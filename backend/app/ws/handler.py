"""
PREDICT — WebSocket Handler
Real-time push to the dashboard via Redis pub/sub fan-out.
Clients subscribe to channels: telemetry, alerts, workorders, health.
"""
import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket, WebSocketDisconnect

from app.db.redis_client import redis_client

logger = logging.getLogger("predict.ws")


class ConnectionManager:
    """Manages active WebSocket connections and Redis pub/sub fan-out."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._pubsub_task: asyncio.Task = None

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("WebSocket client connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket client."""
        self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, channel: str, message: str):
        """Send a message to all connected clients."""
        payload = json.dumps({"channel": channel, "data": json.loads(message)})
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def listen_redis(self):
        """Listen to Redis pub/sub channels and broadcast to WebSocket clients."""
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("ws:telemetry", "ws:alerts", "ws:workorders", "ws:health")
        logger.info("WebSocket manager listening to Redis pub/sub channels")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    data = message["data"]
                    await self.broadcast(channel, data)
        except asyncio.CancelledError:
            logger.info("Redis pub/sub listener cancelled")
        except Exception as e:
            logger.error("Redis pub/sub listener error: %s", e)
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()


# ── Singleton ─────────────────────────────────────────────────────────────────
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time dashboard updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; clients can send pings
            data = await websocket.receive_text()
            # Echo ping for keepalive
            if data == "ping":
                await websocket.send_text(json.dumps({"channel": "pong", "data": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


async def start_ws_listener():
    """Start the Redis pub/sub listener task (called on app startup)."""
    manager._pubsub_task = asyncio.create_task(manager.listen_redis())


async def stop_ws_listener():
    """Stop the Redis pub/sub listener task (called on app shutdown)."""
    if manager._pubsub_task:
        manager._pubsub_task.cancel()
        try:
            await manager._pubsub_task
        except asyncio.CancelledError:
            pass