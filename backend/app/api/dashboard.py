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
    RuleTriggerOut,
    SensorReadingOut,
    SensorTelemetryItem,
    VehicleHealthItem,
    VehicleTelemetryOut,
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


@router.get("/telemetry", response_model=List[VehicleTelemetryOut])
async def get_fleet_telemetry(db: AsyncSession = Depends(get_db)):
    """Live telemetry for every active vehicle.

    Joins three sources into one payload so the dashboard can render full
    per-sensor detail without N+1 calls:
      - latest sensor values / GPS / ignition from the Redis state cache
      - sensor operating limits (min/max, warning/critical thresholds) from the DB
      - active threshold rules (the "trigger points") from the DB

    Sorted by health priority: red first, then yellow, grey, green.
    """
    vehicles = (
        (await db.execute(
            select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.id)
        )).scalars().all()
    )
    states = await get_all_vehicle_states()

    # Active sensors with their parent component (per vehicle)
    sensor_rows = (await db.execute(
        select(Sensor, Component)
        .join(Component, Sensor.component_id == Component.id)
        .where(Sensor.is_active == True)
        .order_by(Component.id, Sensor.id)
    )).all()

    # Active threshold rules, keyed by sensor_type
    rule_rows = (await db.execute(
        select(Rule).where(Rule.is_active == True, Rule.rule_type == RuleType.THRESHOLD)
    )).scalars().all()

    sensors_by_vehicle: dict = {}
    for sensor, component in sensor_rows:
        sensors_by_vehicle.setdefault(component.vehicle_id, []).append((sensor, component))

    rules_by_type: dict = {}
    for rule in rule_rows:
        if rule.sensor_type:
            rules_by_type.setdefault(rule.sensor_type, []).append(rule)

    def _infer_direction(rules: list) -> str:
        """Infer which side of the scale is dangerous from rule operators.
        '>' rules → high values are bad; '<' rules → low values are bad."""
        for r in rules:
            if r.operator in (">", ">="):
                return "high"
            if r.operator in ("<", "<="):
                return "low"
        return "high"

    def _compute_status(value, warning, critical, direction) -> str:
        if value is None:
            return "no_data"
        if direction == "low":
            if critical is not None and value <= critical:
                return "critical"
            if warning is not None and value <= warning:
                return "warning"
        else:
            if critical is not None and value >= critical:
                return "critical"
            if warning is not None and value >= warning:
                return "warning"
        return "normal"

    health_order = {
        AssetHealth.RED: 0, AssetHealth.YELLOW: 1,
        AssetHealth.GREY: 2, AssetHealth.GREEN: 3,
    }

    out: List[VehicleTelemetryOut] = []
    for v in vehicles:
        state = states.get(v.id) or {}
        state_sensors = state.get("sensors") or {}

        items: List[SensorTelemetryItem] = []
        for sensor, component in sensors_by_vehicle.get(v.id, []):
            rules = rules_by_type.get(sensor.sensor_type, [])
            direction = _infer_direction(rules)

            live = state_sensors.get(sensor.sensor_type)
            value = live.get("value") if isinstance(live, dict) else None
            unit = (live.get("unit") if isinstance(live, dict) else None) or sensor.unit

            items.append(SensorTelemetryItem(
                sensor_type=sensor.sensor_type,
                name=sensor.name,
                component=component.name,
                unit=unit,
                value=value,
                min_value=sensor.min_value,
                max_value=sensor.max_value,
                warning_threshold=sensor.warning_threshold,
                critical_threshold=sensor.critical_threshold,
                direction=direction,
                status=_compute_status(
                    value, sensor.warning_threshold, sensor.critical_threshold, direction
                ),
                triggers=[
                    RuleTriggerOut(
                        rule_id=r.id,
                        name=r.name,
                        operator=r.operator or ">",
                        threshold_value=r.threshold_value or 0,
                        duration_seconds=r.duration_seconds or 0,
                        severity=r.severity,
                    )
                    for r in rules
                ],
            ))

        out.append(VehicleTelemetryOut(
            id=v.id,
            name=v.name,
            license_plate=v.license_plate,
            imei=v.imei,
            health=v.health,
            last_seen=v.last_seen,
            ignition=state.get("ignition"),
            gps=state.get("gps"),
            state_timestamp=state.get("timestamp"),
            sensors=items,
        ))

    out.sort(key=lambda x: health_order.get(x.health, 99))
    return out


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