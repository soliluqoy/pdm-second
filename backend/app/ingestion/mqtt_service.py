"""
PREDICT — MQTT Ingestion Service
Subscribes to FMC150 telemetry/DTC topics, stores readings in TimescaleDB,
updates Redis latest-state cache, and triggers the rule engine.

This is the "adapter seam": the simulator and real FMC150 both publish to the
same topic schema (fmc150/{imei}/telemetry) with the same JSON payload shape.
The backend knows nothing about whether the source is real or simulated.
"""
import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt
from sqlalchemy import select

from app.config import settings
from app.db.database import async_session_factory
from app.db.models import SensorReading, Vehicle, AssetHealth
from app.db.redis_client import set_vehicle_state, publish_telemetry, publish_health_update

logger = logging.getLogger("predict.ingestion")


class MQTTIngestionService:
    """MQTT subscriber that ingests telematics data into the system.
    Runs paho-mqtt in a background thread, bridges callbacks to asyncio."""

    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── MQTT Callbacks (called from paho's thread) ─────────────────────────────
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("MQTT connected to %s:%s", settings.MQTT_HOST, settings.MQTT_PORT)
            client.subscribe(settings.MQTT_TELEMETRY_TOPIC, qos=1)
            client.subscribe(settings.MQTT_DTC_TOPIC, qos=1)
            logger.info("Subscribed to: %s, %s",
                        settings.MQTT_TELEMETRY_TOPIC, settings.MQTT_DTC_TOPIC)
        else:
            logger.error("MQTT connection failed, reason_code=%s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning("MQTT disconnected, reason_code=%s", reason_code)

    def on_message(self, client, userdata, msg):
        """Bridge MQTT message to asyncio loop."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._handle_message(msg.topic, msg.payload), self._loop
            )

    # ── Async message handler ──────────────────────────────────────────────────
    async def _handle_message(self, topic: str, payload: bytes):
        """Parse and process an incoming MQTT message."""
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to parse MQTT payload on topic %s: %s", topic, e)
            return

        # Extract IMEI from topic: fmc150/{imei}/telemetry or fmc150/{imei}/dtc
        parts = topic.split("/")
        if len(parts) < 3:
            logger.warning("Unexpected topic format: %s", topic)
            return

        imei = parts[1]
        msg_type = parts[2]  # "telemetry" or "dtc"

        if msg_type == "telemetry":
            await self._handle_telemetry(imei, data)
        elif msg_type == "dtc":
            await self._handle_dtc(imei, data)

    async def _handle_telemetry(self, imei: str, data: dict):
        """Process a telemetry message: store readings + update state + trigger rules."""
        async with async_session_factory() as session:
            # Look up vehicle by IMEI
            result = await session.execute(
                select(Vehicle).where(Vehicle.imei == imei)
            )
            vehicle = result.scalar_one_or_none()
            if not vehicle:
                logger.warning("Telemetry from unknown IMEI: %s", imei)
                return

            # Parse FMC150-style payload
            # Expected format: { "timestamp": "...", "gps": {...}, "sensors": {...} }
            ts = self._parse_timestamp(data.get("timestamp"))

            gps = data.get("gps", {})
            sensors = data.get("sensors", {})
            ignition = data.get("ignition", True)

            # Store each sensor reading
            readings_added = []
            for sensor_type, value in sensors.items():
                if value is None:
                    continue
                # Handle nested {value, unit} or plain value
                if isinstance(value, dict):
                    val = value.get("value")
                    unit = value.get("unit")
                else:
                    val = value
                    unit = self._guess_unit(sensor_type)

                if val is None:
                    continue

                reading = SensorReading(
                    timestamp=ts,
                    vehicle_id=vehicle.id,
                    imei=imei,
                    sensor_type=sensor_type,
                    sensor_name=sensor_type.replace("_", " ").title(),
                    value=float(val),
                    unit=unit,
                    quality="good",
                    latitude=gps.get("latitude"),
                    longitude=gps.get("longitude"),
                    speed=gps.get("speed"),
                    ignition=ignition,
                )
                session.add(reading)
                readings_added.append({
                    "sensor_type": sensor_type,
                    "value": float(val),
                    "unit": unit,
                })

            # Update vehicle last_seen
            vehicle.last_seen = ts

            # Update health to GREEN if was GREY (first data)
            if vehicle.health == AssetHealth.GREY:
                vehicle.health = AssetHealth.GREEN

            await session.commit()

            # Build latest state snapshot for Redis
            state = {
                "timestamp": ts.isoformat(),
                "imei": imei,
                "vehicle_id": vehicle.id,
                "vehicle_name": vehicle.name,
                "ignition": ignition,
                "gps": gps,
                "sensors": {r["sensor_type"]: {"value": r["value"], "unit": r["unit"]}
                            for r in readings_added},
            }
            await set_vehicle_state(vehicle.id, state)

            # Publish telemetry event for WebSocket
            await publish_telemetry(vehicle.id, state)

            # Trigger rule engine (Phase 2)
            try:
                from app.rules.engine import evaluate_telemetry
                await evaluate_telemetry(vehicle.id, imei, sensors, ts)
            except ImportError:
                pass  # Rule engine not yet implemented (Phase 1)
            except Exception as e:
                logger.error("Rule engine error: %s", e)

            logger.debug("Ingested %d readings for vehicle %s (IMEI %s)",
                         len(readings_added), vehicle.name, imei)

    async def _handle_dtc(self, imei: str, data: dict):
        """Process a DTC (Diagnostic Trouble Code) message."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Vehicle).where(Vehicle.imei == imei)
            )
            vehicle = result.scalar_one_or_none()
            if not vehicle:
                logger.warning("DTC from unknown IMEI: %s", imei)
                return

            dtc_code = data.get("dtc_code")
            description = data.get("description", "")
            severity = data.get("severity", "warning")

            logger.info("DTC received: vehicle=%s IMEI=%s code=%s desc=%s",
                        vehicle.name, imei, dtc_code, description)

            # Trigger DTC rule evaluation (Phase 2)
            try:
                from app.rules.engine import evaluate_dtc
                await evaluate_dtc(vehicle.id, imei, dtc_code, description, severity)
            except ImportError:
                pass
            except Exception as e:
                logger.error("DTC rule engine error: %s", e)

    @staticmethod
    def _parse_timestamp(timestamp_str: Optional[str]) -> datetime:
        """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime.

        - Naive input is assumed to already be UTC.
        - Offset-aware input is converted to UTC (never silently stripped —
          ``replace(tzinfo=None)`` on a ``+08:00`` value would corrupt it).
        - Missing/unparseable input falls back to now (UTC).
        """
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    return ts.replace(tzinfo=timezone.utc)
                return ts.astimezone(timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _guess_unit(self, sensor_type: str) -> str:
        """Guess the unit for a sensor type if not provided."""
        units = {
            "rpm": "RPM",
            "engine_rpm": "RPM",
            "coolant_temperature": "°C",
            "temperature": "°C",
            "engine_temperature": "°C",
            "speed": "km/h",
            "vehicle_speed": "km/h",
            "fuel_level": "%",
            "fuel": "%",
            "odometer": "km",
            "engine_hours": "h",
            "battery_voltage": "V",
            "voltage": "V",
            "oil_pressure": "kPa",
            "tire_pressure": "kPa",
            "load": "%",
            "engine_load": "%",
        }
        return units.get(sensor_type, "")

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def start(self, loop: asyncio.AbstractEventLoop):
        """Start the MQTT subscriber in a background thread."""
        self._loop = loop
        self._running = True

        self.client = mqtt.Client(
            client_id=f"predict-backend-{id(self)}",
            protocol=mqtt.MQTTv5,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._thread = threading.Thread(target=self._run_mqtt, daemon=True)
        self._thread.start()
        logger.info("MQTT ingestion service started")

    def _run_mqtt(self):
        """Run the MQTT client loop in a background thread."""
        try:
            self.client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
            self.client.loop_forever(retry_first_connection=True)
        except Exception as e:
            logger.error("MQTT connection error: %s", e)

    def stop(self):
        """Stop the MQTT subscriber."""
        self._running = False
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("MQTT ingestion service stopped")


# ── Singleton ─────────────────────────────────────────────────────────────────
mqtt_service = MQTTIngestionService()