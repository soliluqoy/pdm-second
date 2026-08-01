"""
PREDICT — Driving behavior API (Phase 5)
Fleet scorecards, per-vehicle score trends, trips + events.
"""
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import DriverScore, DrivingEvent, Trip, Vehicle
from app.schemas.schemas import (
    BehaviorScorePoint,
    BehaviorScorecard,
    BehaviorVehicleOut,
    DrivingEventOut,
    TripDetailOut,
    TripOut,
)

router = APIRouter(prefix="/behavior", tags=["behavior"])


@router.get("/summary", response_model=List[BehaviorScorecard])
async def fleet_behavior_summary(
    days: int = Query(1, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Latest (or best available) scorecard per active vehicle, worst first."""
    day = date.today() - timedelta(days=days - 1)
    vehicles = (await db.execute(
        select(Vehicle).where(Vehicle.is_active == True).order_by(Vehicle.name)  # noqa: E712
    )).scalars().all()

    cards: List[BehaviorScorecard] = []
    for v in vehicles:
        score_row = (await db.execute(
            select(DriverScore)
            .where(DriverScore.vehicle_id == v.id, DriverScore.date >= day)
            .order_by(DriverScore.date.desc())
            .limit(1)
        )).scalar_one_or_none()
        cards.append(BehaviorScorecard(
            vehicle_id=v.id,
            vehicle_name=v.name,
            license_plate=v.license_plate,
            score=score_row.score if score_row else None,
            date=score_row.date if score_row else None,
            trips=score_row.trips if score_row else 0,
            distance_km=score_row.distance_km if score_row else 0.0,
            idle_ratio=score_row.idle_ratio if score_row else 0.0,
            events_per_100km=score_row.events_per_100km or {} if score_row else {},
        ))

    cards.sort(key=lambda c: (c.score is None, c.score if c.score is not None else 999))
    return cards


@router.get("/vehicles/{vehicle_id}", response_model=BehaviorVehicleOut)
async def vehicle_behavior(
    vehicle_id: int,
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    vehicle = (await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id)
    )).scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    start_day = date.today() - timedelta(days=days - 1)
    scores = (await db.execute(
        select(DriverScore)
        .where(DriverScore.vehicle_id == vehicle_id, DriverScore.date >= start_day)
        .order_by(DriverScore.date.asc())
    )).scalars().all()

    window_start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=timezone.utc)
    ev_rows = (await db.execute(
        select(DrivingEvent.event_type, func.count())
        .where(DrivingEvent.vehicle_id == vehicle_id, DrivingEvent.ts >= window_start)
        .group_by(DrivingEvent.event_type)
    )).all()
    breakdown = {
        (et.value if hasattr(et, "value") else str(et)): int(c) for et, c in ev_rows
    }

    return BehaviorVehicleOut(
        vehicle_id=vehicle.id,
        vehicle_name=vehicle.name,
        scores=[
            BehaviorScorePoint(
                date=s.date,
                score=s.score,
                trips=s.trips,
                distance_km=s.distance_km,
                idle_ratio=s.idle_ratio,
                events_per_100km=s.events_per_100km or {},
            )
            for s in scores
        ],
        event_breakdown=breakdown,
    )


@router.get("/vehicles/{vehicle_id}/trips", response_model=List[TripOut])
async def list_trips(
    vehicle_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    vehicle = (await db.execute(
        select(Vehicle.id).where(Vehicle.id == vehicle_id)
    )).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    rows = (await db.execute(
        select(Trip)
        .where(Trip.vehicle_id == vehicle_id)
        .order_by(Trip.start_ts.desc())
        .offset(skip).limit(limit)
    )).scalars().all()
    return rows


@router.get("/vehicles/{vehicle_id}/trips/{trip_id}", response_model=TripDetailOut)
async def trip_detail(
    vehicle_id: int,
    trip_id: int,
    db: AsyncSession = Depends(get_db),
):
    trip = (await db.execute(
        select(Trip).where(Trip.id == trip_id, Trip.vehicle_id == vehicle_id)
    )).scalar_one_or_none()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    events = (await db.execute(
        select(DrivingEvent)
        .where(DrivingEvent.trip_id == trip_id)
        .order_by(DrivingEvent.ts.asc())
    )).scalars().all()

    out = TripDetailOut.model_validate(trip)
    out.events = [DrivingEventOut.model_validate(e) for e in events]
    return out
