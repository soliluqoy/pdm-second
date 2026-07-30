"""
PREDICT — Rules & Work Order Templates API
CRUD for rules and templates used by the rule engine.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Rule, RuleType, WorkOrderTemplate
from app.schemas.schemas import (
    RuleCreate,
    RuleOut,
    RuleUpdate,
    WorkOrderTemplateCreate,
    WorkOrderTemplateOut,
)

router = APIRouter(prefix="/rules", tags=["rules"])


# =============================================================================
# Work Order Templates
# =============================================================================
@router.get("/templates", response_model=List[WorkOrderTemplateOut])
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrderTemplate).order_by(WorkOrderTemplate.id))
    return result.scalars().all()


@router.post("/templates", response_model=WorkOrderTemplateOut, status_code=201)
async def create_template(data: WorkOrderTemplateCreate, db: AsyncSession = Depends(get_db)):
    template = WorkOrderTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    return template


@router.get("/templates/{template_id}", response_model=WorkOrderTemplateOut)
async def get_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrderTemplate).where(WorkOrderTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrderTemplate).where(WorkOrderTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(template)


# =============================================================================
# Rules
# =============================================================================
@router.get("", response_model=List[RuleOut])
async def list_rules(
    rule_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Rule).order_by(Rule.id)
    if rule_type:
        stmt = stmt.where(Rule.rule_type == rule_type)
    if is_active is not None:
        stmt = stmt.where(Rule.is_active == is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(data: RuleCreate, db: AsyncSession = Depends(get_db)):
    rule = Rule(**data.model_dump())
    db.add(rule)
    await db.flush()
    return rule


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, data: RuleUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    await db.flush()
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)