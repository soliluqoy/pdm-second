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
    SensorReading,
    Vehicle,
    WorkOrder,
    WorkOrderStatus,
)
from app.db.redis_client import get_all_vehicle_states
from app.schemas.schemas import (
    DashboardSummary,
    SensorReadingOut,
    VehicleHealthItem,
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