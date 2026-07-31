"""
PREDICT — Work Order Management API
List, create, assign, complete, and close work orders.
Includes the technician "Mark as Complete" feedback loop.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import (
    Alert,
    AlertStatus,
    MaintenanceHistory,
    Vehicle,
    WorkOrder,
    WorkOrderStatus,
    WorkOrderPriority,
)
from app.db.redis_client import publish_work_order
from app.schemas.schemas import (
    MessageOut,
    WorkOrderAssign,
    WorkOrderComplete,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderUpdate,
)

router = APIRouter(prefix="/workorders", tags=["work orders"])


async def _wo_to_out(db: AsyncSession, wo: WorkOrder) -> WorkOrderOut:
    """Build WorkOrderOut with vehicle name."""
    vehicle_name = None
    if wo.vehicle_id:
        vr = await db.execute(select(Vehicle.name).where(Vehicle.id == wo.vehicle_id))
        vehicle_name = vr.scalar_one_or_none()
    return WorkOrderOut(
        id=wo.id, vehicle_id=wo.vehicle_id, alert_id=wo.alert_id,
        template_id=wo.template_id, title=wo.title, description=wo.description,
        priority=wo.priority, status=wo.status, instructions=wo.instructions,
        assigned_to=wo.assigned_to, assigned_at=wo.assigned_at,
        completed_at=wo.completed_at, completed_by=wo.completed_by,
        completion_notes=wo.completion_notes, is_shadow=wo.is_shadow,
        vehicle_name=vehicle_name, created_at=wo.created_at, updated_at=wo.updated_at,
    )


@router.get("", response_model=List[WorkOrderOut])
async def list_work_orders(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    vehicle_id: Optional[int] = None,
    is_shadow: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if status:
        stmt = stmt.where(WorkOrder.status == status)
    if priority:
        stmt = stmt.where(WorkOrder.priority == priority)
    if vehicle_id is not None:
        stmt = stmt.where(WorkOrder.vehicle_id == vehicle_id)
    if is_shadow is not None:
        stmt = stmt.where(WorkOrder.is_shadow == is_shadow)
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    wos = result.scalars().all()
    return [await _wo_to_out(db, wo) for wo in wos]


@router.post("", response_model=WorkOrderOut, status_code=201)
async def create_work_order(data: WorkOrderCreate, db: AsyncSession = Depends(get_db)):
    # Verify vehicle exists
    vresult = await db.execute(select(Vehicle).where(Vehicle.id == data.vehicle_id))
    if not vresult.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vehicle not found")
    wo = WorkOrder(**data.model_dump(), status=WorkOrderStatus.OPEN)
    db.add(wo)
    await db.flush()
    out = await _wo_to_out(db, wo)
    await publish_work_order(out.model_dump())
    return out


@router.get("/{wo_id}", response_model=WorkOrderOut)
async def get_work_order(wo_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    return await _wo_to_out(db, wo)


@router.patch("/{wo_id}", response_model=WorkOrderOut)
async def update_work_order(wo_id: int, data: WorkOrderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(wo, k, v)
    await db.flush()
    return await _wo_to_out(db, wo)


@router.post("/{wo_id}/assign", response_model=WorkOrderOut)
async def assign_work_order(wo_id: int, data: WorkOrderAssign, db: AsyncSession = Depends(get_db)):
    """Assign a work order to a technician and set status to in_progress."""
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.status not in (WorkOrderStatus.OPEN, WorkOrderStatus.SHADOW):
        raise HTTPException(status_code=400, detail=f"Cannot assign work order in status '{wo.status}'")
    wo.assigned_to = data.assigned_to
    wo.assigned_at = datetime.now(timezone.utc)
    wo.status = WorkOrderStatus.IN_PROGRESS
    await db.flush()
    out = await _wo_to_out(db, wo)
    await publish_work_order(out.model_dump(mode="json"))
    return out


@router.post("/{wo_id}/complete", response_model=WorkOrderOut)
async def complete_work_order(wo_id: int, data: WorkOrderComplete, db: AsyncSession = Depends(get_db)):
    """Technician marks work order as complete.
    This closes the loop: sets status to completed, records who/when/notes,
    and writes an entry to the vehicle's maintenance history."""
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.status not in (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.OPEN, WorkOrderStatus.SHADOW):
        raise HTTPException(status_code=400, detail=f"Cannot complete work order in status '{wo.status}'")

    wo.status = WorkOrderStatus.COMPLETED
    wo.completed_at = datetime.now(timezone.utc)
    wo.completed_by = data.completed_by
    wo.completion_notes = data.completion_notes

    # Write to maintenance history (the feedback loop)
    history = MaintenanceHistory(
        vehicle_id=wo.vehicle_id,
        work_order_id=wo.id,
        event_type="repair" if not wo.is_shadow else "shadow_resolved",
        title=wo.title,
        description=f"Completed by {data.completed_by}. Notes: {data.completion_notes or 'N/A'}",
        performed_by=data.completed_by,
    )
    db.add(history)

    # If linked alert exists, resolve it
    if wo.alert_id:
        alert_result = await db.execute(select(Alert).where(Alert.id == wo.alert_id))
        alert = alert_result.scalar_one_or_none()
        if alert and alert.status == AlertStatus.ACTIVE:
            alert.status = AlertStatus.RESOLVED

    await db.flush()
    out = await _wo_to_out(db, wo)
    await publish_work_order(out.model_dump(mode="json"))
    return out


@router.post("/{wo_id}/close", response_model=WorkOrderOut)
async def close_work_order(wo_id: int, db: AsyncSession = Depends(get_db)):
    """Close a completed work order (final step)."""
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.status != WorkOrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Only completed work orders can be closed")
    wo.status = WorkOrderStatus.CLOSED
    await db.flush()
    out = await _wo_to_out(db, wo)
    await publish_work_order(out.model_dump(mode="json"))
    return out


@router.post("/{wo_id}/cancel", response_model=WorkOrderOut)
async def cancel_work_order(wo_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a work order (e.g., false positive in shadow mode)."""
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CLOSED):
        raise HTTPException(status_code=400, detail="Cannot cancel completed/closed work orders")
    wo.status = WorkOrderStatus.CANCELLED
    await db.flush()
    return await _wo_to_out(db, wo)


@router.delete("/{wo_id}", status_code=204)
async def delete_work_order(wo_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    await db.delete(wo)