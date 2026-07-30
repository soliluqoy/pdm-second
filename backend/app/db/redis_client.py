"""
PREDICT — Redis Client
Used for: latest vehicle state cache, alert queue, WebSocket pub/sub.
"""
import json
from typing import Optional, Any

import redis.asyncio as redis

from app.config import settings

# ── Async Redis client ────────────────────────────────────────────────────────
redis_client: redis.Redis = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    encoding="utf-8",
)


async def get_redis() -> redis.Redis:
    """FastAPI dependency for Redis."""
    return redis_client


# ── Helpers: latest vehicle state ─────────────────────────────────────────────
async def set_vehicle_state(vehicle_id: int, state: dict) -> None:
    """Cache the latest sensor snapshot for a vehicle."""
    key = f"vehicle:{vehicle_id}:state"
    await redis_client.set(key, json.dumps(state, default=str))


async def get_vehicle_state(vehicle_id: int) -> Optional[dict]:
    """Retrieve the latest cached sensor snapshot for a vehicle."""
    key = f"vehicle:{vehicle_id}:state"
    data = await redis_client.get(key)
    if data:
        return json.loads(data)
    return None


async def get_all_vehicle_states() -> dict:
    """Retrieve latest state for all vehicles (keys: vehicle:*:state)."""
    states = {}
    async for key in redis_client.scan_iter(match="vehicle:*:state"):
        vid = key.split(":")[1]
        data = await redis_client.get(key)
        if data:
            states[int(vid)] = json.loads(data)
    return states


# ── Helpers: WebSocket pub/sub ────────────────────────────────────────────────
async def publish_event(channel: str, payload: Any) -> None:
    """Publish an event to a Redis pub/sub channel for WebSocket fan-out."""
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload, default=str)
    await redis_client.publish(channel, payload)


async def publish_telemetry(vehicle_id: int, data: dict) -> None:
    """Publish a telemetry update event."""
    await publish_event("ws:telemetry", {"vehicle_id": vehicle_id, "data": data})


async def publish_alert(alert_data: dict) -> None:
    """Publish a new alert event."""
    await publish_event("ws:alerts", alert_data)


async def publish_work_order(wo_data: dict) -> None:
    """Publish a new work order event."""
    await publish_event("ws:workorders", wo_data)


async def publish_health_update(vehicle_id: int, health: str) -> None:
    """Publish a vehicle health change event."""
    await publish_event("ws:health", {"vehicle_id": vehicle_id, "health": health})