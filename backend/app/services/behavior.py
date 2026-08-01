"""
PREDICT — Driving behavior analytics (Phase 5)

Trip segmentation (ignition / movement fallback), Tier-2 derived events
(harsh accel/brake, speeding, idle, high RPM), daily per-vehicle scores,
and persistence of device-native eco-driving events.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from app.db.models import (
    DriverScore,
    DrivingEvent,
    DrivingEventSource,
    DrivingEventType,
    SystemConfig,
    Trip,
)
from app.db.redis_client import redis_client

logger = logging.getLogger("predict.behavior")


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

TRIP_GAP_SECONDS = 300  # movement/speed fallback gap
SPEED_NEAR_ZERO = 3.0   # km/h — treat as stopped
SPEEDING_CONSECUTIVE = 2
STATE_TTL = 48 * 3600

_DEFAULT_WEIGHTS = {
    "harsh_accel": 8,
    "harsh_brake": 10,
    "harsh_corner": 8,
    "speeding": 6,
    "idling": 3,
    "high_rpm": 4,
}

_config_cache: dict[str, Any] = {}
_config_cached_at: float = 0.0
_CONFIG_TTL = 30.0


def _state_key(vehicle_id: int) -> str:
    return f"behavior:vehicle:{vehicle_id}:trip"


async def _load_config(session) -> dict[str, Any]:
    global _config_cache, _config_cached_at
    now = time.monotonic()
    if _config_cache and (now - _config_cached_at) < _CONFIG_TTL:
        return _config_cache

    keys = (
        "behavior.speed_limit_kmh",
        "behavior.idle_minutes",
        "behavior.accel_threshold_ms2",
        "behavior.high_rpm_threshold",
        "behavior.score_weights",
    )
    result = await session.execute(
        select(SystemConfig.key, SystemConfig.value).where(SystemConfig.key.in_(keys))
    )
    rows = {k: v for k, v in result.all()}
    weights = dict(_DEFAULT_WEIGHTS)
    raw_w = rows.get("behavior.score_weights")
    if raw_w:
        try:
            weights.update(json.loads(raw_w))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    cfg = {
        "speed_limit_kmh": float(rows.get("behavior.speed_limit_kmh") or 120),
        "idle_minutes": float(rows.get("behavior.idle_minutes") or 5),
        "accel_threshold_ms2": float(rows.get("behavior.accel_threshold_ms2") or 3.0),
        "high_rpm_threshold": float(rows.get("behavior.high_rpm_threshold") or 4000),
        "score_weights": weights,
    }
    _config_cache = cfg
    _config_cached_at = now
    return cfg


async def _get_redis_state(vehicle_id: int) -> dict:
    raw = await redis_client.get(_state_key(vehicle_id))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


async def _set_redis_state(vehicle_id: int, state: dict) -> None:
    await redis_client.set(
        _state_key(vehicle_id), json.dumps(state, default=str), ex=STATE_TTL
    )


def _sensor_speed(sensors: dict, gps: Optional[dict]) -> Optional[float]:
    for key in ("vehicle_speed_obd", "vehicle_speed"):
        v = _extract_value(sensors.get(key))
        if v is not None:
            return v
    if gps and gps.get("speed") is not None:
        try:
            return float(gps["speed"])
        except (TypeError, ValueError):
            return None
    return None


def _sensor_fuel(sensors: dict) -> Optional[float]:
    for key in ("fuel_consumed", "fuel_level_liters", "fuel_level"):
        v = _extract_value(sensors.get(key))
        if v is not None:
            return v
    return None


def _parse_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    try:
        return bool(int(val))
    except (TypeError, ValueError):
        return bool(val)


async def _open_trip(session, vehicle_id: int) -> Optional[Trip]:
    result = await session.execute(
        select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.is_open == True)  # noqa: E712
        .order_by(Trip.start_ts.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _start_trip(
    session,
    vehicle_id: int,
    ts: datetime,
    odometer: Optional[float],
    fuel: Optional[float],
    state: dict,
) -> Trip:
    trip = Trip(
        vehicle_id=vehicle_id,
        start_ts=ts,
        start_odometer=odometer,
        fuel_start=fuel,
        idle_seconds=0,
        is_open=True,
        max_speed=0.0,
        avg_speed=0.0,
    )
    session.add(trip)
    await session.flush()
    state["trip_id"] = trip.id
    state["speed_sum"] = 0.0
    state["speed_n"] = 0
    state["idle_accum"] = 0.0
    state["idle_since"] = None
    state["speeding_streak"] = 0
    state["high_rpm_latched"] = False
    state["last_idle_event_ts"] = None
    logger.debug("Trip started vehicle=%s trip=%s", vehicle_id, trip.id)
    return trip


async def _end_trip(
    session,
    trip: Trip,
    ts: datetime,
    odometer: Optional[float],
    fuel: Optional[float],
    state: dict,
) -> None:
    trip.end_ts = ts
    trip.end_odometer = odometer
    trip.fuel_end = fuel
    trip.is_open = False
    if trip.start_odometer is not None and odometer is not None and odometer >= trip.start_odometer:
        trip.distance_km = round(odometer - trip.start_odometer, 3)
    trip.duration_seconds = max(0, int((ts - trip.start_ts).total_seconds()))
    trip.idle_seconds = int(state.get("idle_accum") or 0)
    n = int(state.get("speed_n") or 0)
    if n > 0:
        trip.avg_speed = round(float(state.get("speed_sum") or 0) / n, 2)
    trip.max_speed = state.get("max_speed")
    await session.flush()
    state["trip_id"] = None
    logger.debug("Trip ended vehicle=%s trip=%s dist=%s", trip.vehicle_id, trip.id, trip.distance_km)
    await recompute_daily_score(session, trip.vehicle_id, trip.start_ts.date())


async def _add_event(
    session,
    *,
    vehicle_id: int,
    trip_id: Optional[int],
    ts: datetime,
    event_type: DrivingEventType,
    value: Optional[float],
    latitude: Optional[float],
    longitude: Optional[float],
    source: DrivingEventSource,
) -> DrivingEvent:
    ev = DrivingEvent(
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        ts=ts,
        event_type=event_type,
        value=value,
        latitude=latitude,
        longitude=longitude,
        source=source,
    )
    session.add(ev)
    return ev


async def record_device_event(
    session,
    *,
    vehicle_id: int,
    ts: datetime,
    event_type: str,
    value: Optional[float],
    latitude: Optional[float],
    longitude: Optional[float],
) -> Optional[DrivingEvent]:
    """Persist a Tier-1 device eco-driving / overspeeding event."""
    try:
        et = DrivingEventType(event_type)
    except ValueError:
        logger.warning("Unknown device event_type=%r vehicle=%s", event_type, vehicle_id)
        return None
    trip = await _open_trip(session, vehicle_id)
    ev = await _add_event(
        session,
        vehicle_id=vehicle_id,
        trip_id=trip.id if trip else None,
        ts=ts,
        event_type=et,
        value=value,
        latitude=latitude,
        longitude=longitude,
        source=DrivingEventSource.DEVICE,
    )
    await session.flush()
    if trip:
        await recompute_daily_score(session, vehicle_id, ts.date())
    return ev


async def process_telemetry(
    session,
    *,
    vehicle_id: int,
    ts: datetime,
    sensors: dict,
    ignition: Optional[bool],
    movement: Optional[bool],
    gps: Optional[dict],
) -> None:
    """Update trip state machine and derive Tier-2 events from one telemetry record."""
    cfg = await _load_config(session)
    state = await _get_redis_state(vehicle_id)

    speed = _sensor_speed(sensors, gps)
    odometer = _extract_value(sensors.get("odometer"))
    fuel = _sensor_fuel(sensors)
    rpm = _extract_value(sensors.get("engine_rpm"))
    lat = (gps or {}).get("latitude")
    lon = (gps or {}).get("longitude")
    movement_b = _parse_bool(movement)

    prev_ign = state.get("last_ignition")
    prev_ts_raw = state.get("last_ts")
    prev_speed = state.get("last_speed")
    prev_ts: Optional[datetime] = None
    if prev_ts_raw:
        try:
            prev_ts = datetime.fromisoformat(prev_ts_raw)
            if prev_ts.tzinfo is None:
                prev_ts = prev_ts.replace(tzinfo=timezone.utc)
        except ValueError:
            prev_ts = None

    trip = await _open_trip(session, vehicle_id)

    # ── Trip boundaries ───────────────────────────────────────────────────────
    start_trip = False
    end_trip = False

    if ignition is True and prev_ign is False:
        start_trip = True
    elif ignition is False and prev_ign is True:
        end_trip = True
    else:
        # Fallback: movement + speed after gap, or stop after gap
        gap = (ts - prev_ts).total_seconds() if prev_ts else None
        if trip is None and gap is not None and gap > TRIP_GAP_SECONDS:
            if (movement_b is True or (speed is not None and speed > SPEED_NEAR_ZERO)):
                start_trip = True
        if trip is not None and gap is not None and gap > TRIP_GAP_SECONDS:
            if (movement_b is False or movement_b is None) and (
                speed is None or speed <= SPEED_NEAR_ZERO
            ):
                end_trip = True

    if start_trip and trip is None:
        trip = await _start_trip(session, vehicle_id, ts, odometer, fuel, state)
    if end_trip and trip is not None:
        await _end_trip(session, trip, ts, odometer, fuel, state)
        trip = None

    # ── In-trip aggregates + Tier-2 ───────────────────────────────────────────
    if trip is not None:
        if speed is not None:
            state["speed_sum"] = float(state.get("speed_sum") or 0) + speed
            state["speed_n"] = int(state.get("speed_n") or 0) + 1
            prev_max = state.get("max_speed")
            if prev_max is None or speed > prev_max:
                state["max_speed"] = speed
            trip.max_speed = state["max_speed"]

        # Harsh accel / brake from Δspeed/Δt
        if (
            speed is not None and prev_speed is not None and prev_ts is not None
            and (ts - prev_ts).total_seconds() > 0
        ):
            dt = (ts - prev_ts).total_seconds()
            # km/h → m/s
            accel = ((speed - prev_speed) * (1000.0 / 3600.0)) / dt
            thr = cfg["accel_threshold_ms2"]
            if accel > thr:
                await _add_event(
                    session, vehicle_id=vehicle_id, trip_id=trip.id, ts=ts,
                    event_type=DrivingEventType.HARSH_ACCEL, value=round(accel, 3),
                    latitude=lat, longitude=lon, source=DrivingEventSource.DERIVED,
                )
            elif accel < -thr:
                await _add_event(
                    session, vehicle_id=vehicle_id, trip_id=trip.id, ts=ts,
                    event_type=DrivingEventType.HARSH_BRAKE, value=round(abs(accel), 3),
                    latitude=lat, longitude=lon, source=DrivingEventSource.DERIVED,
                )

        # Speeding streak
        if speed is not None and speed > cfg["speed_limit_kmh"]:
            streak = int(state.get("speeding_streak") or 0) + 1
            state["speeding_streak"] = streak
            if streak == SPEEDING_CONSECUTIVE:
                await _add_event(
                    session, vehicle_id=vehicle_id, trip_id=trip.id, ts=ts,
                    event_type=DrivingEventType.SPEEDING, value=speed,
                    latitude=lat, longitude=lon, source=DrivingEventSource.DERIVED,
                )
        else:
            state["speeding_streak"] = 0

        # High RPM while moving
        moving = speed is not None and speed > SPEED_NEAR_ZERO
        if moving and rpm is not None and rpm >= cfg["high_rpm_threshold"]:
            if not state.get("high_rpm_latched"):
                await _add_event(
                    session, vehicle_id=vehicle_id, trip_id=trip.id, ts=ts,
                    event_type=DrivingEventType.HIGH_RPM, value=rpm,
                    latitude=lat, longitude=lon, source=DrivingEventSource.DERIVED,
                )
                state["high_rpm_latched"] = True
        else:
            state["high_rpm_latched"] = False

        # Idling: ignition on (or unknown) + near-zero speed
        ign_on = ignition is True or (ignition is None and trip is not None)
        if ign_on and (speed is None or speed <= SPEED_NEAR_ZERO):
            idle_since = state.get("idle_since")
            if idle_since is None:
                state["idle_since"] = ts.isoformat()
            else:
                try:
                    idle_start = datetime.fromisoformat(idle_since)
                    if idle_start.tzinfo is None:
                        idle_start = idle_start.replace(tzinfo=timezone.utc)
                except ValueError:
                    idle_start = ts
                    state["idle_since"] = ts.isoformat()
                idle_secs = (ts - idle_start).total_seconds()
                need = cfg["idle_minutes"] * 60
                last_ev = state.get("last_idle_event_ts")
                if idle_secs >= need and last_ev != state["idle_since"]:
                    await _add_event(
                        session, vehicle_id=vehicle_id, trip_id=trip.id, ts=ts,
                        event_type=DrivingEventType.IDLING, value=round(idle_secs / 60, 2),
                        latitude=lat, longitude=lon, source=DrivingEventSource.DERIVED,
                    )
                    state["last_idle_event_ts"] = state["idle_since"]
                # Accumulate idle time sample-to-sample
                if prev_ts is not None:
                    dt = (ts - prev_ts).total_seconds()
                    if 0 < dt < 120:
                        state["idle_accum"] = float(state.get("idle_accum") or 0) + dt
                        trip.idle_seconds = int(state["idle_accum"])
        else:
            state["idle_since"] = None

    # Persist rolling state
    if ignition is not None:
        state["last_ignition"] = ignition
    if movement_b is not None:
        state["last_movement"] = movement_b
    if speed is not None:
        state["last_speed"] = speed
    state["last_ts"] = ts.isoformat()
    await _set_redis_state(vehicle_id, state)
    await session.flush()


async def recompute_daily_score(session, vehicle_id: int, day: date) -> DriverScore:
    """Recompute driver_scores for one vehicle/day from trips + events."""
    cfg = await _load_config(session)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    trip_rows = await session.execute(
        select(Trip).where(
            Trip.vehicle_id == vehicle_id,
            Trip.start_ts >= start,
            Trip.start_ts < end,
            Trip.is_open == False,  # noqa: E712
        )
    )
    trips = list(trip_rows.scalars().all())
    distance = sum(t.distance_km or 0.0 for t in trips)
    idle_secs = sum(t.idle_seconds or 0 for t in trips)
    duration = sum(t.duration_seconds or 0 for t in trips)

    ev_rows = await session.execute(
        select(DrivingEvent.event_type, func.count())
        .where(
            DrivingEvent.vehicle_id == vehicle_id,
            DrivingEvent.ts >= start,
            DrivingEvent.ts < end,
        )
        .group_by(DrivingEvent.event_type)
    )
    counts = {et.value if hasattr(et, "value") else str(et): int(c) for et, c in ev_rows.all()}

    denom = max(distance, 1.0)
    per_100: dict[str, float] = {}
    penalty = 0.0
    weights = cfg["score_weights"]
    for etype, count in counts.items():
        rate = (count / denom) * 100.0
        per_100[etype] = round(rate, 2)
        penalty += rate * float(weights.get(etype, 0))

    idle_ratio = (idle_secs / duration) if duration > 0 else 0.0
    penalty += idle_ratio * 20.0
    score = max(0.0, min(100.0, 100.0 - penalty))

    existing = await session.execute(
        select(DriverScore).where(
            DriverScore.vehicle_id == vehicle_id, DriverScore.date == day
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = DriverScore(vehicle_id=vehicle_id, date=day)
        session.add(row)
    row.trips = len(trips)
    row.distance_km = round(distance, 3)
    row.events_per_100km = per_100
    row.idle_ratio = round(idle_ratio, 4)
    row.score = round(score, 1)
    await session.flush()
    return row
