"""
PREDICT — Sensor baselines & anomaly detection (Phase 6)

Nightly job computes per-vehicle / per-sensor stats from sensor_readings_1h
and fires ANOMALY alerts (z-score + domain detectors).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text

from app.db.database import async_session_factory
from app.db.models import (
    AlertSeverity,
    Rule,
    RuleType,
    SensorBaseline,
    Trip,
    Vehicle,
)
from app.db.redis_client import redis_client
from app.rules.engine import _create_alert_and_work_order, _has_open_alert, invalidate_rules_cache

logger = logging.getLogger("predict.baselines")

BASELINE_SENSORS = (
    "battery_voltage",
    "control_module_voltage",
    "vehicle_battery_voltage",
    "coolant_temperature",
    "engine_oil_temperature",
    "fuel_level",
    "fuel_consumed",
    "fuel_rate",
)
WINDOW = "30d"
Z_SCORE_THRESHOLD = 3.0
SUSTAINED_BUCKETS = 3
NIGHTLY_INTERVAL_SECONDS = 6 * 3600  # also runs on startup after a short delay
ANOMALY_DEDUP_TTL = 24 * 3600

_task: asyncio.Task | None = None


def _anomaly_key(vehicle_id: int, sensor_type: str, kind: str) -> str:
    return f"anomaly:{vehicle_id}:{sensor_type}:{kind}"


async def _ensure_anomaly_rule(session, name: str, sensor_type: str,
                               severity: AlertSeverity = AlertSeverity.INFO) -> Rule:
    result = await session.execute(
        select(Rule).where(Rule.name == name, Rule.rule_type == RuleType.ANOMALY)
    )
    rule = result.scalar_one_or_none()
    if rule:
        return rule
    rule = Rule(
        name=name,
        description=f"Auto-generated anomaly detector for {sensor_type}",
        rule_type=RuleType.ANOMALY,
        sensor_type=sensor_type,
        operator=">",
        threshold_value=Z_SCORE_THRESHOLD,
        duration_seconds=0,
        severity=severity,
        is_active=True,
    )
    session.add(rule)
    await session.flush()
    invalidate_rules_cache()
    return rule


async def recompute_baselines(session) -> int:
    """Recompute 30d baselines from continuous aggregate. Returns row count."""
    vehicles = (await session.execute(
        select(Vehicle.id).where(Vehicle.is_active == True)  # noqa: E712
    )).scalars().all()
    if not vehicles:
        return 0

    updated = 0
    # Prefer continuous aggregate; fall back to raw if view missing.
    for vehicle_id in vehicles:
        for sensor_type in BASELINE_SENSORS:
            try:
                row = (await session.execute(text(
                    "SELECT avg(avg_value) AS mean, "
                    "       coalesce(stddev_samp(avg_value), 0) AS std, "
                    "       percentile_cont(0.95) WITHIN GROUP (ORDER BY avg_value) AS p95, "
                    "       count(*)::int AS n "
                    "FROM sensor_readings_1h "
                    "WHERE vehicle_id = :vid AND sensor_type = :st "
                    "  AND bucket >= now() - interval '30 days'"
                ), {"vid": vehicle_id, "st": sensor_type})).mappings().first()
            except Exception:
                row = (await session.execute(text(
                    "SELECT avg(value) AS mean, "
                    "       coalesce(stddev_samp(value), 0) AS std, "
                    "       percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95, "
                    "       count(*)::int AS n "
                    "FROM sensor_readings "
                    "WHERE vehicle_id = :vid AND sensor_type = :st "
                    "  AND timestamp >= now() - interval '30 days'"
                ), {"vid": vehicle_id, "st": sensor_type})).mappings().first()

            if not row or not row["n"] or row["mean"] is None:
                continue
            existing = (await session.execute(
                select(SensorBaseline).where(
                    SensorBaseline.vehicle_id == vehicle_id,
                    SensorBaseline.sensor_type == sensor_type,
                    SensorBaseline.window == WINDOW,
                )
            )).scalar_one_or_none()
            if existing is None:
                existing = SensorBaseline(
                    vehicle_id=vehicle_id,
                    sensor_type=sensor_type,
                    window=WINDOW,
                    mean=0.0,
                    std=0.0,
                )
                session.add(existing)
            existing.mean = float(row["mean"])
            existing.std = float(row["std"] or 0.0)
            existing.p95 = float(row["p95"]) if row["p95"] is not None else None
            existing.sample_count = int(row["n"])
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
    await session.flush()
    return updated


async def _recent_z_score(session, vehicle_id: int, sensor_type: str,
                          baseline: SensorBaseline) -> Optional[float]:
    if baseline.std is None or baseline.std < 1e-9:
        return None
    try:
        row = (await session.execute(text(
            "SELECT avg(avg_value) AS v FROM sensor_readings_1h "
            "WHERE vehicle_id = :vid AND sensor_type = :st "
            "  AND bucket >= now() - make_interval(hours => :h)"
        ), {"vid": vehicle_id, "st": sensor_type, "h": SUSTAINED_BUCKETS})).first()
    except Exception:
        row = (await session.execute(text(
            "SELECT avg(value) AS v FROM sensor_readings "
            "WHERE vehicle_id = :vid AND sensor_type = :st "
            "  AND timestamp >= now() - make_interval(hours => :h)"
        ), {"vid": vehicle_id, "st": sensor_type, "h": SUSTAINED_BUCKETS})).first()
    if not row or row[0] is None:
        return None
    return (float(row[0]) - baseline.mean) / baseline.std


async def detect_anomalies(session) -> int:
    """Run z-score + domain detectors; return number of alerts created."""
    fired = 0
    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.is_active == True)  # noqa: E712
    )).scalars().all()
    baselines = (await session.execute(select(SensorBaseline))).scalars().all()
    by_key = {(b.vehicle_id, b.sensor_type): b for b in baselines}

    z_rule = await _ensure_anomaly_rule(
        session, "Sensor Baseline Deviation", "generic", AlertSeverity.INFO
    )
    batt_rule = await _ensure_anomaly_rule(
        session, "Battery Degradation Trend", "battery_voltage", AlertSeverity.WARNING
    )
    cool_rule = await _ensure_anomaly_rule(
        session, "Cooling System Drift", "coolant_temperature", AlertSeverity.WARNING
    )
    fuel_rule = await _ensure_anomaly_rule(
        session, "Fuel Consumption Anomaly", "fuel_consumed", AlertSeverity.WARNING
    )

    for v in vehicles:
        for sensor_type in BASELINE_SENSORS:
            bl = by_key.get((v.id, sensor_type))
            if not bl:
                continue
            z = await _recent_z_score(session, v.id, sensor_type, bl)
            if z is not None and abs(z) >= Z_SCORE_THRESHOLD:
                key = _anomaly_key(v.id, sensor_type, "zscore")
                if not await redis_client.get(key):
                    if not await _has_open_alert(session, v.id, z_rule.id):
                        await _create_alert_and_work_order(
                            session,
                            vehicle_id=v.id,
                            rule=z_rule,
                            title=f"Abnormal {sensor_type.replace('_', ' ')}",
                            message=(
                                f"{sensor_type} is {z:.1f}σ from this vehicle's "
                                f"30-day baseline (mean={bl.mean:.2f})"
                            ),
                            trigger_value=z,
                            ts=datetime.now(timezone.utc),
                            vehicle_name=v.name,
                        )
                        fired += 1
                    await redis_client.set(key, "1", ex=ANOMALY_DEDUP_TTL)

        # Battery: recent mean below baseline mean - 1σ
        for st in ("battery_voltage", "control_module_voltage", "vehicle_battery_voltage"):
            bl = by_key.get((v.id, st))
            if not bl or bl.std < 0.05:
                continue
            z = await _recent_z_score(session, v.id, st, bl)
            if z is not None and z <= -1.5:
                key = _anomaly_key(v.id, st, "battery")
                if not await redis_client.get(key):
                    if not await _has_open_alert(session, v.id, batt_rule.id):
                        await _create_alert_and_work_order(
                            session,
                            vehicle_id=v.id,
                            rule=batt_rule,
                            title="Battery / charging degradation",
                            message=(
                                f"{st} trending low vs 30-day baseline "
                                f"(z={z:.1f}, mean={bl.mean:.2f} V)"
                            ),
                            trigger_value=z,
                            ts=datetime.now(timezone.utc),
                            vehicle_name=v.name,
                        )
                        fired += 1
                    await redis_client.set(key, "1", ex=ANOMALY_DEDUP_TTL)

        # Coolant steady-state creep: recent mean near/above p95
        bl = by_key.get((v.id, "coolant_temperature"))
        if bl and bl.p95 is not None:
            z = await _recent_z_score(session, v.id, "coolant_temperature", bl)
            if z is not None and z >= 1.5:
                key = _anomaly_key(v.id, "coolant_temperature", "creep")
                if not await redis_client.get(key):
                    if not await _has_open_alert(session, v.id, cool_rule.id):
                        await _create_alert_and_work_order(
                            session,
                            vehicle_id=v.id,
                            rule=cool_rule,
                            title="Cooling system drift",
                            message=(
                                f"Coolant steady-state elevated vs baseline "
                                f"(z={z:.1f}, p95={bl.p95:.1f} °C)"
                            ),
                            trigger_value=z,
                            ts=datetime.now(timezone.utc),
                            vehicle_name=v.name,
                        )
                        fired += 1
                    await redis_client.set(key, "1", ex=ANOMALY_DEDUP_TTL)

        # Fuel L/100 km from closed trips (prefer fuel_consumed delta)
        since = datetime.now(timezone.utc) - timedelta(days=7)
        trips = (await session.execute(
            select(Trip).where(
                Trip.vehicle_id == v.id,
                Trip.is_open == False,  # noqa: E712
                Trip.end_ts >= since,
                Trip.distance_km.is_not(None),
                Trip.distance_km > 1,
                Trip.fuel_start.is_not(None),
                Trip.fuel_end.is_not(None),
            )
        )).scalars().all()
        rates = []
        for t in trips:
            # fuel_consumed / liters: end >= start; fuel_level %: end <= start
            delta = t.fuel_end - t.fuel_start
            if delta < 0:
                # percent tank — skip without known capacity
                continue
            if delta <= 0:
                continue
            rates.append((delta / t.distance_km) * 100.0)
        if len(rates) >= 3:
            mean_r = sum(rates) / len(rates)
            var = sum((r - mean_r) ** 2 for r in rates) / (len(rates) - 1)
            std_r = var ** 0.5
            latest = rates[-1]
            if std_r > 0.1 and abs(latest - mean_r) / std_r >= 3.0:
                key = _anomaly_key(v.id, "fuel", "l100")
                if not await redis_client.get(key):
                    if not await _has_open_alert(session, v.id, fuel_rule.id):
                        await _create_alert_and_work_order(
                            session,
                            vehicle_id=v.id,
                            rule=fuel_rule,
                            title="Fuel consumption anomaly",
                            message=(
                                f"Recent trip {latest:.1f} L/100 km vs "
                                f"7-day mean {mean_r:.1f} (±{std_r:.1f})"
                            ),
                            trigger_value=latest,
                            ts=datetime.now(timezone.utc),
                            vehicle_name=v.name,
                        )
                        fired += 1
                    await redis_client.set(key, "1", ex=ANOMALY_DEDUP_TTL)

    await session.commit()
    return fired


async def run_baselines_once() -> None:
    async with async_session_factory() as session:
        n = await recompute_baselines(session)
        await session.commit()
        fired = await detect_anomalies(session)
        logger.info("Baselines updated=%d anomaly_alerts=%d", n, fired)


async def _run() -> None:
    await asyncio.sleep(60)  # let startup settle
    while True:
        try:
            await run_baselines_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Baselines job failed: %s", e)
        await asyncio.sleep(NIGHTLY_INTERVAL_SECONDS)


def start_baselines_job() -> None:
    global _task
    _task = asyncio.create_task(_run())
    logger.info("Baselines/anomaly job started (every %ds)", NIGHTLY_INTERVAL_SECONDS)


async def stop_baselines_job() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
