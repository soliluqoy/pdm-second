"""
PREDICT — Dashboard API
Fleet health summary, vehicle health list, and time-series sensor data.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.db.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AssetHealth,
    Component,
    Rule,
    RuleType,
    Sensor,
    SensorReading,
    Vehicle,
    WorkOrder,
    WorkOrderStatus,
)
from app.db.redis_client import get_all_vehicle_states
from app.schemas.schemas import (
    DashboardSummary,
    LiveSensorItem,
    SensorReadingOut,
    TriggerRuleInfo,
    VehicleHealthItem,
    VehicleLiveItem,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """High-level fleet health summary for the dashboard header."""
    # Vehicle counts by health
    total = await db.execute(select(func.count(Vehicle.id)).where(Vehicle.is_active == True))
    total_vehicles = total.scalar() or 0

    green = await db.execute(
        select(func.count(Vehicle.id)).where(
            Vehicle.is_active == True, Vehicle.health == AssetHealth.GREEN
        )
    )
    yellow = await db.execute(
        select(func.count(Vehicle.id)).where(
            Vehicle.is_active == True, Vehicle.health == AssetHealth.YELLOW
        )
    )
    red = await db.execute(
        select(func.count(Vehicle.id)).where(
            Vehicle.is_active == True, Vehicle.health == AssetHealth.RED
        )
    )
    grey = await db.execute(
        select(func.count(Vehicle.id)).where(
            Vehicle.is_active == True, Vehicle.health == AssetHealth.GREY
        )
    )

    # Alert counts
    active_alerts = await db.execute(
        select(func.count(Alert.id)).where(Alert.status == AlertStatus.ACTIVE)
    )
    critical_alerts = await db.execute(
        select(func.count(Alert.id)).where(
            Alert.status == AlertStatus.ACTIVE, Alert.severity == AlertSeverity.CRITICAL
        )
    )

    # Work order counts
    open_wos = await db.execute(
        select(func.count(WorkOrder.id)).where(WorkOrder.status == WorkOrderStatus.OPEN)
    )
    shadow_wos = await db.execute(
        select(func.count(WorkOrder.id)).where(WorkOrder.status == WorkOrderStatus.SHADOW)
    )
    in_progress_wos = await db.execute(
        select(func.count(WorkOrder.id)).where(WorkOrder.status == WorkOrderStatus.IN_PROGRESS)
    )

    return DashboardSummary(
        total_vehicles=total_vehicles,
        green_count=green.scalar() or 0,
        yellow_count=yellow.scalar() or 0,
        red_count=red.scalar() or 0,
        grey_count=grey.scalar() or 0,
        active_alerts=active_alerts.scalar() or 0,
        critical_alerts=critical_alerts.scalar() or 0,
        open_work_orders=open_wos.scalar() or 0,
        shadow_work_orders=shadow_wos.scalar() or 0,
        in_progress_work_orders=in_progress_wos.scalar() or 0,
        shadow_mode=settings.SHADOW_MODE,
    )


@router.get("/health", response_model=List[VehicleHealthItem])
async def get_fleet_health(db: AsyncSession = Depends(get_db)):
    """Fleet health overview — all vehicles with health status and counts.
    Sorted: red first, then yellow, then grey, then green."""
    vehicles = await db.execute(
        select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.id)
    )
    vehicles = vehicles.scalars().all()

    # Get all latest states from Redis
    states = await get_all_vehicle_states()

    # Health sort order
    health_order = {AssetHealth.RED: 0, AssetHealth.YELLOW: 1, AssetHealth.GREY: 2, AssetHealth.GREEN: 3}

    items = []
    for v in vehicles:
        # Active alert count
        ac = await db.execute(
            select(func.count(Alert.id)).where(
                Alert.vehicle_id == v.id, Alert.status == AlertStatus.ACTIVE
            )
        )
        active_alert_count = ac.scalar() or 0

        # Open work order count
        wc = await db.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.vehicle_id == v.id,
                WorkOrder.status.in_([
                    WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.SHADOW
                ]),
            )
        )
        open_wo_count = wc.scalar() or 0

        items.append(VehicleHealthItem(
            id=v.id, name=v.name, imei=v.imei, health=v.health,
            last_seen=v.last_seen, license_plate=v.license_plate,
            active_alert_count=active_alert_count,
            open_work_order_count=open_wo_count,
            latest_readings=states.get(v.id),
        ))

    # Sort by health priority
    items.sort(key=lambda x: health_order.get(x.health, 99))
    return items


# ── Live fleet telemetry helpers ──────────────────────────────────────────────
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
    and computed per-sensor status. One request — no N+1 on the frontend."""
    vehicles = (await db.execute(
        select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.id)
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
            .where(Sensor.component_id.in_(comp_ids), Sensor.is_active == True)
            .order_by(Sensor.id)
        )).scalars().all()
    sensors_by_vehicle: dict = {}
    for s in sensors:
        sensors_by_vehicle.setdefault(comp_vehicle[s.component_id], []).append(s)

    # Active threshold rules, grouped by sensor_type
    rules = (await db.execute(
        select(Rule).where(Rule.is_active == True, Rule.rule_type == RuleType.THRESHOLD)
    )).scalars().all()
    rules_by_type: dict = {}
    for r in rules:
        if r.sensor_type:
            rules_by_type.setdefault(r.sensor_type, []).append(r)

    # Live state snapshots from Redis
    states = await get_all_vehicle_states()

    # Alert / work-order counts (grouped, no N+1)
    alert_counts = dict((await db.execute(
        select(Alert.vehicle_id, func.count())
        .where(Alert.vehicle_id.in_(vehicle_ids), Alert.status == AlertStatus.ACTIVE)
        .group_by(Alert.vehicle_id)
    )).all())
    wo_counts = dict((await db.execute(
        select(WorkOrder.vehicle_id, func.count())
        .where(
            WorkOrder.vehicle_id.in_(vehicle_ids),
            WorkOrder.status.in_([
                WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.SHADOW
            ]),
        )
        .group_by(WorkOrder.vehicle_id)
    )).all())

    health_order = {AssetHealth.RED: 0, AssetHealth.YELLOW: 1, AssetHealth.GREY: 2, AssetHealth.GREEN: 3}

    items: List[VehicleLiveItem] = []
    for v in vehicles:
        state = states.get(v.id) or {}
        live = state.get("sensors") or {}
        gps = state.get("gps") or {}

        sensor_items: List[LiveSensorItem] = []
        for s in sensors_by_vehicle.get(v.id, []):
            reading = live.get(s.sensor_type) or {}
            value = reading.get("value")
            sensor_rules = rules_by_type.get(s.sensor_type, [])
            direction = _infer_direction(s, sensor_rules)
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
                ) for r in sensor_rules],
            ))

        items.append(VehicleLiveItem(
            id=v.id, name=v.name, imei=v.imei, license_plate=v.license_plate,
            health=v.health, last_seen=v.last_seen,
            ignition=state.get("ignition"),
            speed=gps.get("speed"),
            telemetry_timestamp=state.get("timestamp"),
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
    """Time-series sensor readings for a vehicle (default: last 1 hour)."""
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


@router.get("/vehicles/{vehicle_id}/latest", response_model=dict)
async def get_vehicle_latest(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    """Latest cached state for a vehicle (from Redis)."""
    from app.db.redis_client import get_vehicle_state
    state = await get_vehicle_state(vehicle_id)
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