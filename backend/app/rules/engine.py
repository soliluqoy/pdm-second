"""
PREDICT — Rule Engine
Evaluates threshold and DTC rules against incoming telemetry.
Creates alerts + work orders, recomputes vehicle health, broadcasts via Redis pub/sub.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.config import settings
from app.db.database import async_session_factory
from app.db.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    Rule,
    RuleType,
    SystemConfig,
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

logger = logging.getLogger("predict.rules")

OPERATORS = {
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t,
}


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


async def _get_shadow_mode(session) -> bool:
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "shadow_mode")
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        return cfg.value.lower() == "true"
    return settings.SHADOW_MODE


def _duration_key(rule_id: int, vehicle_id: int) -> str:
    return f"rule:{rule_id}:vehicle:{vehicle_id}:since"


async def _check_duration(rule_id: int, vehicle_id: int, ts: datetime, duration_seconds: int) -> bool:
    """Return True when the sustained condition has been met long enough to fire."""
    if duration_seconds <= 0:
        return True
    key = _duration_key(rule_id, vehicle_id)
    since_str = await redis_client.get(key)
    if since_str is None:
        await redis_client.set(key, ts.isoformat())
        return False
    since = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    elapsed = (ts - since).total_seconds()
    return elapsed >= duration_seconds


async def _reset_duration(rule_id: int, vehicle_id: int) -> None:
    await redis_client.delete(_duration_key(rule_id, vehicle_id))


async def _has_open_alert(session, vehicle_id: int, rule_id: int) -> bool:
    result = await session.execute(
        select(Alert.id).where(
            Alert.vehicle_id == vehicle_id,
            Alert.rule_id == rule_id,
            Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


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
    shadow_mode = await _get_shadow_mode(session)

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


async def evaluate_telemetry(
    vehicle_id: int,
    imei: str,
    sensors: dict,
    ts: datetime,
) -> None:
    """Evaluate all active threshold rules against incoming sensor readings."""
    async with async_session_factory() as session:
        vresult = await session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
        vehicle = vresult.scalar_one_or_none()
        if not vehicle:
            return
        vehicle_name = vehicle.name

        rules_result = await session.execute(
            select(Rule).where(Rule.is_active == True, Rule.rule_type == RuleType.THRESHOLD)
        )
        rules = rules_result.scalars().all()

        for rule in rules:
            if not rule.sensor_type or rule.threshold_value is None or not rule.operator:
                continue

            raw = sensors.get(rule.sensor_type)
            value = _extract_value(raw)
            if value is None:
                await _reset_duration(rule.id, vehicle_id)
                continue

            if not _condition_met(value, rule.operator, rule.threshold_value):
                await _reset_duration(rule.id, vehicle_id)
                continue

            if not await _check_duration(rule.id, vehicle_id, ts, rule.duration_seconds or 0):
                continue

            if await _has_open_alert(session, vehicle_id, rule.id):
                continue

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


async def evaluate_dtc(
    vehicle_id: int,
    imei: str,
    dtc_code: str,
    description: str,
    severity: str,
) -> None:
    """Evaluate DTC rules against an incoming diagnostic trouble code."""
    if not dtc_code:
        return

    async with async_session_factory() as session:
        vresult = await session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
        vehicle = vresult.scalar_one_or_none()
        if not vehicle:
            return
        vehicle_name = vehicle.name

        rules_result = await session.execute(
            select(Rule).where(
                Rule.is_active == True,
                Rule.rule_type == RuleType.DTC,
                Rule.dtc_code == dtc_code,
            )
        )
        rules = rules_result.scalars().all()
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
