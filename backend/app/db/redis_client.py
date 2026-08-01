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


# Live-state keys expire after a day so stale vehicles don't linger forever.
STATE_TTL_SECONDS = 24 * 3600


# ── Helpers: latest vehicle state ─────────────────────────────────────────────
async def set_vehicle_state(vehicle_id: int, state: dict) -> None:
    """Cache the latest sensor snapshot for a vehicle (full replace)."""
    key = f"vehicle:{vehicle_id}:state"
    await redis_client.set(key, json.dumps(state, default=str), ex=STATE_TTL_SECONDS)


async def merge_vehicle_state(vehicle_id: int, state: dict) -> dict:
    """Merge a (possibly partial) telemetry snapshot into the cached state.

    Teltonika AVL records legitimately omit IO elements, so a full replace
    would blank out sensors until the next record that happens to carry them.
    Sensors are merged per-type and each carries its own timestamp so the
    dashboard can judge freshness per sensor. Returns the merged state.
    """
    key = f"vehicle:{vehicle_id}:state"
    existing_raw = await redis_client.get(key)
    merged = {}
    if existing_raw:
        try:
            merged = json.loads(existing_raw)
        except (ValueError, TypeError):
            merged = {}

    new_sensors = state.pop("sensors", {}) or {}
    old_sensors = merged.get("sensors") or {}
    ts = state.get("timestamp")
    for sensor_type, reading in new_sensors.items():
        if isinstance(reading, dict):
            reading = {**reading, "timestamp": ts}
        else:
            reading = {"value": reading, "unit": None, "timestamp": ts}
        old_sensors[sensor_type] = reading

    # Top-level fields (timestamp, gps, ignition, ...) always come from the
    # newest record; None values must not clobber known state.
    for k, v in state.items():
        if v is not None or k not in merged:
            merged[k] = v
    merged["sensors"] = old_sensors

    await redis_client.set(key, json.dumps(merged, default=str), ex=STATE_TTL_SECONDS)
    return merged


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


async def clear_all_vehicle_states() -> int:
    """Delete all cached vehicle state keys. Returns count deleted."""
    keys = [key async for key in redis_client.scan_iter(match="vehicle:*:state")]
    if keys:
        await redis_client.delete(*keys)
    return len(keys)


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