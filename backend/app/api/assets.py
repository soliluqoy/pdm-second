"""
PREDICT — Asset Registry API
Fleets, Vehicles, Components, Sensors CRUD.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import (
    Alert,
    AlertStatus,
    Component,
    Fleet,
    Sensor,
    Vehicle,
    WorkOrder,
    WorkOrderStatus,
)
from app.schemas.schemas import (
    ComponentCreate,
    ComponentOut,
    ComponentUpdate,
    FleetCreate,
    FleetOut,
    FleetUpdate,
    SensorCreate,
    SensorOut,
    SensorUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)
from app.services.provisioning import provision_vehicle

router = APIRouter(prefix="/assets", tags=["assets"])



# =============================================================================
# Fleets
# =============================================================================
@router.get("/fleets", response_model=List[FleetOut])
async def list_fleets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Fleet).order_by(Fleet.id)
    )
    fleets = result.scalars().all()
    out = []
    for f in fleets:
        count_result = await db.execute(
            select(func.count(Vehicle.id)).where(Vehicle.fleet_id == f.id)
        )
        vc = count_result.scalar() or 0
        out.append(FleetOut(id=f.id, name=f.name, description=f.description,
                            is_active=f.is_active, vehicle_count=vc,
                            created_at=f.created_at, updated_at=f.updated_at))
    return out


@router.post("/fleets", response_model=FleetOut, status_code=201)
async def create_fleet(data: FleetCreate, db: AsyncSession = Depends(get_db)):
    fleet = Fleet(**data.model_dump())
    db.add(fleet)
    await db.flush()
    return FleetOut(id=fleet.id, name=fleet.name, description=fleet.description,
                    is_active=fleet.is_active, vehicle_count=0,
                    created_at=fleet.created_at, updated_at=fleet.updated_at)


@router.get("/fleets/{fleet_id}", response_model=FleetOut)
async def get_fleet(fleet_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fleet).where(Fleet.id == fleet_id))
    fleet = result.scalar_one_or_none()
    if not fleet:
        raise HTTPException(status_code=404, detail="Fleet not found")
    count_result = await db.execute(
        select(func.count(Vehicle.id)).where(Vehicle.fleet_id == fleet.id)
    )
    vc = count_result.scalar() or 0
    return FleetOut(id=fleet.id, name=fleet.name, description=fleet.description,
                    is_active=fleet.is_active, vehicle_count=vc,
                    created_at=fleet.created_at, updated_at=fleet.updated_at)


@router.patch("/fleets/{fleet_id}", response_model=FleetOut)
async def update_fleet(fleet_id: int, data: FleetUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fleet).where(Fleet.id == fleet_id))
    fleet = result.scalar_one_or_none()
    if not fleet:
        raise HTTPException(status_code=404, detail="Fleet not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(fleet, k, v)
    await db.flush()
    return FleetOut(id=fleet.id, name=fleet.name, description=fleet.description,
                    is_active=fleet.is_active, created_at=fleet.created_at,
                    updated_at=fleet.updated_at)


@router.delete("/fleets/{fleet_id}", status_code=204)
async def delete_fleet(fleet_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fleet).where(Fleet.id == fleet_id))
    fleet = result.scalar_one_or_none()
    if not fleet:
        raise HTTPException(status_code=404, detail="Fleet not found")
    await db.delete(fleet)


# =============================================================================
# Vehicles
# =============================================================================
async def _vehicle_to_out(db: AsyncSession, v: Vehicle) -> VehicleOut:
    """Build VehicleOut with computed counts."""
    fleet_name = None
    if v.fleet_id:
        fr = await db.execute(select(Fleet.name).where(Fleet.id == v.fleet_id))
        fleet_name = fr.scalar_one_or_none()

    cc = await db.execute(
        select(func.count(Component.id)).where(Component.vehicle_id == v.id)
    )
    component_count = cc.scalar() or 0

    ac = await db.execute(
        select(func.count(Alert.id)).where(
            Alert.vehicle_id == v.id, Alert.status == AlertStatus.ACTIVE
        )
    )
    active_alert_count = ac.scalar() or 0

    wc = await db.execute(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.vehicle_id == v.id,
            WorkOrder.status.in_([WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.SHADOW]),
        )
    )
    open_wo_count = wc.scalar() or 0

    return VehicleOut(
        id=v.id, name=v.name, license_plate=v.license_plate, make=v.make,
        model=v.model, year=v.year, vin=v.vin, imei=v.imei, device_type=v.device_type,
        sim_phone=v.sim_phone, fleet_id=v.fleet_id,
        is_active=v.is_active, health=v.health, last_seen=v.last_seen,
        fleet_name=fleet_name, component_count=component_count,
        active_alert_count=active_alert_count, open_work_order_count=open_wo_count,
        created_at=v.created_at, updated_at=v.updated_at,
    )


@router.get("/vehicles", response_model=List[VehicleOut])
async def list_vehicles(
    fleet_id: Optional[int] = None,
    health: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Vehicle).order_by(Vehicle.id)
    if fleet_id is not None:
        stmt = stmt.where(Vehicle.fleet_id == fleet_id)
    if health is not None:
        stmt = stmt.where(Vehicle.health == health)
    if is_active is not None:
        stmt = stmt.where(Vehicle.is_active == is_active)
    result = await db.execute(stmt)
    vehicles = result.scalars().all()
    return [await _vehicle_to_out(db, v) for v in vehicles]


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
async def create_vehicle(data: VehicleCreate, db: AsyncSession = Depends(get_db)):
    # Check IMEI uniqueness
    existing = await db.execute(select(Vehicle).where(Vehicle.imei == data.imei))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Vehicle with IMEI {data.imei} already exists")
    vehicle = Vehicle(**data.model_dump())
    db.add(vehicle)
    await db.flush()
    return await _vehicle_to_out(db, vehicle)


@router.post("/vehicles/register", response_model=VehicleOut, status_code=201)
async def register_vehicle(
    data: VehicleCreate,
    provision: bool = Query(True, description="Attach catalog components + sensors"),
    db: AsyncSession = Depends(get_db),
):
    """Register a REAL Teltonika-equipped vehicle (FMC001 OBD-II or FMC150 CAN).

    Creates the vehicle (keyed by device IMEI) and, by default, provisions the
    component/sensor catalog matching its device_type from
    app/services/provisioning.py so the dashboard and rule engine have known
    sensor types the moment the first record arrives.
    """
    existing = await db.execute(select(Vehicle).where(Vehicle.imei == data.imei))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Vehicle with IMEI {data.imei} already exists")
    vehicle = Vehicle(**data.model_dump())
    db.add(vehicle)
    await db.flush()
    if provision:
        await provision_vehicle(db, vehicle)
    await db.flush()
    return await _vehicle_to_out(db, vehicle)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):

    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return await _vehicle_to_out(db, vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(vehicle_id: int, data: VehicleUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(vehicle, k, v)
    await db.flush()
    return await _vehicle_to_out(db, vehicle)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
async def delete_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    await db.delete(vehicle)


# =============================================================================
# Components
# =============================================================================
@router.get("/vehicles/{vehicle_id}/components", response_model=List[ComponentOut])
async def list_components(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Component).where(Component.vehicle_id == vehicle_id).order_by(Component.id)
    )
    components = result.scalars().all()
    out = []
    for c in components:
        sc = await db.execute(
            select(func.count(Sensor.id)).where(Sensor.component_id == c.id)
        )
        sensor_count = sc.scalar() or 0
        out.append(ComponentOut(id=c.id, vehicle_id=c.vehicle_id, name=c.name,
                                component_type=c.component_type, description=c.description,
                                sensor_count=sensor_count, created_at=c.created_at,
                                updated_at=c.updated_at))
    return out


@router.post("/components", response_model=ComponentOut, status_code=201)
async def create_component(data: ComponentCreate, db: AsyncSession = Depends(get_db)):
    # Verify vehicle exists
    vresult = await db.execute(select(Vehicle).where(Vehicle.id == data.vehicle_id))
    if not vresult.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vehicle not found")
    component = Component(**data.model_dump())
    db.add(component)
    await db.flush()
    return ComponentOut(id=component.id, vehicle_id=component.vehicle_id,
                        name=component.name, component_type=component.component_type,
                        description=component.description, sensor_count=0,
                        created_at=component.created_at, updated_at=component.updated_at)


@router.patch("/components/{component_id}", response_model=ComponentOut)
async def update_component(component_id: int, data: ComponentUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Component).where(Component.id == component_id))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(component, k, v)
    await db.flush()
    sc = await db.execute(
        select(func.count(Sensor.id)).where(Sensor.component_id == component.id)
    )
    sensor_count = sc.scalar() or 0
    return ComponentOut(id=component.id, vehicle_id=component.vehicle_id,
                        name=component.name, component_type=component.component_type,
                        description=component.description, sensor_count=sensor_count,
                        created_at=component.created_at, updated_at=component.updated_at)


@router.delete("/components/{component_id}", status_code=204)
async def delete_component(component_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Component).where(Component.id == component_id))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    await db.delete(component)


# =============================================================================
# Sensors
# =============================================================================
@router.get("/components/{component_id}/sensors", response_model=List[SensorOut])
async def list_sensors(component_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Sensor).where(Sensor.component_id == component_id).order_by(Sensor.id)
    )
    return result.scalars().all()


@router.post("/sensors", response_model=SensorOut, status_code=201)
async def create_sensor(data: SensorCreate, db: AsyncSession = Depends(get_db)):
    cresult = await db.execute(select(Component).where(Component.id == data.component_id))
    if not cresult.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Component not found")
    sensor = Sensor(**data.model_dump())
    db.add(sensor)
    await db.flush()
    return sensor


@router.patch("/sensors/{sensor_id}", response_model=SensorOut)
async def update_sensor(sensor_id: int, data: SensorUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sensor).where(Sensor.id == sensor_id))
    sensor = result.scalar_one_or_none()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(sensor, k, v)
    await db.flush()
    return sensor


@router.delete("/sensors/{sensor_id}", status_code=204)
async def delete_sensor(sensor_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sensor).where(Sensor.id == sensor_id))
    sensor = result.scalar_one_or_none()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    await db.delete(sensor)