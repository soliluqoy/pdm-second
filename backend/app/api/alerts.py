"""
PREDICT — Alerts API
List, acknowledge, resolve, and suppress alerts.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.redis_client import publish_alert
from app.db.models import Alert, AlertStatus, Vehicle
from app.schemas.schemas import AlertOut, MessageOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


async def _alert_to_out(db: AsyncSession, a: Alert) -> AlertOut:
    vehicle_name = None
    if a.vehicle_id:
        vr = await db.execute(select(Vehicle.name).where(Vehicle.id == a.vehicle_id))
        vehicle_name = vr.scalar_one_or_none()
    return AlertOut(
        id=a.id, vehicle_id=a.vehicle_id, rule_id=a.rule_id, sensor_id=a.sensor_id,
        severity=a.severity, status=a.status, title=a.title, message=a.message,
        trigger_value=a.trigger_value, trigger_timestamp=a.trigger_timestamp,
        work_order_id=a.work_order_id, vehicle_name=vehicle_name,
        created_at=a.created_at,
    )


@router.get("", response_model=List[AlertOut])
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    vehicle_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert).order_by(Alert.created_at.desc())
    if status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if vehicle_id is not None:
        stmt = stmt.where(Alert.vehicle_id == vehicle_id)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()
    return [await _alert_to_out(db, a) for a in alerts]


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return await _alert_to_out(db, alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.status != AlertStatus.ACTIVE:
        raise HTTPException(status_code=400, detail=f"Cannot acknowledge alert in status '{alert.status}'")
    alert.status = AlertStatus.ACKNOWLEDGED
    await db.flush()
    out = await _alert_to_out(db, alert)
    await publish_alert(out.model_dump(mode="json"))
    return out


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.RESOLVED
    await db.flush()
    out = await _alert_to_out(db, alert)
    await publish_alert(out.model_dump(mode="json"))
    return out


@router.post("/{alert_id}/suppress", response_model=AlertOut)
async def suppress_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.SUPPRESSED
    await db.flush()
    return await _alert_to_out(db, alert)