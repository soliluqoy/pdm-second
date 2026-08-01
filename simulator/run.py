#!/usr/bin/env python3
"""
External FMC150 vehicle simulator for PREDICT.

Publishes MQTT telemetry matching the bridge contract so the dashboard
Live telemetry / graphs / rules work without a real tracker.

Usage (from this directory, with the Docker stack already running):
  pip install -r requirements.txt
  python run.py

Disable: set enabled: false in config.yaml, or Ctrl+C to stop publishing.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

import yaml

from mqtt_pub import TelemetryPublisher
from register import ensure_vehicle
from vehicle import DEFAULT_SPIKE_PROFILES, SimulatedVehicle

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("simulator")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing config: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    cfg = load_config()
    if not cfg.get("enabled", True):
        print(
            "Simulator disabled (enabled: false in config.yaml). "
            "Set enabled: true to start the feed."
        )
        return 0

    vehicle_cfg = cfg.get("vehicle") or {}
    api_cfg = cfg.get("api") or {}
    mqtt_cfg = cfg.get("mqtt") or {}
    pub_cfg = cfg.get("publish") or {}
    spike_cfg = cfg.get("spikes") or {}

    imei = str(vehicle_cfg.get("imei", "999150000000001"))
    interval = float(pub_cfg.get("interval_seconds", 2.0))
    api_base = str(api_cfg.get("base_url", "http://localhost:8000"))

    logger.info("Ensuring vehicle is registered at %s …", api_base)
    try:
        registered = ensure_vehicle(api_base, vehicle_cfg)
    except Exception as e:
        logger.error("Registration failed: %s", e)
        logger.error("Is the backend running? (http://localhost:8000/health)")
        return 1

    logger.info(
        "Vehicle ready: id=%s name=%r → open http://localhost:5173/",
        registered.get("id"),
        registered.get("name"),
    )

    sim = SimulatedVehicle(
        imei=imei,
        cruise_seconds=float(spike_cfg.get("cruise_seconds", 150)),
        spike_seconds=float(spike_cfg.get("spike_seconds", 40)),
        spikes_enabled=bool(spike_cfg.get("enabled", True)),
        profiles=list(spike_cfg.get("profiles") or DEFAULT_SPIKE_PROFILES),
    )

    publisher = TelemetryPublisher(
        host=str(mqtt_cfg.get("host", "localhost")),
        port=int(mqtt_cfg.get("port", 1883)),
        username=str(mqtt_cfg.get("username", "predict_sim")),
        password=str(mqtt_cfg.get("password", "predict_sim_pass")),
        imei=imei,
        qos=int(mqtt_cfg.get("qos", 1)),
    )

    stop = False

    def _stop(*_args):
        nonlocal stop
        stop = True
        logger.info("Stopping simulator (Ctrl+C) — telemetry feed disabled.")

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        publisher.connect()
    except Exception as e:
        logger.error("%s", e)
        return 1

    logger.info(
        "Publishing every %.1fs to teltonika/%s/telemetry (spikes=%s)",
        interval,
        imei,
        sim.spikes_enabled,
    )

    last_mode = ""
    try:
        while not stop:
            payload, dtcs = sim.tick()
            publisher.publish_telemetry(payload)
            for dtc in dtcs:
                publisher.publish_dtc(dtc)

            mode = sim.mode_label
            if mode != last_mode:
                logger.info("Mode → %s", mode)
                last_mode = mode

            # Sleep in small slices so Ctrl+C is responsive
            deadline = time.monotonic() + interval
            while not stop and time.monotonic() < deadline:
                time.sleep(0.1)
    finally:
        publisher.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
