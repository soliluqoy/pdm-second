"""
PREDICT — Predictive Maintenance CMSS
FastAPI Application Entry Point

Startup:  DB init + seed → MQTT ingestion → WebSocket listener
Shutdown: MQTT stop → WebSocket stop → DB dispose
"""
import asyncio
import logging
import os
import sys

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import alerts, assets, dashboard, rules, system, workorders
from app.db.init_db import audit_dormant_rules, init_database, seed_database
from app.db.database import engine, async_session_factory
from app.ingestion.mqtt_service import mqtt_service
from app.services.settings_service import get_shadow_mode
from app.services.watchdog import start_watchdog, stop_watchdog
from app.ws.handler import start_ws_listener, stop_ws_listener, websocket_endpoint

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("predict")


# ── Lifespan (startup + shutdown) ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("=== PREDICT starting up ===")

    # 1. Initialize database (create tables + TimescaleDB hypertable)
    logger.info("Initializing database...")
    try:
        await init_database()
        await seed_database()
        await audit_dormant_rules()
    except Exception as e:
        logger.error("Database init error (will retry on next start): %s", e)

    # 2. Start WebSocket Redis pub/sub listener
    logger.info("Starting WebSocket listener...")
    await start_ws_listener()

    # 3. Start MQTT ingestion service
    logger.info("Starting MQTT ingestion service...")
    loop = asyncio.get_running_loop()
    mqtt_service.start(loop)

    # 4. Start offline watchdog (GREEN → GREY when telemetry goes stale)
    start_watchdog()

    logger.info("=== PREDICT ready ===  API: http://localhost:%d  Docs: /docs ===",
                settings.BACKEND_PORT)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("=== PREDICT shutting down ===")
    mqtt_service.stop()
    await stop_watchdog()
    await stop_ws_listener()
    await engine.dispose()
    logger.info("=== PREDICT stopped ===")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PREDICT — Predictive Maintenance CMSS",
    description="Sensor data → Rule engine → Work orders → Technician feedback loop",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(assets.router, prefix="/api/v1")
app.include_router(workorders.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(rules.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket_endpoint(websocket)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health_check():
    async with async_session_factory() as session:
        shadow = await get_shadow_mode(session)
    return {
        "status": "ok",
        "service": "PREDICT",
        "version": "0.1.0",
        "shadow_mode": shadow,
    }


@app.get("/", tags=["root"])
async def root():
    return {
        "service": "PREDICT — Predictive Maintenance CMSS",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": "/api/v1",
    }


# ── Run directly (for local dev without Docker) ────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True,
    )