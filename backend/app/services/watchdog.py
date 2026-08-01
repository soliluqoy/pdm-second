"""
PREDICT — Offline watchdog
Background task: vehicles whose telemetry has gone stale (and that have no
open alerts) revert from GREEN to GREY so the dashboard reflects reality.
Runs every WATCHDOG_INTERVAL_SECONDS.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.db.database import async_session_factory
from app.db.models import AssetHealth, Vehicle
from app.db.redis_client import publish_health_update
from app.services.health import recompute_health

logger = logging.getLogger("predict.watchdog")

_task: asyncio.Task | None = None


async def _sweep_once() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.OFFLINE_AFTER_SECONDS)
    async with async_session_factory() as session:
        result = await session.execute(
            select(Vehicle.id).where(
                Vehicle.is_active == True,  # noqa: E712
                Vehicle.health == AssetHealth.GREEN,
                (Vehicle.last_seen.is_(None)) | (Vehicle.last_seen < cutoff),
            )
        )
        stale_ids = [row[0] for row in result.all()]
        for vehicle_id in stale_ids:
            new_health = await recompute_health(session, vehicle_id)
            if new_health:
                await session.commit()
                await publish_health_update(vehicle_id, new_health.value)
                logger.info("Vehicle %s marked %s (telemetry stale)", vehicle_id, new_health.value)


async def _run() -> None:
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Watchdog sweep failed: %s", e)
        await asyncio.sleep(settings.WATCHDOG_INTERVAL_SECONDS)


def start_watchdog() -> None:
    global _task
    _task = asyncio.create_task(_run())
    logger.info("Offline watchdog started (stale after %ds, sweep every %ds)",
                settings.OFFLINE_AFTER_SECONDS, settings.WATCHDOG_INTERVAL_SECONDS)


async def stop_watchdog() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
