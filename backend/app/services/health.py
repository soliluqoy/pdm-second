"""
PREDICT — Vehicle health computation
Shared helper used by the rule engine and alert/work-order endpoints.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, AlertSeverity, AlertStatus, AssetHealth, Vehicle
from app.db.redis_client import publish_health_update


async def recompute_health(session: AsyncSession, vehicle_id: int) -> Optional[AssetHealth]:
    """Recompute vehicle health from active alerts. Returns new health if changed."""
    result = await session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        return None

    alerts_result = await session.execute(
        select(Alert.severity).where(
            Alert.vehicle_id == vehicle_id,
            Alert.status == AlertStatus.ACTIVE,
        )
    )
    severities = [row[0] for row in alerts_result.all()]

    if any(s == AlertSeverity.CRITICAL for s in severities):
        new_health = AssetHealth.RED
    elif any(s == AlertSeverity.WARNING for s in severities):
        new_health = AssetHealth.YELLOW
    elif vehicle.last_seen:
        new_health = AssetHealth.GREEN
    else:
        new_health = AssetHealth.GREY

    if vehicle.health != new_health:
        vehicle.health = new_health
        return new_health
    return None


async def recompute_and_publish(session: AsyncSession, vehicle_id: int) -> Optional[str]:
    """Recompute vehicle health and broadcast via WebSocket if changed."""
    new_health = await recompute_health(session, vehicle_id)
    if new_health:
        await publish_health_update(vehicle_id, new_health.value)
    return new_health.value if new_health else None
