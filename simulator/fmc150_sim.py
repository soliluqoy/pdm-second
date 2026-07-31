"""
PREDICT — Teltonika FMC150 Simulator
Emulates multiple FMC150 telematics gateways publishing realistic OBD-II/CAN
data via MQTT. Payload format mirrors the real FMC150 MQTT JSON structure.

Each simulated vehicle:
- Publishes telemetry every N seconds to fmc150/{imei}/telemetry
- Occasionally publishes DTC events to fmc150/{imei}/dtc
- Generates realistic sensor values with occasional injected anomalies
  (so the rule engine has something to catch)

Future real integration: configure a real FMC150's MQTT parameters to point
at the same broker with the same topic schema — zero backend changes needed.
"""
import json
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FMC150-SIM] %(levelname)s: %(message)s",
)
logger = logging.getLogger("fmc150_sim")

# ── Config (from environment) ────────────────────────────────────────────────
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "predict_sim")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "predict_sim_pass")
VEHICLE_COUNT = int(os.getenv("SIM_VEHICLE_COUNT", "5"))
PUBLISH_INTERVAL = int(os.getenv("SIM_PUBLISH_INTERVAL", "10"))  # seconds
ANOMALY_PROBABILITY = float(os.getenv("SIM_ANOMALY_PROBABILITY", "0.05"))

# ── Simulated Vehicles (mirror backend seed data) ─────────────────────────────
SIM_VEHICLES = [
    {"name": "Truck-001", "imei": "350424061234001", "make": "Ford", "model": "Transit"},
    {"name": "Truck-002", "imei": "350424061234002", "make": "Mercedes", "model": "Sprinter"},
    {"name": "Van-003", "imei": "350424061234003", "make": "Ford", "model": "Transit Connect"},
    {"name": "Truck-004", "imei": "350424061234004", "make": "Iveco", "model": "Daily"},
    {"name": "Van-005", "imei": "350424061234005", "make": "Renault", "model": "Master"},
]

# ── DTC codes for random injection ────────────────────────────────────────────
DTC_CODES = [
    {"code": "P0128", "description": "Engine coolant thermostat below regulating temperature", "severity": "warning"},
    {"code": "P0300", "description": "Random/multiple cylinder misfire detected", "severity": "critical"},
    {"code": "P0420", "description": "Catalyst system efficiency below threshold (Bank 1)", "severity": "warning"},
    {"code": "P0171", "description": "System too lean (Bank 1)", "severity": "warning"},
    {"code": "P0500", "description": "Vehicle Speed Sensor malfunction", "severity": "warning"},
    {"code": "P0115", "description": "Engine Coolant Temperature Circuit malfunction", "severity": "critical"},
]


class VehicleSimulator:
    """Simulates a single vehicle's telematics data stream."""

    def __init__(self, vehicle_config: dict):
        self.name = vehicle_config["name"]
        self.imei = vehicle_config["imei"]
        self.make = vehicle_config["make"]
        self.model = vehicle_config["model"]

        # Vehicle state (evolves over time)
        self.ignition = True
        self.odometer = random.uniform(15000, 80000)  # km
        self.engine_hours = random.uniform(500, 3000)  # hours
        self.fuel_level = random.uniform(60, 95)  # %
        self.is_anomalous = False
        self.anomaly_type = None
        self.anomaly_duration = 0

        # GPS base location (Singapore area for demo)
        self.lat = random.uniform(1.28, 1.35)
        self.lon = random.uniform(103.82, 103.90)

        logger.info("Initialized vehicle: %s (IMEI: %s)", self.name, self.imei)

    def _generate_telemetry(self) -> dict:
        """Generate a single telemetry payload mimicking FMC150 MQTT format."""
        now = datetime.now(timezone.utc)

        # Decide if we should inject an anomaly this cycle
        if not self.is_anomalous and random.random() < ANOMALY_PROBABILITY:
            self.is_anomalous = True
            self.anomaly_type = random.choice([
                "high_coolant_temp", "high_rpm", "low_fuel",
                "low_battery", "high_engine_load", "low_tire_pressure"
            ])
            duration_map = {
                "high_coolant_temp": random.randint(35, 45),
                "high_rpm": random.randint(8, 12),
                "low_battery": random.randint(8, 12),
                "high_engine_load": random.randint(35, 45),
                "low_tire_pressure": random.randint(3, 6),
                "low_fuel": random.randint(3, 6),
            }
            self.anomaly_duration = duration_map[self.anomaly_type]
            logger.warning("Injecting anomaly '%s' into %s for %d cycles",
                           self.anomaly_type, self.name, self.anomaly_duration)

        # Decrement anomaly duration
        if self.is_anomalous:
            self.anomaly_duration -= 1
            if self.anomaly_duration <= 0:
                self.is_anomalous = False
                self.anomaly_type = None
                logger.info("Anomaly cleared for %s", self.name)

        # Generate sensor values
        speed = max(0, random.gauss(55, 20)) if self.ignition else 0
        rpm = max(0, int(random.gauss(1800, 500))) if self.ignition else 0
        coolant_temp = random.gauss(88, 8)
        engine_load = max(0, min(100, random.gauss(45, 15)))
        oil_pressure = random.gauss(300, 40)
        trans_temp = random.gauss(75, 10)
        brake_pressure = random.gauss(2000, 500) if speed > 10 else 0
        tire_pressure = random.gauss(320, 15)
        battery_voltage = random.gauss(13.8, 0.3)

        # Apply anomaly overrides
        if self.anomaly_type == "high_coolant_temp":
            coolant_temp = random.gauss(112, 3)  # > critical threshold
        elif self.anomaly_type == "high_rpm":
            rpm = int(random.gauss(5600, 200))  # > critical threshold
        elif self.anomaly_type == "low_fuel":
            self.fuel_level = max(5, self.fuel_level - 2)
        elif self.anomaly_type == "low_battery":
            battery_voltage = random.gauss(11.2, 0.2)  # < critical threshold
        elif self.anomaly_type == "high_engine_load":
            engine_load = random.gauss(96, 1)  # > warning threshold
        elif self.anomaly_type == "low_tire_pressure":
            tire_pressure = random.gauss(190, 5)  # < warning threshold

        # Update evolving state
        if self.ignition and speed > 0:
            self.odometer += speed / 3600 * PUBLISH_INTERVAL  # km per interval
            self.engine_hours += PUBLISH_INTERVAL / 3600

        # Fuel consumption + refuel simulation
        if self.ignition:
            self.fuel_level = max(0, self.fuel_level - random.uniform(0.05, 0.15))
        if self.fuel_level < 15:
            self.fuel_level = random.uniform(70, 95)
            logger.info("Simulated refuel for %s → %.1f%%", self.name, self.fuel_level)
        fuel_level = self.fuel_level

        # Ignition cycles: occasionally turn off when stopped
        if self.ignition and speed == 0 and random.random() < 0.05:
            self.ignition = False
            logger.info("Ignition OFF for %s", self.name)
        elif not self.ignition and random.random() < 0.3:
            self.ignition = True
            logger.info("Ignition ON for %s", self.name)

        # GPS drift (simulate movement)
        if self.ignition and speed > 0:
            self.lat += random.uniform(-0.001, 0.001)
            self.lon += random.uniform(-0.001, 0.001)

        # Build FMC150-style payload
        # This mirrors the JSON structure the real FMC150 sends via MQTT
        payload = {
            "timestamp": now.isoformat(),
            "imei": self.imei,
            "vehicle_name": self.name,
            "ignition": self.ignition,
            "gps": {
                "latitude": round(self.lat, 6),
                "longitude": round(self.lon, 6),
                "speed": round(speed, 1),
                "altitude": random.uniform(10, 50),
                "angle": random.uniform(0, 360),
                "satellites": random.randint(6, 12),
            },
            "sensors": {
                "engine_rpm": {"value": rpm, "unit": "RPM"},
                "coolant_temperature": {"value": round(coolant_temp, 1), "unit": "°C"},
                "engine_load": {"value": round(engine_load, 1), "unit": "%"},
                "oil_pressure": {"value": round(oil_pressure, 1), "unit": "kPa"},
                "transmission_temperature": {"value": round(trans_temp, 1), "unit": "°C"},
                "brake_pressure": {"value": round(brake_pressure, 1), "unit": "kPa"},
                "tire_pressure_fl": {"value": round(tire_pressure, 1), "unit": "kPa"},
                "battery_voltage": {"value": round(battery_voltage, 2), "unit": "V"},
                "vehicle_speed": {"value": round(speed, 1), "unit": "km/h"},
                "fuel_level": {"value": round(fuel_level, 1), "unit": "%"},
                "odometer": {"value": round(self.odometer, 1), "unit": "km"},
                "engine_hours": {"value": round(self.engine_hours, 1), "unit": "h"},
            },
        }
        return payload

    def _maybe_generate_dtc(self) -> dict | None:
        """Occasionally generate a DTC event."""
        if not self.ignition:
            return None
        # Lower probability for DTCs
        if random.random() < ANOMALY_PROBABILITY * 0.3:
            dtc = random.choice(DTC_CODES)
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "imei": self.imei,
                "vehicle_name": self.name,
                "dtc_code": dtc["code"],
                "description": dtc["description"],
                "severity": dtc["severity"],
            }
        return None


class FMC150Simulator:
    """Manages multiple vehicle simulators and publishes to MQTT."""

    def __init__(self):
        self.client: mqtt.Client = None
        self.vehicles: list[VehicleSimulator] = []
        self._running = False
        self._thread: threading.Thread = None

    def start(self):
        """Start the simulator."""
        # Initialize vehicles
        count = min(VEHICLE_COUNT, len(SIM_VEHICLES))
        self.vehicles = [VehicleSimulator(v) for v in SIM_VEHICLES[:count]]

        # Connect MQTT
        self.client = mqtt.Client(
            client_id=f"fmc150-simulator-{int(time.time())}",
            protocol=mqtt.MQTTv5,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        logger.info("Connecting to MQTT broker at %s:%s ...", MQTT_HOST, MQTT_PORT)
        # Retry until the broker accepts connections (it may still be starting
        # even when compose ordering/healthchecks are bypassed).
        attempt = 0
        while True:
            try:
                self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
                break
            except Exception as e:
                attempt += 1
                logger.warning("MQTT connect attempt %d failed (%s); retrying in 3s...",
                               attempt, e)
                time.sleep(3)
        self.client.loop_start()

        # Start publishing loop in background thread
        self._running = True
        self._thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._thread.start()

        logger.info("Simulator started: %d vehicles, publish interval=%ds",
                     count, PUBLISH_INTERVAL)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Simulator connected to MQTT broker")
        else:
            logger.error("Simulator MQTT connection failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning("Simulator MQTT disconnected: %s", reason_code)

    def _publish_loop(self):
        """Main publishing loop."""
        while self._running:
            for vehicle in self.vehicles:
                try:
                    # Publish telemetry
                    telemetry = vehicle._generate_telemetry()
                    topic = f"fmc150/{vehicle.imei}/telemetry"
                    self.client.publish(topic, json.dumps(telemetry), qos=1)

                    # Maybe publish DTC
                    dtc = vehicle._maybe_generate_dtc()
                    if dtc:
                        dtc_topic = f"fmc150/{vehicle.imei}/dtc"
                        self.client.publish(dtc_topic, json.dumps(dtc), qos=1)
                        logger.info("Published DTC for %s: %s", vehicle.name, dtc["dtc_code"])

                except Exception as e:
                    logger.error("Error publishing for %s: %s", vehicle.name, e)

            time.sleep(PUBLISH_INTERVAL)

    def stop(self):
        """Stop the simulator."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        logger.info("Simulator stopped")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    sim = FMC150Simulator()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received...")
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    sim.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()