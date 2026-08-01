"""
PREDICT — MQTT Ingestion Service
Subscribes to Teltonika telemetry/DTC topics (FMC001 + FMC150), stores readings
in TimescaleDB, updates Redis latest-state cache, and triggers the rule engine.

This is the "adapter seam": the fmc-bridge service (bridge/) decodes each
tracker's Teltonika AVL protocol and republishes here as JSON on
teltonika/{imei}/telemetry — so this service needs zero hardware knowledge.

Backpressure: paho callbacks push raw messages onto a bounded asyncio.Queue
consumed by a small worker pool. A device flushing a multi-hour store-and-
forward buffer therefore cannot spawn unbounded concurrent DB sessions; when
the queue is full the oldest message is dropped (readings are re-sent by the
device until ACKed at the bridge, and rules skip stale records anyway).
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
from app.db.redis_client import merge_vehicle_state, publish_telemetry, publish_health_update
from app.rules.engine import evaluate_dtc, evaluate_telemetry

logger = logging.getLogger("predict.ingestion")

QUEUE_MAXSIZE = 1000
WORKER_COUNT = 3


class MQTTIngestionService:
    """MQTT subscriber that ingests telematics data into the system.
    Runs paho-mqtt in a background thread; messages are handed to asyncio
    workers through a bounded queue."""

    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._workers: list[asyncio.Task] = []
        self._dropped = 0

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
        """Enqueue the message for the asyncio worker pool (thread-safe)."""
        if not (self._loop and self._loop.is_running() and self._queue is not None):
            return
        self._loop.call_soon_threadsafe(self._enqueue, msg.topic, msg.payload)

    def _enqueue(self, topic: str, payload: bytes) -> None:
        try:
            self._queue.put_nowait((topic, payload))
        except asyncio.QueueFull:
            # Drop the oldest message to keep latency bounded during bursts.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((topic, payload))
            except asyncio.QueueEmpty:
                pass
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.warning("Ingestion queue full — dropped %d message(s) so far",
                               self._dropped)

    # ── Worker pool ─────────────────────────────────────────────────────────────
    async def _worker(self, worker_id: int):
        while True:
            topic, payload = await self._queue.get()
            try:
                await self._handle_message(topic, payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Worker %d failed on %s: %s", worker_id, topic, e)
            finally:
                self._queue.task_done()

    # ── Async message handler ──────────────────────────────────────────────────
    async def _handle_message(self, topic: str, payload: bytes):
        """Parse and process an incoming MQTT message."""
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Failed to parse MQTT payload on topic %s: %s", topic, e)
            return

        # Extract IMEI from topic: teltonika/{imei}/telemetry or teltonika/{imei}/dtc
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

            # Parse bridge payload
            # Expected format: { "timestamp": "...", "gps": {...}, "sensors": {...} }
            ts = self._parse_timestamp(data.get("timestamp"))

            gps = data.get("gps", {})
            sensors = data.get("sensors", {})
            # None (unknown) when the record doesn't carry the ignition flag —
            # defaulting to True would pollute idle/trip analytics.
            ignition = data.get("ignition")

            # Build all readings for this record, insert in one batch
            readings = []
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

                readings.append(SensorReading(
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
                ))
                readings_added.append({
                    "sensor_type": sensor_type,
                    "value": float(val),
                    "unit": unit,
                })
            session.add_all(readings)

            # Update vehicle last_seen (only forward — buffered uploads can
            # replay old records after newer ones)
            if vehicle.last_seen is None or ts > vehicle.last_seen:
                vehicle.last_seen = ts

            # Update health to GREEN if was GREY (first / resumed data)
            was_grey = vehicle.health == AssetHealth.GREY
            if was_grey:
                vehicle.health = AssetHealth.GREEN

            await session.commit()

            # Merge (not replace) the latest-state snapshot in Redis: AVL
            # records legitimately omit IO elements, so a replace would blank
            # out sensor tiles until the next full record.
            partial_state = {
                "timestamp": ts.isoformat(),
                "imei": imei,
                "vehicle_id": vehicle.id,
                "vehicle_name": vehicle.name,
                "ignition": ignition,
                "gps": gps or None,
                "sensors": {r["sensor_type"]: {"value": r["value"], "unit": r["unit"]}
                            for r in readings_added},
            }
            merged_state = await merge_vehicle_state(vehicle.id, partial_state)

            # Publish telemetry event for WebSocket (merged view)
            await publish_telemetry(vehicle.id, merged_state)

            if was_grey:
                await publish_health_update(vehicle.id, AssetHealth.GREEN.value)

            # Freshness guard: the tracker buffers records when out of coverage and
            # burst-uploads them later. Everything above is STORED, but rules
            # only run on fresh data — replayed history must not fire alerts.
            record_age = (datetime.now(timezone.utc) - ts).total_seconds()
            if record_age <= settings.RULE_MAX_RECORD_AGE_SECONDS:
                try:
                    await evaluate_telemetry(
                        vehicle.id, imei, sensors, ts,
                        session=session, vehicle_name=vehicle.name,
                    )
                except Exception as e:
                    logger.error("Rule engine error: %s", e)
            else:
                logger.debug("Skipping rule evaluation: stale record "
                             "(age=%.0fs) vehicle=%s", record_age, vehicle.name)

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

            # Freshness guard — same rationale as telemetry (buffered uploads
            # from the device must not fire alerts for old faults).
            ts = self._parse_timestamp(data.get("timestamp"))
            record_age = (datetime.now(timezone.utc) - ts).total_seconds()
            if record_age > settings.RULE_MAX_RECORD_AGE_SECONDS:
                logger.debug("Skipping stale DTC (age=%.0fs) vehicle=%s code=%s",
                             record_age, vehicle.name, dtc_code)
                return

            try:
                await evaluate_dtc(
                    vehicle.id, imei, dtc_code, description, severity,
                    session=session, vehicle_name=vehicle.name,
                )
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
        """Start the worker pool and the MQTT subscriber thread."""
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._workers = [
            loop.create_task(self._worker(i)) for i in range(WORKER_COUNT)
        ]

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
        logger.info("MQTT ingestion service started (%d workers, queue %d)",
                    WORKER_COUNT, QUEUE_MAXSIZE)

    def _run_mqtt(self):
        """Run the MQTT client loop in a background thread."""
        try:
            self.client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
            self.client.loop_forever(retry_first_connection=True)
        except Exception as e:
            logger.error("MQTT connection error: %s", e)

    def stop(self):
        """Stop the MQTT subscriber and workers."""
        if self.client:
            self.client.disconnect()
            self.client.loop_stop()
        if self._thread:
            self._thread.join(timeout=5)
        for task in self._workers:
            task.cancel()
        self._workers = []
        logger.info("MQTT ingestion service stopped")


# ── Singleton ─────────────────────────────────────────────────────────────────
mqtt_service = MQTTIngestionService()
