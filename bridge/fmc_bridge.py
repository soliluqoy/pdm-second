"""
PREDICT — Teltonika Bridge (FMC001 + FMC150, AVL → MQTT)

Listens on a raw TCP port for Teltonika tracker connections, performs the IMEI
handshake, decodes Codec 8 / 8 Extended AVL packets, maps I/O elements to
PREDICT sensor types, and publishes to Mosquitto using the exact JSON contract
the backend already consumes:

    teltonika/{imei}/telemetry  {timestamp, imei, ignition, gps{...}, sensors{...}}
    teltonika/{imei}/dtc        {timestamp, imei, dtc_code, description, severity}

Multi-model support: the Teltonika handshake carries only the IMEI (no model),
so the bridge is told which IMEI is which model via BRIDGE_DEVICES and applies
the matching avl_map.<model>.json (FMC001 = OBD-II IDs, FMC150 = CAN IDs).
Both maps normalize into the same sensor_type strings, so the backend, rule
engine, and dashboard stay device-agnostic.

The backend (mqtt_service.py) consumes the JSON contract unchanged — that is
the integration seam.

Run:  python fmc_bridge.py
Test with a real device: point the tracker's server settings at this host:port
(on a VPS, that is simply <VPS_STATIC_IP>:5123 — no tunnel needed).
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import paho.mqtt.client as mqtt

from codec8e import (
    AvlRecord,
    CodecError,
    IncompletePacket,
    build_ack,
    build_imei_reply,
    parse_avl_packet,
    parse_imei,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FMC-BRIDGE] %(levelname)s: %(message)s",
)
logger = logging.getLogger("fmc_bridge")

# ── Config (from environment) ─────────────────────────────────────────────────
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "predict_sim")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "predict_sim_pass")

BRIDGE_HOST = os.getenv("BRIDGE_HOST", "0.0.0.0")
BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "5123"))
BRIDGE_IDLE_TIMEOUT = int(os.getenv("BRIDGE_IDLE_TIMEOUT", "300"))  # seconds

# Device registry: comma-separated imei:model pairs, e.g.
#   BRIDGE_DEVICES=867648042983435:fmc001,357234561234567:fmc150
# The IMEI handshake carries no model info, so this is how the bridge picks
# the right avl_map.<model>.json. EMPTY = accept any device as DEFAULT_MODEL
# (handy for the first bench test; pin your real IMEI(s) afterwards).
BRIDGE_DEFAULT_MODEL = os.getenv("BRIDGE_DEFAULT_MODEL", "fmc001").strip().lower()


def parse_device_registry(raw: str) -> Dict[str, str]:
    """Parse 'imei:model,imei:model' → {imei: model}. Bare IMEI → default model."""
    devices: Dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            imei, model = item.rsplit(":", 1)
            devices[imei.strip()] = model.strip().lower() or BRIDGE_DEFAULT_MODEL
        else:
            devices[item] = BRIDGE_DEFAULT_MODEL
    return devices


DEVICE_MODELS = parse_device_registry(os.getenv("BRIDGE_DEVICES", ""))

# Deprecated fallback: bare IMEI allowlist (all treated as DEFAULT_MODEL).
_legacy_raw = os.getenv("BRIDGE_ALLOWED_IMEIS", "").strip()
if _legacy_raw and not DEVICE_MODELS:
    DEVICE_MODELS = parse_device_registry(_legacy_raw)
    logger.warning(
        "BRIDGE_ALLOWED_IMEIS is deprecated — use BRIDGE_DEVICES=imei:model,... "
        "(treating %d entr%s as %s)",
        len(DEVICE_MODELS), "y" if len(DEVICE_MODELS) == 1 else "ies",
        BRIDGE_DEFAULT_MODEL,
    )

TELEMETRY_TOPIC = "teltonika/{imei}/telemetry"
DTC_TOPIC = "teltonika/{imei}/dtc"


# ── AVL I/O maps (one per device model) ───────────────────────────────────────
def load_io_map(path: Path) -> Dict[int, dict]:
    """Load avl_map.<model>.json → {avl_id: entry}. Unknown keys (_readme) ignored."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = raw.get("io_elements", [])
    io_map = {int(e["id"]): e for e in entries}
    logger.info("Loaded %d I/O mappings from %s", len(io_map), path.name)
    return io_map


def load_all_io_maps() -> Dict[str, Dict[int, dict]]:
    """Load every avl_map.<model>.json sitting next to this file."""
    maps: Dict[str, Dict[int, dict]] = {}
    for path in sorted(Path(__file__).parent.glob("avl_map.*.json")):
        model = path.stem.split(".", 1)[1].lower()
        maps[model] = load_io_map(path)
    if not maps:
        raise RuntimeError("No avl_map.<model>.json files found next to fmc_bridge.py")
    if BRIDGE_DEFAULT_MODEL not in maps:
        raise RuntimeError(
            f"BRIDGE_DEFAULT_MODEL={BRIDGE_DEFAULT_MODEL!r} has no map file "
            f"(available: {', '.join(sorted(maps))})"
        )
    return maps


IO_MAPS = load_all_io_maps()

# Discovery aid: each unmapped AVL ID is logged once per process so you can
# see exactly what YOUR car/firmware sends and add it to the model's map file.
_unmapped_seen: set[tuple[str, int]] = set()


def record_to_payload(imei: str, record: AvlRecord, io_map: Dict[int, dict],
                      model: str = "?") -> Tuple[dict, list]:
    """Convert one AvlRecord into (telemetry_payload, dtc_codes)."""
    payload = {
        "timestamp": record.timestamp.isoformat(),
        "imei": imei,
        "ignition": True,  # default unless AVL 239 (or mapped id) says otherwise
        "gps": {
            "latitude": record.latitude,
            "longitude": record.longitude,
            "speed": record.speed,
            "altitude": record.altitude,
            "angle": record.angle,
            "satellites": record.satellites,
        },
        "sensors": {},
    }
    dtcs: list[str] = []

    for avl_id, raw in record.io.items():
        entry = io_map.get(avl_id)
        if entry is None:
            key = (model, avl_id)
            if key not in _unmapped_seen:
                _unmapped_seen.add(key)
                logger.info(
                    "Unmapped AVL ID %s (value=%r) from IMEI %s (%s) — "
                    "add it to avl_map.%s.json if you want it on the dashboard",
                    avl_id, raw, imei, model, model,
                )
            continue

        if isinstance(raw, (bytes, bytearray)):
            # Variable-length (8E X-group) values arrive as bytes. Entries with
            # "encoding": "ascii" are human-readable (VIN, fault codes);
            # anything else stays a hex dump for discovery purposes.
            if entry.get("encoding") == "ascii":
                value = raw.decode("ascii", errors="ignore").strip("\x00").strip()
            else:
                value = raw.hex()
        else:
            value = raw * entry.get("scale", 1) + entry.get("offset", 0)
            if isinstance(value, float):
                value = round(value, 4)

        kind = entry.get("kind", "sensor")
        sensor_type = entry["sensor_type"]

        if kind == "sensor":
            payload["sensors"][sensor_type] = {
                "value": value,
                "unit": entry.get("unit", ""),
            }
        elif kind == "meta":
            if sensor_type == "ignition":
                payload["ignition"] = bool(int(value)) if not isinstance(value, str) else bool(value)
            else:
                payload[sensor_type] = value
        elif kind == "dtc":
            # Both models send all active fault codes in one ASCII element,
            # comma-separated (e.g. "P0128,P0300") — publish each separately
            # so DTC rules can match individual codes.
            for code in str(value).split(","):
                code = code.strip()
                if code:
                    dtcs.append(code)

    return payload, dtcs


# ── MQTT client (paho runs its network loop in a background thread; publish()
# is thread-safe, so the asyncio server can call it directly) ──────────────────
mqtt_client = mqtt.Client(
    client_id=f"fmc-bridge-{int(time.time())}",
    protocol=mqtt.MQTTv5,
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)


def mqtt_connect_with_retry():
    attempt = 0
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            mqtt_client.loop_start()
            logger.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
            return
        except Exception as e:
            attempt += 1
            logger.warning("MQTT connect attempt %d failed (%s); retrying in 3s...", attempt, e)
            time.sleep(3)


def publish(topic: str, payload: dict):
    try:
        mqtt_client.publish(topic, json.dumps(payload), qos=1)
    except Exception as e:
        logger.error("MQTT publish failed on %s: %s", topic, e)


# ── Per-device connection handler ─────────────────────────────────────────────
async def handle_device(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    imei: Optional[str] = None
    try:
        # ── Phase 1: IMEI handshake ───────────────────────────────────────────
        buf = b""
        while True:
            chunk = await asyncio.wait_for(reader.read(256), timeout=30)
            if not chunk:
                return
            buf += chunk
            try:
                imei, consumed = parse_imei(buf)
                break
            except IncompletePacket:
                continue

        if DEVICE_MODELS and imei not in DEVICE_MODELS:
            logger.warning("REJECTED unknown IMEI %s from %s", imei, peer)
            writer.write(build_imei_reply(False))
            await writer.drain()
            return

        model = DEVICE_MODELS.get(imei, BRIDGE_DEFAULT_MODEL)
        io_map = IO_MAPS.get(model)
        if io_map is None:
            logger.warning(
                "REJECTED IMEI %s: model %r has no avl_map.%s.json (available: %s)",
                imei, model, model, ", ".join(sorted(IO_MAPS)),
            )
            writer.write(build_imei_reply(False))
            await writer.drain()
            return

        writer.write(build_imei_reply(True))
        await writer.drain()
        logger.info("Device connected: IMEI %s (%s) from %s", imei, model.upper(), peer)

        buf = buf[consumed:]

        # ── Phase 2: AVL packet loop ──────────────────────────────────────────
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=BRIDGE_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                logger.info("Idle timeout (%ds), closing IMEI %s", BRIDGE_IDLE_TIMEOUT, imei)
                return
            if not chunk:
                return
            buf += chunk

            # Drain as many complete packets as the buffer holds
            while buf:
                try:
                    records, consumed = parse_avl_packet(buf)
                except IncompletePacket:
                    break
                except CodecError as e:
                    # Corrupt frame — drop one byte to resync. Un-ACKed records
                    # stay in the device buffer and are retransmitted.
                    logger.warning("Bad packet from IMEI %s: %s — dropping 1 byte", imei, e)
                    buf = buf[1:]
                    continue

                buf = buf[consumed:]

                for record in records:
                    payload, dtcs = record_to_payload(imei, record, io_map, model)
                    publish(TELEMETRY_TOPIC.format(imei=imei), payload)
                    for code in dtcs:
                        publish(DTC_TOPIC.format(imei=imei), {
                            "timestamp": record.timestamp.isoformat(),
                            "imei": imei,
                            "dtc_code": code,
                            "description": "",
                            "severity": "warning",
                        })

                writer.write(build_ack(len(records)))
                await writer.drain()
                logger.info("IMEI %s: %d record(s) published, ACK sent", imei, len(records))

    except (ConnectionResetError, BrokenPipeError):
        logger.info("Connection lost: IMEI %s (%s)", imei or "?", peer)
    except Exception:
        logger.exception("Unexpected error for IMEI %s (%s)", imei or "?", peer)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        if imei:
            logger.info("Device disconnected: IMEI %s", imei)


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    mqtt_connect_with_retry()

    if not DEVICE_MODELS:
        logger.warning(
            "BRIDGE_DEVICES is empty — ANY device IMEI will be accepted as %s. "
            "Set BRIDGE_DEVICES=imei:model,... once you know your IMEIs.",
            BRIDGE_DEFAULT_MODEL,
        )

    server = await asyncio.start_server(handle_device, BRIDGE_HOST, BRIDGE_PORT)
    logger.info("Teltonika bridge listening on %s:%d (Codec 8/8E → MQTT %s:%d, models: %s)",
                BRIDGE_HOST, BRIDGE_PORT, MQTT_HOST, MQTT_PORT, ", ".join(sorted(IO_MAPS)))

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bridge stopped")
