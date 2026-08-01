"""
PREDICT — Telemetry data reset
Wipes ingested sensor data, alerts, work orders, and Redis live cache.
Vehicle registration (components/sensors catalog) is preserved.
"""
import logging

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, AssetHealth, MaintenanceHistory, SensorReading, Vehicle, WorkOrder
from app.db.redis_client import clear_all_vehicle_states

logger = logging.getLogger("predict.telemetry_reset")


async def reset_telemetry_data(session: AsyncSession) -> dict:
    """Delete all telemetry-derived rows and clear Redis vehicle state."""
    maint = await session.execute(delete(MaintenanceHistory))
    await session.execute(update(Alert).values(work_order_id=None))
    wo = await session.execute(delete(WorkOrder))
    alerts = await session.execute(delete(Alert))
    readings = await session.execute(delete(SensorReading))
    vehicles = await session.execute(
        update(Vehicle).values(last_seen=None, health=AssetHealth.GREY)
    )
    await session.commit()

    redis_keys = await clear_all_vehicle_states()

    counts = {
        "maintenance_history_deleted": maint.rowcount or 0,
        "work_orders_deleted": wo.rowcount or 0,
        "alerts_deleted": alerts.rowcount or 0,
        "sensor_readings_deleted": readings.rowcount or 0,
        "vehicles_reset": vehicles.rowcount or 0,
        "redis_state_keys_deleted": redis_keys,
    }
    logger.info("Telemetry reset complete: %s", counts)
    return counts
