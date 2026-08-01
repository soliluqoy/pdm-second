"""FMC150 simulated vehicle state: cruise drift + threshold-crossing spikes."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Units must match bridge / provisioning catalogs.
SENSOR_UNITS: dict[str, str] = {
    "vehicle_speed": "km/h",
    "battery_voltage": "V",
    "tracker_battery_voltage": "V",
    "gsm_signal": "1-5",
    "engine_rpm": "RPM",
    "coolant_temperature": "°C",
    "fuel_level": "%",
    "fuel_level_liters": "l",
    "fuel_consumed": "l",
    "engine_oil_temperature": "°C",
    "engine_oil_pressure": "kPa",
    "engine_oil_level": "%",
    "throttle_position": "%",
    "vehicle_speed_obd": "km/h",
    "odometer": "km",
    "engine_hours": "min",
    "ambient_air_temperature": "°C",
    "hv_battery_charge": "%",
    "vehicle_battery_voltage": "V",
    "distance_until_service": "km",
    "remaining_distance": "km",
    "dtc_count": "",
}

DEFAULT_SPIKE_PROFILES = (
    "overheat",
    "high_rpm",
    "low_fuel",
    "low_battery",
    "service_due",
    "dtc",
)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _noise(scale: float) -> float:
    return random.uniform(-scale, scale)


@dataclass
class SimulatedVehicle:
    imei: str
    cruise_seconds: float = 150.0
    spike_seconds: float = 40.0
    spikes_enabled: bool = True
    profiles: list[str] = field(default_factory=lambda: list(DEFAULT_SPIKE_PROFILES))

    # KL-ish starting point
    lat: float = 3.1390
    lon: float = 101.6869
    heading: float = 45.0

    odometer_km: float = 48250.0
    engine_hours_min: float = 18540.0
    fuel_consumed_l: float = 6120.0
    fuel_level_pct: float = 55.0
    distance_until_service: float = 4200.0
    remaining_distance: float = 380.0

    _t0: float = field(default_factory=time.monotonic)
    _phase_t0: float = field(default_factory=time.monotonic)
    _profile_idx: int = 0
    _in_spike: bool = False
    _pending_dtcs: list[str] = field(default_factory=list)

    def tick(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Advance state; return (telemetry_payload, dtc_messages)."""
        now = time.monotonic()
        self._advance_phase(now)

        mode = self._current_mode()
        sensors = self._cruise_sensors(now)

        if mode == "overheat":
            sensors["coolant_temperature"] = 108.0 + _noise(4)
            sensors["engine_oil_temperature"] = 128.0 + _noise(3)
        elif mode == "high_rpm":
            sensors["engine_rpm"] = 5200.0 + _noise(300)
            sensors["throttle_position"] = 85.0 + _noise(8)
            sensors["vehicle_speed"] = 95.0 + _noise(10)
            sensors["vehicle_speed_obd"] = sensors["vehicle_speed"]
        elif mode == "low_fuel":
            sensors["fuel_level"] = 12.0 + _noise(4)
            sensors["fuel_level_liters"] = sensors["fuel_level"] * 0.55
            sensors["remaining_distance"] = 45.0 + _noise(15)
        elif mode == "low_battery":
            sensors["battery_voltage"] = 11.2 + _noise(0.15)
            sensors["vehicle_battery_voltage"] = 11.1 + _noise(0.15)
        elif mode == "service_due":
            sensors["distance_until_service"] = 120.0 + _noise(80)
        elif mode == "dtc":
            sensors["dtc_count"] = 1.0
            sensors["coolant_temperature"] = 98.0 + _noise(2)

        # Keep cumulative fields coherent
        sensors["odometer"] = round(self.odometer_km, 3)
        sensors["engine_hours"] = round(self.engine_hours_min, 0)
        sensors["fuel_consumed"] = round(self.fuel_consumed_l, 1)

        speed = float(sensors["vehicle_speed"])
        self._drift_gps(speed)
        self._accumulate(speed, float(sensors["engine_rpm"]))

        ignition = True
        movement = speed > 3.0

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "imei": self.imei,
            "ignition": ignition,
            "movement": movement,
            "vin": "SIMFMC15000000001",
            "gps": {
                "latitude": round(self.lat, 6),
                "longitude": round(self.lon, 6),
                "speed": round(speed, 1),
                "altitude": round(45.0 + _noise(3), 1),
                "angle": round(self.heading % 360, 1),
                "satellites": int(_clamp(10 + _noise(2), 6, 14)),
            },
            "sensors": {
                k: {"value": round(float(v), 3 if abs(float(v)) < 100 else 1), "unit": SENSOR_UNITS.get(k, "")}
                for k, v in sensors.items()
            },
        }

        dtcs = self._drain_dtcs(mode)
        return payload, dtcs

    def _current_mode(self) -> str:
        if not self.spikes_enabled or not self._in_spike or not self.profiles:
            return "cruise"
        return self.profiles[self._profile_idx % len(self.profiles)]

    def _advance_phase(self, now: float) -> None:
        if not self.spikes_enabled or not self.profiles:
            self._in_spike = False
            return
        elapsed = now - self._phase_t0
        if self._in_spike:
            if elapsed >= self.spike_seconds:
                self._in_spike = False
                self._phase_t0 = now
                self._profile_idx = (self._profile_idx + 1) % len(self.profiles)
        else:
            if elapsed >= self.cruise_seconds:
                self._in_spike = True
                self._phase_t0 = now
                mode = self._current_mode()
                if mode == "dtc":
                    self._pending_dtcs.append("P0128")

    def _cruise_sensors(self, now: float) -> dict[str, float]:
        t = now - self._t0
        speed = 55.0 + 12.0 * math.sin(t / 18.0) + _noise(2.5)
        speed = _clamp(speed, 0, 120)
        rpm = 1800.0 + (speed * 18.0) + _noise(80)
        throttle = _clamp(20.0 + speed * 0.35 + _noise(3), 5, 90)
        fuel = _clamp(self.fuel_level_pct + _noise(0.05), 5, 100)

        return {
            "vehicle_speed": speed,
            "vehicle_speed_obd": speed + _noise(0.8),
            "engine_rpm": rpm,
            "coolant_temperature": 90.0 + 2.0 * math.sin(t / 40.0) + _noise(0.4),
            "fuel_level": fuel,
            "fuel_level_liters": fuel * 0.55,
            "fuel_consumed": self.fuel_consumed_l,
            "engine_oil_temperature": 95.0 + _noise(1.5),
            "engine_oil_pressure": 280.0 + _noise(15),
            "engine_oil_level": 78.0 + _noise(1),
            "throttle_position": throttle,
            "odometer": self.odometer_km,
            "engine_hours": self.engine_hours_min,
            "ambient_air_temperature": 31.0 + _noise(0.5),
            "hv_battery_charge": 0.0,
            "battery_voltage": 13.8 + _noise(0.08),
            "tracker_battery_voltage": 4.05 + _noise(0.02),
            "vehicle_battery_voltage": 13.7 + _noise(0.08),
            "gsm_signal": float(int(_clamp(4 + _noise(0.6), 2, 5))),
            "distance_until_service": self.distance_until_service,
            "remaining_distance": self.remaining_distance + _noise(2),
            "dtc_count": 0.0,
        }

    def _drift_gps(self, speed_kmh: float) -> None:
        # ~ meters per publish at 2s interval approximated via speed
        dt_h = 2.0 / 3600.0
        dist_km = max(0.0, speed_kmh) * dt_h
        self.heading = (self.heading + _noise(4)) % 360
        rad = math.radians(self.heading)
        # rough deg conversion near equator
        self.lat += (dist_km / 111.0) * math.cos(rad)
        self.lon += (dist_km / (111.0 * math.cos(math.radians(self.lat)))) * math.sin(rad)

    def _accumulate(self, speed_kmh: float, rpm: float) -> None:
        dt_h = 2.0 / 3600.0
        dist = max(0.0, speed_kmh) * dt_h
        self.odometer_km += dist
        self.distance_until_service = max(0.0, self.distance_until_service - dist)
        self.remaining_distance = max(0.0, self.remaining_distance - dist * 0.3)
        if rpm > 500:
            self.engine_hours_min += 2.0 / 60.0
            burn = 0.002 + (rpm / 1e6)
            self.fuel_consumed_l += burn
            self.fuel_level_pct = max(5.0, self.fuel_level_pct - burn * 0.08)

    def _drain_dtcs(self, mode: str) -> list[dict[str, Any]]:
        if mode != "dtc" or not self._pending_dtcs:
            return []
        codes = list(self._pending_dtcs)
        self._pending_dtcs.clear()
        ts = datetime.now(timezone.utc).isoformat()
        return [
            {
                "timestamp": ts,
                "imei": self.imei,
                "dtc_code": code,
                "description": "Simulated thermostat / coolant fault",
                "severity": "warning",
            }
            for code in codes
        ]

    @property
    def mode_label(self) -> str:
        return self._current_mode()
