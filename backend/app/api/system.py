"""
PREDICT — System Config & Maintenance History API
Shadow mode toggle, system settings, and asset history log.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.db.models import MaintenanceHistory, SystemConfig, Vehicle
from app.schemas.schemas import (
    MaintenanceHistoryOut,
    MessageOut,
    SystemConfigOut,
    SystemConfigUpdate,
)
from app.services.telemetry_reset import reset_telemetry_data

router = APIRouter(prefix="/system", tags=["system"])


# =============================================================================
# System Config
# =============================================================================
@router.get("/config", response_model=List[SystemConfigOut])
async def list_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    return result.scalars().all()


@router.get("/config/{key}", response_model=SystemConfigOut)
async def get_config(key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Config key not found")
    return cfg


@router.patch("/config/{key}", response_model=SystemConfigOut)
async def update_config(key: str, data: SystemConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Config key not found")
    cfg.value = data.value
    await db.flush()
    return cfg


@router.get("/shadow-mode", response_model=dict)
async def get_shadow_mode(db: AsyncSession = Depends(get_db)):
    """Get current shadow mode status."""
    # Check DB config first, fall back to env setting
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "shadow_mode")
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        return {"shadow_mode": cfg.value.lower() == "true"}
    return {"shadow_mode": settings.SHADOW_MODE}


@router.post("/shadow-mode", response_model=dict)
async def set_shadow_mode(enabled: bool, db: AsyncSession = Depends(get_db)):
    """Toggle shadow mode on/off."""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "shadow_mode")
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.value = str(enabled).lower()
    else:
        cfg = SystemConfig(
            key="shadow_mode",
            value=str(enabled).lower(),
            description="When true, generated work orders are created in shadow status for review.",
        )
        db.add(cfg)
    await db.flush()
    # Update runtime setting
    settings.SHADOW_MODE = enabled
    return {"shadow_mode": enabled}


@router.post("/reset-telemetry", response_model=dict)
async def reset_telemetry(db: AsyncSession = Depends(get_db)):
    """Wipe all ingested telemetry, alerts, work orders, and Redis live cache.

    Vehicle registration and sensor catalog are preserved. Use after removing
    test/simulated data or to start fresh before connecting real hardware.
    """
    counts = await reset_telemetry_data(db)
    return {"status": "ok", **counts}


# =============================================================================
# Maintenance History
# =============================================================================
@router.get("/history", response_model=List[MaintenanceHistoryOut])
async def list_maintenance_history(
    vehicle_id: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MaintenanceHistory).order_by(MaintenanceHistory.event_date.desc()).limit(limit)
    if vehicle_id is not None:
        stmt = stmt.where(MaintenanceHistory.vehicle_id == vehicle_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/history/vehicle/{vehicle_id}", response_model=List[MaintenanceHistoryOut])
async def get_vehicle_history(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MaintenanceHistory)
        .where(MaintenanceHistory.vehicle_id == vehicle_id)
        .order_by(MaintenanceHistory.event_date.desc())
    )
    return result.scalars().all()