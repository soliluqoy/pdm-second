"""
PREDICT — Rule Engine
Evaluates threshold, DTC, scheduled, and behavior rules against incoming
telemetry / event counts. Creates alerts + work orders, recomputes vehicle
health, broadcasts via Redis pub/sub.

Performance notes:
- Active rules are cached in-process (TTL + explicit invalidation from the
  rules CRUD API) so the ingestion hot path doesn't re-query them per message.
- The caller (MQTT ingestion) passes its DB session and the vehicle row so no
  extra session/queries are opened per telemetry record.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy import func, select

from app.config import settings
from app.db.database import async_session_factory
from app.db.models import (
    Alert,
    AlertStatus,
    DrivingEvent,
    DrivingEventType,
    MaintenanceHistory,
    Rule,
    RuleType,
    Vehicle,
    WorkOrder,
    WorkOrderStatus,
    WorkOrderTemplate,
)
from app.db.redis_client import (
    publish_alert,
    publish_health_update,
    publish_work_order,
    redis_client,
)
from app.services.health import recompute_health
from app.services.settings_service import get_shadow_mode

logger = logging.getLogger("predict.rules")

# Tolerance for float equality rules — exact == is useless on telemetry floats.
EQUALITY_EPSILON = 1e-6

OPERATORS = {
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: abs(v - t) <= EQUALITY_EPSILON,
}

# Sensor types a SCHEDULED rule can track (monotonically increasing counters).
SCHEDULED_SENSOR_TYPES = ("odometer", "engine_hours")

# Behavior rules use sensor_type as the driving event type name.
BEHAVIOR_EVENT_TYPES = tuple(e.value for e in DrivingEventType)


# ── In-process rule cache ─────────────────────────────────────────────────────
class _RuleCache:
    """Cached active rules, refreshed on TTL expiry or explicit invalidation."""

    def __init__(self):
        self._rules: List[Rule] = []
        self._loaded_at: float = 0.0
        self._dirty = True

    def invalidate(self) -> None:
        self._dirty = True

    async def get(self, session) -> List[Rule]:
        now = time.monotonic()
        if self._dirty or (now - self._loaded_at) > settings.RULES_CACHE_TTL_SECONDS:
            result = await session.execute(
                select(Rule).where(Rule.is_active == True)  # noqa: E712
            )
            # Detached read-only use is safe: expire_on_commit=False and no
            # lazy relationships are accessed during evaluation.
            self._rules = list(result.scalars().all())
            self._loaded_at = now
            self._dirty = False
        return self._rules


_rule_cache = _RuleCache()


def invalidate_rules_cache() -> None:
    """Called by the rules CRUD API after create/update/delete."""
    _rule_cache.invalidate()


# ── Value helpers ─────────────────────────────────────────────────────────────
def _extract_value(sensor_data: Any) -> Optional[float]:
    if sensor_data is None:
        return None
    if isinstance(sensor_data, dict):
        val = sensor_data.get("value")
    else:
        val = sensor_data
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _condition_met(value: float, operator: str, threshold: float) -> bool:
    fn = OPERATORS.get(operator)
    if fn is None:
        return False
    return fn(value, threshold)


# ── Sustained-duration tracking (Redis) ───────────────────────────────────────
def _duration_key(rule_id: int, vehicle_id: int) -> str:
    return f"rule:{rule_id}:vehicle:{vehicle_id}:since"


def _duration_ttl(duration_seconds: int) -> int:
    """Keys self-expire so a vehicle that stops reporting doesn't leak keys,
    and a very old 'since' can't satisfy a freshly resumed condition."""
    return max(duration_seconds * 3, 900)


async def _check_duration(rule_id: int, vehicle_id: int, ts: datetime, duration_seconds: int) -> bool:
    """Return True when the sustained condition has been met long enough to fire."""
    if duration_seconds <= 0:
        return True
    key = _duration_key(rule_id, vehicle_id)
    ttl = _duration_ttl(duration_seconds)
    since_str = await redis_client.get(key)
    if since_str is None:
        await redis_client.set(key, ts.isoformat(), ex=ttl)
        return False
    # Refresh expiry while the condition holds
    await redis_client.expire(key, ttl)
    since = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    elapsed = (ts - since).total_seconds()
    return elapsed >= duration_seconds


async def _reset_duration(rule_id: int, vehicle_id: int) -> None:
    await redis_client.delete(_duration_key(rule_id, vehicle_id))


# ── Alert dedupe ──────────────────────────────────────────────────────────────
async def _has_open_alert(session, vehicle_id: int, rule_id: int) -> bool:
    result = await session.execute(
        select(Alert.id).where(
            Alert.vehicle_id == vehicle_id,
            Alert.rule_id == rule_id,
            Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── Alert + work order creation ───────────────────────────────────────────────
async def _create_alert_and_work_order(
    session,
    *,
    vehicle_id: int,
    rule: Rule,
    title: str,
    message: str,
    trigger_value: Optional[float],
    ts: datetime,
    vehicle_name: str,
) -> None:
    shadow_mode = await get_shadow_mode(session)

    alert = Alert(
        vehicle_id=vehicle_id,
        rule_id=rule.id,
        severity=rule.severity,
        status=AlertStatus.ACTIVE,
        title=title,
        message=message,
        trigger_value=trigger_value,
        trigger_timestamp=ts,
    )
    session.add(alert)
    await session.flush()

    wo = None
    if rule.work_order_template_id:
        tpl_result = await session.execute(
            select(WorkOrderTemplate).where(WorkOrderTemplate.id == rule.work_order_template_id)
        )
        template = tpl_result.scalar_one_or_none()
        if template:
            wo_status = WorkOrderStatus.SHADOW if shadow_mode else WorkOrderStatus.OPEN
            wo = WorkOrder(
                vehicle_id=vehicle_id,
                alert_id=alert.id,
                template_id=template.id,
                title=template.name,
                description=template.description,
                priority=template.default_priority,
                status=wo_status,
                instructions=template.instructions,
                is_shadow=shadow_mode,
            )
            session.add(wo)
            await session.flush()
            alert.work_order_id = wo.id

    new_health = await recompute_health(session, vehicle_id)
    await session.commit()

    alert_payload = {
        "id": alert.id,
        "vehicle_id": vehicle_id,
        "vehicle_name": vehicle_name,
        "rule_id": rule.id,
        "severity": rule.severity.value,
        "status": AlertStatus.ACTIVE.value,
        "title": title,
        "message": message,
        "trigger_value": trigger_value,
        "work_order_id": alert.work_order_id,
    }
    await publish_alert(alert_payload)

    if wo:
        wo_payload = {
            "id": wo.id,
            "vehicle_id": vehicle_id,
            "vehicle_name": vehicle_name,
            "alert_id": alert.id,
            "title": wo.title,
            "status": wo.status.value,
            "priority": wo.priority.value,
            "is_shadow": wo.is_shadow,
        }
        await publish_work_order(wo_payload)

    if new_health:
        await publish_health_update(vehicle_id, new_health.value)

    logger.info(
        "Rule triggered: vehicle=%s rule=%s alert=%s wo=%s health=%s",
        vehicle_name, rule.name, alert.id, wo.id if wo else None, new_health,
    )


def _rule_applies_to_vehicle(rule: Rule, vehicle_id: int) -> bool:
    return rule.vehicle_id is None or rule.vehicle_id == vehicle_id


# ── Threshold evaluation ──────────────────────────────────────────────────────
async def evaluate_telemetry(
    vehicle_id: int,
    imei: str,
    sensors: dict,
    ts: datetime,
    session=None,
    vehicle_name: Optional[str] = None,
) -> None:
    """Evaluate active threshold + scheduled rules against incoming readings.

    The ingestion service passes its session and the vehicle name; standalone
    callers (tests, scripts) can omit them.
    """
    if session is not None:
        await _evaluate_telemetry(session, vehicle_id, sensors, ts, vehicle_name)
        return
    async with async_session_factory() as own_session:
        await _evaluate_telemetry(own_session, vehicle_id, sensors, ts, vehicle_name)


async def _evaluate_telemetry(session, vehicle_id: int, sensors: dict, ts: datetime,
                              vehicle_name: Optional[str]) -> None:
    if vehicle_name is None:
        vresult = await session.execute(
            select(Vehicle.name).where(Vehicle.id == vehicle_id)
        )
        vehicle_name = vresult.scalar_one_or_none()
        if vehicle_name is None:
            return

    rules = await _rule_cache.get(session)

    for rule in rules:
        if not _rule_applies_to_vehicle(rule, vehicle_id):
            continue
        if rule.rule_type == RuleType.THRESHOLD:
            await _evaluate_threshold_rule(session, rule, vehicle_id, vehicle_name, sensors, ts)
        elif rule.rule_type == RuleType.SCHEDULED:
            await _evaluate_scheduled_rule(session, rule, vehicle_id, vehicle_name, sensors, ts)


async def _evaluate_threshold_rule(session, rule: Rule, vehicle_id: int,
                                   vehicle_name: str, sensors: dict, ts: datetime) -> None:
    if not rule.sensor_type or rule.threshold_value is None or not rule.operator:
        return

    if rule.sensor_type not in sensors:
        # AVL records legitimately omit IO elements. Absence is "no
        # information": keep any running duration window (it self-expires via
        # TTL) instead of resetting it — otherwise sparse records make
        # sustained conditions unfireable.
        return

    value = _extract_value(sensors.get(rule.sensor_type))
    if value is None:
        return

    if not _condition_met(value, rule.operator, rule.threshold_value):
        await _reset_duration(rule.id, vehicle_id)
        return

    if not await _check_duration(rule.id, vehicle_id, ts, rule.duration_seconds or 0):
        return

    if await _has_open_alert(session, vehicle_id, rule.id):
        return

    title = rule.name
    message = (
        f"{rule.description or rule.name}: "
        f"{rule.sensor_type}={value} (threshold {rule.operator} {rule.threshold_value})"
    )
    await _create_alert_and_work_order(
        session,
        vehicle_id=vehicle_id,
        rule=rule,
        title=title,
        message=message,
        trigger_value=value,
        ts=ts,
        vehicle_name=vehicle_name,
    )
    await _reset_duration(rule.id, vehicle_id)


# ── Scheduled (interval) evaluation ───────────────────────────────────────────
def _scheduled_key(rule_id: int, vehicle_id: int) -> str:
    return f"rule:{rule_id}:vehicle:{vehicle_id}:next_due"


async def reset_scheduled_next_due(rule_id: int, vehicle_id: int, current_value: float,
                                   interval_value: float) -> None:
    """Re-anchor next_due after scheduled maintenance is completed."""
    await redis_client.set(
        _scheduled_key(rule_id, vehicle_id),
        str(current_value + interval_value),
    )


async def _has_completed_scheduled_service(session, rule_id: int, vehicle_id: int) -> bool:
    """True if a WO from this rule was completed (maintenance_history exists)."""
    result = await session.execute(
        select(MaintenanceHistory.id)
        .join(WorkOrder, WorkOrder.id == MaintenanceHistory.work_order_id)
        .join(Alert, Alert.id == WorkOrder.alert_id)
        .where(
            MaintenanceHistory.vehicle_id == vehicle_id,
            Alert.rule_id == rule_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _evaluate_scheduled_rule(session, rule: Rule, vehicle_id: int,
                                   vehicle_name: str, sensors: dict, ts: datetime) -> None:
    """Interval maintenance on a monotonically increasing counter.

    sensor_type must be 'odometer' or 'engine_hours' and interval_value the
    service interval in that unit. First sighting anchors next_due at
    current + interval. Completing a scheduled WO re-anchors via
    ``reset_scheduled_next_due`` (see workorders.complete).
    """
    if (not rule.interval_value or rule.interval_value <= 0
            or rule.sensor_type not in SCHEDULED_SENSOR_TYPES):
        return

    value = _extract_value(sensors.get(rule.sensor_type))
    if value is None:
        return

    key = _scheduled_key(rule.id, vehicle_id)
    next_due_raw = await redis_client.get(key)
    if next_due_raw is None:
        # Fresh anchor. If prior scheduled service exists in history the
        # counter still advances from "now + interval" (we don't store the
        # odometer at service time); WO completion resets explicitly.
        await redis_client.set(key, str(value + rule.interval_value))
        if await _has_completed_scheduled_service(session, rule.id, vehicle_id):
            logger.debug(
                "Scheduled rule %s vehicle %s: redis empty but history exists — "
                "anchored at current+interval",
                rule.id, vehicle_id,
            )
        return

    try:
        next_due = float(next_due_raw)
    except (TypeError, ValueError):
        await redis_client.set(key, str(value + rule.interval_value))
        return

    if value < next_due:
        return

    if not await _has_open_alert(session, vehicle_id, rule.id):
        unit = "km" if rule.sensor_type == "odometer" else "h"
        title = rule.name
        message = (
            f"{rule.description or rule.name}: {rule.sensor_type} reached "
            f"{value:.0f}{unit} (interval {rule.interval_value:.0f}{unit})"
        )
        await _create_alert_and_work_order(
            session,
            vehicle_id=vehicle_id,
            rule=rule,
            title=title,
            message=message,
            trigger_value=value,
            ts=ts,
            vehicle_name=vehicle_name,
        )
    # Re-anchor whether or not a duplicate alert was suppressed.
    await redis_client.set(key, str(value + rule.interval_value))


# ── Behavior (daily event counts) ─────────────────────────────────────────────
async def evaluate_behavior_rules(
    vehicle_id: int,
    session=None,
    vehicle_name: Optional[str] = None,
    ts: Optional[datetime] = None,
) -> None:
    """Evaluate BEHAVIOR rules against today's driving-event counts."""
    if session is not None:
        await _evaluate_behavior_rules(session, vehicle_id, vehicle_name, ts)
        return
    async with async_session_factory() as own_session:
        await _evaluate_behavior_rules(own_session, vehicle_id, vehicle_name, ts)


async def _evaluate_behavior_rules(session, vehicle_id: int,
                                   vehicle_name: Optional[str],
                                   ts: Optional[datetime]) -> None:
    if ts is None:
        ts = datetime.now(timezone.utc)
    if vehicle_name is None:
        vresult = await session.execute(
            select(Vehicle.name).where(Vehicle.id == vehicle_id)
        )
        vehicle_name = vresult.scalar_one_or_none()
        if vehicle_name is None:
            return

    rules = await _rule_cache.get(session)
    day_start = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    for rule in rules:
        if rule.rule_type != RuleType.BEHAVIOR:
            continue
        if not _rule_applies_to_vehicle(rule, vehicle_id):
            continue
        if (not rule.sensor_type or rule.sensor_type not in BEHAVIOR_EVENT_TYPES
                or rule.threshold_value is None):
            continue

        try:
            et = DrivingEventType(rule.sensor_type)
        except ValueError:
            continue

        count = (await session.execute(
            select(func.count()).select_from(DrivingEvent).where(
                DrivingEvent.vehicle_id == vehicle_id,
                DrivingEvent.event_type == et,
                DrivingEvent.ts >= day_start,
                DrivingEvent.ts < day_end,
            )
        )).scalar() or 0

        op = rule.operator or ">="
        if not _condition_met(float(count), op, float(rule.threshold_value)):
            continue
        if await _has_open_alert(session, vehicle_id, rule.id):
            continue

        await _create_alert_and_work_order(
            session,
            vehicle_id=vehicle_id,
            rule=rule,
            title=rule.name,
            message=(
                f"{rule.description or rule.name}: {count} {rule.sensor_type} "
                f"events today (threshold {op} {rule.threshold_value:.0f})"
            ),
            trigger_value=float(count),
            ts=ts,
            vehicle_name=vehicle_name,
        )


# ── DTC evaluation ────────────────────────────────────────────────────────────
async def evaluate_dtc(
    vehicle_id: int,
    imei: str,
    dtc_code: str,
    description: str,
    severity: str,
    session=None,
    vehicle_name: Optional[str] = None,
) -> None:
    """Evaluate DTC rules against an incoming diagnostic trouble code."""
    if not dtc_code:
        return
    if session is not None:
        await _evaluate_dtc(session, vehicle_id, dtc_code, description, vehicle_name)
        return
    async with async_session_factory() as own_session:
        await _evaluate_dtc(own_session, vehicle_id, dtc_code, description, vehicle_name)


async def _evaluate_dtc(session, vehicle_id: int, dtc_code: str,
                        description: str, vehicle_name: Optional[str]) -> None:
    if vehicle_name is None:
        vresult = await session.execute(
            select(Vehicle.name).where(Vehicle.id == vehicle_id)
        )
        vehicle_name = vresult.scalar_one_or_none()
        if vehicle_name is None:
            return

    rules = [
        r for r in await _rule_cache.get(session)
        if r.rule_type == RuleType.DTC and r.dtc_code == dtc_code
        and _rule_applies_to_vehicle(r, vehicle_id)
    ]
    if not rules:
        logger.debug("No DTC rule for code %s (vehicle %s)", dtc_code, vehicle_name)
        return

    ts = datetime.now(timezone.utc)
    for rule in rules:
        if await _has_open_alert(session, vehicle_id, rule.id):
            continue

        title = rule.name
        message = f"{description or rule.description} (DTC: {dtc_code})"
        await _create_alert_and_work_order(
            session,
            vehicle_id=vehicle_id,
            rule=rule,
            title=title,
            message=message,
            trigger_value=None,
            ts=ts,
            vehicle_name=vehicle_name,
        )
