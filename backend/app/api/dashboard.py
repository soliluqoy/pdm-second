"""
PREDICT — Dashboard API
Fleet health summary, vehicle health list, live telemetry, time-series sensor
history (raw + Timescale continuous aggregates), and the merged vehicle
event timeline.
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.db.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AssetHealth,
    Component,
    DrivingEvent,
    DtcEvent,
    MaintenanceHistory,
    Rule,
    RuleType,
    Sensor,
    SensorReading,
    Vehicle,
    VehicleHealthEvent,
    WorkOrder,
    WorkOrderStatus,
)
from app.db.redis_client import get_all_vehicle_states
from app.schemas.schemas import (
    DashboardSummary,
    HistoryPoint,
    LiveSensorItem,
    SensorHistoryOut,
    SensorReadingOut,
    TelemetryCatalogOut,
    TimelineEvent,
    TriggerRuleInfo,
    VehicleHealthItem,
    VehicleLiveItem,
)
from app.services.provisioning import get_telemetry_catalog
from app.services.settings_service import get_shadow_mode

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/telemetry-catalog", response_model=TelemetryCatalogOut)
async def get_telemetry_catalog_endpoint():
    """Parameters the stack decodes and logs, per Teltonika device model.

    Useful before any vehicle is registered — shows what will appear on the
    dashboard once a tracker connects and starts sending AVL records.
    """
    return get_telemetry_catalog()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """High-level fleet health summary — three grouped queries, not ten."""
    vrow = (await db.execute(
        select(
            func.count(Vehicle.id),
            func.count(Vehicle.id).filter(Vehicle.health == AssetHealth.GREEN),
            func.count(Vehicle.id).filter(Vehicle.health == AssetHealth.YELLOW),
            func.count(Vehicle.id).filter(Vehicle.health == AssetHealth.RED),
            func.count(Vehicle.id).filter(Vehicle.health == AssetHealth.GREY),
        ).where(Vehicle.is_active == True)  # noqa: E712
    )).one()

    arow = (await db.execute(
        select(
            func.count(Alert.id).filter(Alert.status == AlertStatus.ACTIVE),
            func.count(Alert.id).filter(
                Alert.status == AlertStatus.ACTIVE,
                Alert.severity == AlertSeverity.CRITICAL,
            ),
        )
    )).one()

    wrow = (await db.execute(
        select(
            func.count(WorkOrder.id).filter(WorkOrder.status == WorkOrderStatus.OPEN),
            func.count(WorkOrder.id).filter(WorkOrder.status == WorkOrderStatus.SHADOW),
            func.count(WorkOrder.id).filter(WorkOrder.status == WorkOrderStatus.IN_PROGRESS),
        )
    )).one()

    return DashboardSummary(
        total_vehicles=vrow[0] or 0,
        green_count=vrow[1] or 0,
        yellow_count=vrow[2] or 0,
        red_count=vrow[3] or 0,
        grey_count=vrow[4] or 0,
        active_alerts=arow[0] or 0,
        critical_alerts=arow[1] or 0,
        open_work_orders=wrow[0] or 0,
        shadow_work_orders=wrow[1] or 0,
        in_progress_work_orders=wrow[2] or 0,
        shadow_mode=await get_shadow_mode(db),
    )


def _grouped_counts(rows) -> dict:
    return {vehicle_id: count for vehicle_id, count in rows}


async def _alert_wo_counts(db: AsyncSession, vehicle_ids: List[int]):
    """Active-alert and open-WO counts per vehicle in two grouped queries."""
    if not vehicle_ids:
        return {}, {}
    alert_counts = _grouped_counts((await db.execute(
        select(Alert.vehicle_id, func.count())
        .where(Alert.vehicle_id.in_(vehicle_ids), Alert.status == AlertStatus.ACTIVE)
        .group_by(Alert.vehicle_id)
    )).all())
    wo_counts = _grouped_counts((await db.execute(
        select(WorkOrder.vehicle_id, func.count())
        .where(
            WorkOrder.vehicle_id.in_(vehicle_ids),
            WorkOrder.status.in_([
                WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.SHADOW
            ]),
        )
        .group_by(WorkOrder.vehicle_id)
    )).all())
    return alert_counts, wo_counts


@router.get("/health", response_model=List[VehicleHealthItem])
async def get_fleet_health(db: AsyncSession = Depends(get_db)):
    """Fleet health overview — all vehicles with health status and counts.
    Sorted: red first, then yellow, then grey, then green."""
    vehicles = (await db.execute(
        select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.id)  # noqa: E712
    )).scalars().all()
    vehicle_ids = [v.id for v in vehicles]

    states = await get_all_vehicle_states()
    alert_counts, wo_counts = await _alert_wo_counts(db, vehicle_ids)

    health_order = {AssetHealth.RED: 0, AssetHealth.YELLOW: 1, AssetHealth.GREY: 2, AssetHealth.GREEN: 3}

    items = [
        VehicleHealthItem(
            id=v.id, name=v.name, imei=v.imei, health=v.health,
            last_seen=v.last_seen, license_plate=v.license_plate,
            active_alert_count=alert_counts.get(v.id, 0),
            open_work_order_count=wo_counts.get(v.id, 0),
            latest_readings=(states.get(v.id) or {}).get("sensors"),
        )
        for v in vehicles
    ]
    items.sort(key=lambda x: health_order.get(x.health, 99))
    return items


def _parse_state_timestamp(ts_raw) -> Optional[datetime]:
    """Parse ISO timestamp from a Redis vehicle state snapshot."""
    if not ts_raw:
        return None
    if isinstance(ts_raw, datetime):
        return ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_fresh(ts_raw) -> bool:
    ts = _parse_state_timestamp(ts_raw)
    if ts is None:
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age <= settings.TELEMETRY_LIVE_MAX_AGE_SECONDS


def _infer_direction(sensor: Sensor, rules: List[Rule]) -> str:
    """Infer whether high or low values are bad for a sensor.

    Primary signal: critical vs warning threshold ordering
    (battery: warn 12.5 > crit 11.5 → low-is-bad).
    Fallback: the operator of any active threshold rule on this sensor type.
    """
    if sensor.warning_threshold is not None and sensor.critical_threshold is not None:
        return "low" if sensor.critical_threshold < sensor.warning_threshold else "high"
    for r in rules:
        if r.operator in ("<", "<="):
            return "low"
        if r.operator in (">", ">="):
            return "high"
    return "high"


def _sensor_status(value: Optional[float], sensor: Sensor, direction: str) -> str:
    """Compute live status of a reading against its thresholds."""
    if value is None:
        return "offline"
    warn = sensor.warning_threshold
    crit = sensor.critical_threshold
    if direction == "low":
        if crit is not None and value <= crit:
            return "critical"
        if warn is not None and value <= warn:
            return "warning"
    else:
        if crit is not None and value >= crit:
            return "critical"
        if warn is not None and value >= warn:
            return "warning"
    return "ok"


@router.get("/fleet/live", response_model=List[VehicleLiveItem])
async def get_fleet_live(db: AsyncSession = Depends(get_db)):
    """Full live telemetry for every active vehicle: all sensors with their
    latest values (Redis cache), operating thresholds, active trigger rules,
    and computed per-sensor status. Freshness is judged PER SENSOR (merged
    Redis state carries a timestamp per reading), so a partial AVL record
    doesn't blank out sensors it didn't carry."""
    vehicles = (await db.execute(
        select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.id)  # noqa: E712
    )).scalars().all()
    if not vehicles:
        return []
    vehicle_ids = [v.id for v in vehicles]

    # Components → Sensors (bulk)
    components = (await db.execute(
        select(Component).where(Component.vehicle_id.in_(vehicle_ids)).order_by(Component.id)
    )).scalars().all()
    comp_vehicle = {c.id: c.vehicle_id for c in components}
    comp_ids = list(comp_vehicle.keys())

    sensors: List[Sensor] = []
    if comp_ids:
        sensors = (await db.execute(
            select(Sensor)
            .where(Sensor.component_id.in_(comp_ids), Sensor.is_active == True)  # noqa: E712
            .order_by(Sensor.id)
        )).scalars().all()
    sensors_by_vehicle: dict = {}
    for s in sensors:
        sensors_by_vehicle.setdefault(comp_vehicle[s.component_id], []).append(s)

    # Active threshold rules, grouped by sensor_type
    rules = (await db.execute(
        select(Rule).where(Rule.is_active == True, Rule.rule_type == RuleType.THRESHOLD)  # noqa: E712
    )).scalars().all()
    rules_by_type: dict = {}
    for r in rules:
        if r.sensor_type:
            rules_by_type.setdefault(r.sensor_type, []).append(r)

    # Live state snapshots from Redis
    states = await get_all_vehicle_states()

    # Alert / work-order counts (grouped, no N+1)
    alert_counts, wo_counts = await _alert_wo_counts(db, vehicle_ids)

    health_order = {AssetHealth.RED: 0, AssetHealth.YELLOW: 1, AssetHealth.GREY: 2, AssetHealth.GREEN: 3}

    items: List[VehicleLiveItem] = []
    for v in vehicles:
        state = states.get(v.id) or {}
        snapshot_live = _is_fresh(state.get("timestamp"))
        live_sensors = state.get("sensors") or {}
        gps = state.get("gps") or {} if snapshot_live else {}

        sensor_items: List[LiveSensorItem] = []
        for s in sensors_by_vehicle.get(v.id, []):
            reading = live_sensors.get(s.sensor_type) or {}
            # Per-sensor freshness; legacy snapshots without per-sensor
            # timestamps fall back to the snapshot timestamp.
            reading_fresh = _is_fresh(reading.get("timestamp") or state.get("timestamp"))
            value = reading.get("value") if reading_fresh else None

            vehicle_rules = [
                r for r in rules_by_type.get(s.sensor_type, [])
                if r.vehicle_id is None or r.vehicle_id == v.id
            ]
            direction = _infer_direction(s, vehicle_rules)
            sensor_items.append(LiveSensorItem(
                sensor_type=s.sensor_type,
                name=s.name,
                unit=s.unit or reading.get("unit"),
                value=value,
                min_value=s.min_value,
                max_value=s.max_value,
                warning_threshold=s.warning_threshold,
                critical_threshold=s.critical_threshold,
                direction=direction,
                status=_sensor_status(value, s, direction),
                rules=[TriggerRuleInfo(
                    id=r.id, name=r.name, operator=r.operator,
                    threshold_value=r.threshold_value,
                    duration_seconds=r.duration_seconds or 0,
                    severity=r.severity,
                ) for r in vehicle_rules],
            ))

        items.append(VehicleLiveItem(
            id=v.id, name=v.name, imei=v.imei, license_plate=v.license_plate,
            health=v.health, last_seen=v.last_seen,
            ignition=state.get("ignition") if snapshot_live else None,
            speed=gps.get("speed") if snapshot_live else None,
            telemetry_timestamp=state.get("timestamp") if snapshot_live else None,
            active_alert_count=alert_counts.get(v.id, 0),
            open_work_order_count=wo_counts.get(v.id, 0),
            sensors=sensor_items,
        ))

    items.sort(key=lambda x: health_order.get(x.health, 99))
    return items


@router.get("/vehicles/{vehicle_id}/readings", response_model=List[SensorReadingOut])
async def get_vehicle_readings(
    vehicle_id: int,
    sensor_type: Optional[str] = None,
    hours: int = Query(1, ge=1, le=168),
    limit: int = Query(500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Raw time-series sensor readings for a vehicle (default: last 1 hour).
    For long ranges prefer /vehicles/{id}/history which serves bucketed data."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(SensorReading)
        .where(SensorReading.vehicle_id == vehicle_id, SensorReading.timestamp >= since)
        .order_by(SensorReading.timestamp.desc())
        .limit(limit)
    )
    if sensor_type:
        stmt = stmt.where(SensorReading.sensor_type == sensor_type)
    result = await db.execute(stmt)
    readings = result.scalars().all()
    # Return in chronological order for charts
    return list(reversed(readings))


def _pick_resolution(hours: float) -> str:
    if hours <= 6:
        return "raw"
    if hours <= 168:          # up to 7 days → 1-minute buckets
        return "1m"
    return "1h"


def _history_window(
    hours: int,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
) -> Tuple[datetime, datetime, float]:
    """Resolve [since, until] and span-in-hours. Prefer from/to when both set."""
    until = to_ts or datetime.now(timezone.utc)
    if from_ts is not None and to_ts is not None:
        if from_ts.tzinfo is None:
            from_ts = from_ts.replace(tzinfo=timezone.utc)
        if to_ts.tzinfo is None:
            to_ts = to_ts.replace(tzinfo=timezone.utc)
        if from_ts >= to_ts:
            raise HTTPException(status_code=400, detail="'from' must be before 'to'")
        span_hours = (to_ts - from_ts).total_seconds() / 3600.0
        return from_ts, to_ts, span_hours
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    span_hours = float(hours)
    return since, until, span_hours


async def _fetch_sensor_history(
    db: AsyncSession,
    vehicle_id: int,
    sensor_type: str,
    since: datetime,
    until: datetime,
    span_hours: float,
    resolution: str,
    row_limit: int = 5000,
) -> SensorHistoryOut:
    res = _pick_resolution(span_hours) if resolution == "auto" else resolution

    if res == "raw":
        result = await db.execute(
            select(SensorReading.timestamp, SensorReading.value)
            .where(
                SensorReading.vehicle_id == vehicle_id,
                SensorReading.sensor_type == sensor_type,
                SensorReading.timestamp >= since,
                SensorReading.timestamp <= until,
            )
            .order_by(SensorReading.timestamp.asc())
            .limit(row_limit)
        )
        points = [
            HistoryPoint(t=t, value=val, min_value=val, max_value=val, count=1)
            for t, val in result.all()
        ]
        return SensorHistoryOut(sensor_type=sensor_type, resolution="raw", points=points)

    view = "sensor_readings_1m" if res == "1m" else "sensor_readings_1h"
    try:
        result = await db.execute(
            text(
                f"SELECT bucket, avg_value, min_value, max_value, sample_count "
                f"FROM {view} "
                f"WHERE vehicle_id = :vid AND sensor_type = :stype "
                f"AND bucket >= :since AND bucket <= :until "
                f"ORDER BY bucket ASC LIMIT :lim"
            ),
            {
                "vid": vehicle_id,
                "stype": sensor_type,
                "since": since,
                "until": until,
                "lim": row_limit,
            },
        )
        rows = result.all()
    except Exception:
        return await _fetch_sensor_history(
            db, vehicle_id, sensor_type, since, until,
            min(span_hours, 168.0), "raw", row_limit,
        )

    points = [
        HistoryPoint(t=bucket, value=avg_v, min_value=min_v, max_value=max_v, count=cnt)
        for bucket, avg_v, min_v, max_v, cnt in rows
    ]
    return SensorHistoryOut(sensor_type=sensor_type, resolution=res, points=points)


@router.get("/vehicles/{vehicle_id}/history", response_model=SensorHistoryOut)
async def get_vehicle_sensor_history(
    vehicle_id: int,
    sensor_type: str,
    hours: int = Query(24, ge=1, le=2160),   # up to 90 days
    resolution: str = Query("auto", pattern="^(auto|raw|1m|1h)$"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
):
    """Bucketed sensor history served from TimescaleDB continuous aggregates.

    Pass both `from` and `to` for a custom window; otherwise use `hours`.
    resolution=auto picks raw ≤ 6h, 1-minute buckets ≤ 7 days, hourly beyond.
    """
    since, until, span_hours = _history_window(hours, from_ts, to_ts)
    return await _fetch_sensor_history(
        db, vehicle_id, sensor_type, since, until, span_hours, resolution
    )


@router.get("/vehicles/{vehicle_id}/history/csv")
async def get_vehicle_sensor_history_csv(
    vehicle_id: int,
    sensor_type: str,
    hours: int = Query(24, ge=1, le=2160),
    resolution: str = Query("auto", pattern="^(auto|raw|1m|1h)$"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
):
    """CSV export of bucketed (or raw) sensor history. Capped at 50k rows."""
    since, until, span_hours = _history_window(hours, from_ts, to_ts)
    history = await _fetch_sensor_history(
        db, vehicle_id, sensor_type, since, until, span_hours, resolution, row_limit=50_000
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "sensor_type", "value", "min_value", "max_value", "count", "resolution"])
    for p in history.points:
        writer.writerow([
            p.t.isoformat(),
            history.sensor_type,
            p.value,
            p.min_value,
            p.max_value,
            p.count,
            history.resolution,
        ])
    buf.seek(0)
    filename = f"vehicle_{vehicle_id}_{sensor_type}_{history.resolution}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/vehicles/{vehicle_id}/timeline", response_model=List[TimelineEvent])
async def get_vehicle_timeline(
    vehicle_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Merged event stream: alerts, work orders, maintenance, health, DTCs, driving."""
    vehicle = (await db.execute(
        select(Vehicle.id).where(Vehicle.id == vehicle_id)
    )).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Fetch a generous window per source, then merge/sort/paginate in Python.
    fetch_n = skip + limit
    alerts = (await db.execute(
        select(Alert).where(Alert.vehicle_id == vehicle_id)
        .order_by(Alert.created_at.desc()).limit(fetch_n)
    )).scalars().all()
    wos = (await db.execute(
        select(WorkOrder).where(WorkOrder.vehicle_id == vehicle_id)
        .order_by(WorkOrder.created_at.desc()).limit(fetch_n)
    )).scalars().all()
    events = (await db.execute(
        select(MaintenanceHistory).where(MaintenanceHistory.vehicle_id == vehicle_id)
        .order_by(MaintenanceHistory.event_date.desc()).limit(fetch_n)
    )).scalars().all()
    health_events = (await db.execute(
        select(VehicleHealthEvent).where(VehicleHealthEvent.vehicle_id == vehicle_id)
        .order_by(VehicleHealthEvent.timestamp.desc()).limit(fetch_n)
    )).scalars().all()
    dtc_events = (await db.execute(
        select(DtcEvent).where(DtcEvent.vehicle_id == vehicle_id)
        .order_by(DtcEvent.timestamp.desc()).limit(fetch_n)
    )).scalars().all()
    driving_events = (await db.execute(
        select(DrivingEvent).where(DrivingEvent.vehicle_id == vehicle_id)
        .order_by(DrivingEvent.ts.desc()).limit(fetch_n)
    )).scalars().all()

    timeline: List[TimelineEvent] = []
    for a in alerts:
        timeline.append(TimelineEvent(
            kind="alert", id=a.id, timestamp=a.created_at, title=a.title,
            description=a.message, severity=a.severity.value, status=a.status.value,
            work_order_id=a.work_order_id,
        ))
    for w in wos:
        timeline.append(TimelineEvent(
            kind="work_order", id=w.id, timestamp=w.created_at, title=w.title,
            description=w.description, status=w.status.value, alert_id=w.alert_id,
        ))
    for e in events:
        timeline.append(TimelineEvent(
            kind="maintenance", id=e.id, timestamp=e.event_date, title=e.title,
            description=e.description, status=e.event_type,
            work_order_id=e.work_order_id,
        ))
    for h in health_events:
        timeline.append(TimelineEvent(
            kind="health", id=h.id, timestamp=h.timestamp,
            title=f"Health {h.from_health.value} → {h.to_health.value}",
            description=h.reason,
            status=h.to_health.value,
        ))
    for d in dtc_events:
        timeline.append(TimelineEvent(
            kind="dtc", id=d.id, timestamp=d.timestamp,
            title=f"DTC {d.dtc_code}",
            description=d.description,
            severity=d.severity,
            alert_id=d.alert_id,
        ))
    for de in driving_events:
        et = de.event_type.value if hasattr(de.event_type, "value") else str(de.event_type)
        src = de.source.value if hasattr(de.source, "value") else str(de.source)
        timeline.append(TimelineEvent(
            kind="driving", id=de.id, timestamp=de.ts,
            title=et.replace("_", " ").title(),
            description=f"{src}" + (f" · value={de.value}" if de.value is not None else ""),
            status=src,
        ))

    timeline.sort(key=lambda x: x.timestamp, reverse=True)
    return timeline[skip:skip + limit]


@router.get("/vehicles/{vehicle_id}/latest", response_model=dict)
async def get_vehicle_latest(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    """Latest cached state for a vehicle (from Redis)."""
    from app.db.redis_client import get_vehicle_state
    state = await get_vehicle_state(vehicle_id)
    if state and not _is_fresh(state.get("timestamp")):
        state = None
    if not state:
        # Fallback: query latest reading per sensor type
        since = datetime.now(timezone.utc) - timedelta(minutes=30)
        result = await db.execute(
            select(SensorReading)
            .where(SensorReading.vehicle_id == vehicle_id, SensorReading.timestamp >= since)
            .order_by(SensorReading.timestamp.desc())
            .limit(50)
        )
        readings = result.scalars().all()
        state = {}
        for r in readings:
            if r.sensor_type not in state:
                state[r.sensor_type] = {
                    "value": r.value, "unit": r.unit, "timestamp": r.timestamp.isoformat(),
                }
    return state
