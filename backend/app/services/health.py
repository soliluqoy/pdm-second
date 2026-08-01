"""
PREDICT — Vehicle health computation
Shared helper used by the rule engine, alert/work-order endpoints, and the
offline watchdog.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    AssetHealth,
    Vehicle,
    VehicleHealthEvent,
)
from app.db.redis_client import publish_health_update


def _is_stale(last_seen: Optional[datetime]) -> bool:
    if last_seen is None:
        return True
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_seen
    return age > timedelta(seconds=settings.OFFLINE_AFTER_SECONDS)


async def log_health_transition(
    session: AsyncSession,
    vehicle_id: int,
    from_health: AssetHealth,
    to_health: AssetHealth,
    reason: Optional[str] = None,
) -> None:
    """Persist a health transition for the vehicle timeline."""
    if from_health == to_health:
        return
    session.add(
        VehicleHealthEvent(
            vehicle_id=vehicle_id,
            from_health=from_health,
            to_health=to_health,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def recompute_health(
    session: AsyncSession,
    vehicle_id: int,
    reason: Optional[str] = None,
) -> Optional[AssetHealth]:
    """Recompute vehicle health from open alerts + telemetry freshness.
    Returns the new health if it changed, else None.

    ACKNOWLEDGED alerts still count: acknowledging means "seen", not "fixed",
    so the vehicle keeps its RED/YELLOW color until the alert is resolved.
    Vehicles with no open alerts and stale telemetry go GREY.
    """
    result = await session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        return None

    alerts_result = await session.execute(
        select(Alert.severity).where(
            Alert.vehicle_id == vehicle_id,
            Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]),
        )
    )
    severities = [row[0] for row in alerts_result.all()]

    if any(s == AlertSeverity.CRITICAL for s in severities):
        new_health = AssetHealth.RED
    elif any(s == AlertSeverity.WARNING for s in severities):
        new_health = AssetHealth.YELLOW
    elif vehicle.last_seen and not _is_stale(vehicle.last_seen):
        new_health = AssetHealth.GREEN
    else:
        new_health = AssetHealth.GREY

    if vehicle.health != new_health:
        await log_health_transition(
            session,
            vehicle_id,
            vehicle.health,
            new_health,
            reason=reason or "recompute",
        )
        vehicle.health = new_health
        return new_health
    return None


async def recompute_and_publish(
    session: AsyncSession,
    vehicle_id: int,
    reason: Optional[str] = None,
) -> Optional[str]:
    """Recompute vehicle health and broadcast via WebSocket if changed."""
    new_health = await recompute_health(session, vehicle_id, reason=reason)
    if new_health:
        await publish_health_update(vehicle_id, new_health.value)
    return new_health.value if new_health else None
