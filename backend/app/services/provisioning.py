"""
PREDICT — Vehicle Provisioning
Catalog-driven provisioning for REAL Teltonika-equipped vehicles.

When a vehicle is registered (POST /api/v1/assets/vehicles/register), its
components and sensors are created from the catalogs below, selected by the
vehicle's device_type:

  - "fmc001" — OBD-II plug-in tracker. OBD-II parameters (engine RPM, coolant
    temp, engine load, fuel level, throttle, intake, oil temp, fuel rate,
    DTCs, distance-until-service) — availability depends on which PIDs the
    car answers. AVL IDs follow the Teltonika wiki "FMC001 Teltonika Data
    Sending Parameters ID" page.
  - "fmc150" — wired CAN tracker. CAN parameters (RPM, coolant, fuel, true
    mileage, engine hours, oil pressure/level/temp, DTCs, service distance)
    — availability depends on the vehicle being on Teltonika's CAN
    compatibility list and the correct CAN program number. AVL IDs follow
    the wiki "FMC150 Teltonika Data Sending Parameters ID" page.

Both catalogs share the Teltonika standard AVL parameters (ignition, movement,
GSM signal, external/battery voltage, GNSS speed) — those work on ANY vehicle
— and use IDENTICAL sensor_type strings for identical physical quantities, so
rules and the dashboard stay device-agnostic.

Keep AVL IDs in sync with bridge/avl_map.<model>.json.

Sensors NOT included (no standard OBD-II/CAN source): tire pressure, brake
pressure, transmission temperature. Add them later via
POST /api/v1/assets/sensors if you install dedicated hardware — the matching
rules simply stay dormant until data arrives.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Component, Sensor, Vehicle

logger = logging.getLogger("predict.provisioning")

# ── Component catalog (per vehicle, same for both device types) ───────────────
COMPONENT_CATALOG = [
    {"name": "Engine", "component_type": "engine", "description": "Main engine system"},
    {"name": "Electrical", "component_type": "electrical", "description": "Battery, alternator, tracker power"},
    {"name": "Connectivity", "component_type": "connectivity", "description": "Tracker link health"},
    {"name": "Maintenance", "component_type": "maintenance", "description": "Service schedule and fault tracking"},
]

# ── Shared sensors — Teltonika standard AVL IDs, delivered by BOTH models ─────
SHARED_SENSOR_CATALOG = [
    {"component": "Engine", "name": "Vehicle Speed", "sensor_type": "vehicle_speed", "unit": "km/h",
     "io_element_id": 24, "min_value": 0, "max_value": 200, "warning_threshold": 150, "critical_threshold": 180},
    {"component": "Electrical", "name": "Battery Voltage", "sensor_type": "battery_voltage", "unit": "V",
     "io_element_id": 66, "min_value": 0, "max_value": 15, "warning_threshold": 12.5, "critical_threshold": 11.5},
    {"component": "Electrical", "name": "Tracker Battery Voltage", "sensor_type": "tracker_battery_voltage", "unit": "V",
     "io_element_id": 67, "min_value": 0, "max_value": 5, "warning_threshold": 3.6, "critical_threshold": 3.3},
    {"component": "Connectivity", "name": "GSM Signal", "sensor_type": "gsm_signal", "unit": "1-5",
     "io_element_id": 21, "min_value": 0, "max_value": 5, "warning_threshold": None, "critical_threshold": None},
]

# ── FMC001 sensors — OBD-II PIDs (sync with bridge/avl_map.fmc001.json) ───────
FMC001_SENSOR_CATALOG = [
    # Engine (OBD-II PIDs — availability depends on the car)
    {"component": "Engine", "name": "Engine RPM", "sensor_type": "engine_rpm", "unit": "RPM",
     "io_element_id": 36, "min_value": 0, "max_value": 6000, "warning_threshold": 4500, "critical_threshold": 5500},
    {"component": "Engine", "name": "Coolant Temperature", "sensor_type": "coolant_temperature", "unit": "°C",
     "io_element_id": 32, "min_value": 0, "max_value": 130, "warning_threshold": 100, "critical_threshold": 110},
    {"component": "Engine", "name": "Engine Load", "sensor_type": "engine_load", "unit": "%",
     "io_element_id": 31, "min_value": 0, "max_value": 100, "warning_threshold": 80, "critical_threshold": 95},
    {"component": "Engine", "name": "Fuel Level", "sensor_type": "fuel_level", "unit": "%",
     "io_element_id": 48, "min_value": 0, "max_value": 100, "warning_threshold": 20, "critical_threshold": 10},
    {"component": "Engine", "name": "Fuel Rate", "sensor_type": "fuel_rate", "unit": "L/h",
     "io_element_id": 60, "min_value": 0, "max_value": 30, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Engine Oil Temperature", "sensor_type": "engine_oil_temperature", "unit": "°C",
     "io_element_id": 58, "min_value": 0, "max_value": 150, "warning_threshold": 120, "critical_threshold": 130},
    {"component": "Engine", "name": "Throttle Position", "sensor_type": "throttle_position", "unit": "%",
     "io_element_id": 41, "min_value": 0, "max_value": 100, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Intake Air Temperature", "sensor_type": "intake_air_temperature", "unit": "°C",
     "io_element_id": 39, "min_value": -40, "max_value": 100, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Intake Manifold Pressure", "sensor_type": "intake_map", "unit": "kPa",
     "io_element_id": 35, "min_value": 0, "max_value": 255, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Vehicle Speed (OBD)", "sensor_type": "vehicle_speed_obd", "unit": "km/h",
     "io_element_id": 37, "min_value": 0, "max_value": 200, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Odometer", "sensor_type": "odometer", "unit": "km",
     "io_element_id": 16, "min_value": 0, "max_value": 1000000, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Runtime Since Engine Start", "sensor_type": "engine_runtime", "unit": "s",
     "io_element_id": 42, "min_value": 0, "max_value": 65535, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Ambient Air Temperature", "sensor_type": "ambient_air_temperature", "unit": "°C",
     "io_element_id": 53, "min_value": -40, "max_value": 60, "warning_threshold": None, "critical_threshold": None},
    # Electrical
    {"component": "Electrical", "name": "Control Module Voltage", "sensor_type": "control_module_voltage", "unit": "V",
     "io_element_id": 51, "min_value": 0, "max_value": 15, "warning_threshold": 12.0, "critical_threshold": 11.5},
    # Maintenance (service countdown + fault tracking)
    {"component": "Maintenance", "name": "Distance Until Service", "sensor_type": "distance_until_service", "unit": "km",
     "io_element_id": 402, "min_value": 0, "max_value": 100000, "warning_threshold": 1000, "critical_threshold": 100},
    {"component": "Maintenance", "name": "DTC Count", "sensor_type": "dtc_count", "unit": "",
     "io_element_id": 30, "min_value": 0, "max_value": 20, "warning_threshold": 1, "critical_threshold": 3},
    {"component": "Maintenance", "name": "Distance Traveled MIL On", "sensor_type": "mil_on_distance", "unit": "km",
     "io_element_id": 43, "min_value": 0, "max_value": 65535, "warning_threshold": None, "critical_threshold": None},
    {"component": "Maintenance", "name": "Distance Since Codes Cleared", "sensor_type": "codes_cleared_distance", "unit": "km",
     "io_element_id": 49, "min_value": 0, "max_value": 65535, "warning_threshold": None, "critical_threshold": None},
]

# ── FMC150 sensors — CAN bus (sync with bridge/avl_map.fmc150.json) ───────────
# Same sensor_type strings as the FMC001 catalog wherever the quantity matches.
FMC150_SENSOR_CATALOG = [
    # Engine (CAN — only if the car is on Teltonika's compatibility list)
    {"component": "Engine", "name": "Engine RPM", "sensor_type": "engine_rpm", "unit": "RPM",
     "io_element_id": 85, "min_value": 0, "max_value": 6000, "warning_threshold": 4500, "critical_threshold": 5500},
    {"component": "Engine", "name": "Coolant Temperature", "sensor_type": "coolant_temperature", "unit": "°C",
     "io_element_id": 115, "min_value": 0, "max_value": 130, "warning_threshold": 100, "critical_threshold": 110},
    {"component": "Engine", "name": "Fuel Level", "sensor_type": "fuel_level", "unit": "%",
     "io_element_id": 89, "min_value": 0, "max_value": 100, "warning_threshold": 20, "critical_threshold": 10},
    {"component": "Engine", "name": "Fuel Level (liters)", "sensor_type": "fuel_level_liters", "unit": "l",
     "io_element_id": 84, "min_value": 0, "max_value": 200, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Fuel Consumed (total)", "sensor_type": "fuel_consumed", "unit": "l",
     "io_element_id": 83, "min_value": 0, "max_value": 100000, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Engine Oil Temperature", "sensor_type": "engine_oil_temperature", "unit": "°C",
     "io_element_id": 1270, "min_value": 0, "max_value": 150, "warning_threshold": 120, "critical_threshold": 130},
    {"component": "Engine", "name": "Engine Oil Pressure", "sensor_type": "engine_oil_pressure", "unit": "kPa",
     "io_element_id": 1158, "min_value": 0, "max_value": 1000, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Engine Oil Level", "sensor_type": "engine_oil_level", "unit": "%",
     "io_element_id": 1159, "min_value": 0, "max_value": 100, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Throttle Position", "sensor_type": "throttle_position", "unit": "%",
     "io_element_id": 82, "min_value": 0, "max_value": 100, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Vehicle Speed (CAN)", "sensor_type": "vehicle_speed_obd", "unit": "km/h",
     "io_element_id": 81, "min_value": 0, "max_value": 200, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Odometer", "sensor_type": "odometer", "unit": "km",
     "io_element_id": 87, "min_value": 0, "max_value": 1000000, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Engine Total Hours", "sensor_type": "engine_hours", "unit": "min",
     "io_element_id": 102, "min_value": 0, "max_value": 16777215, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "Ambient Air Temperature", "sensor_type": "ambient_air_temperature", "unit": "°C",
     "io_element_id": 1396, "min_value": -40, "max_value": 60, "warning_threshold": None, "critical_threshold": None},
    {"component": "Engine", "name": "HV Battery Charge Level", "sensor_type": "hv_battery_charge", "unit": "%",
     "io_element_id": 152, "min_value": 0, "max_value": 100, "warning_threshold": None, "critical_threshold": None},
    # Electrical
    {"component": "Electrical", "name": "Vehicle Battery Voltage (CAN)", "sensor_type": "vehicle_battery_voltage", "unit": "V",
     "io_element_id": 168, "min_value": 0, "max_value": 15, "warning_threshold": 12.0, "critical_threshold": 11.5},
    # Maintenance (service countdown + fault tracking)
    {"component": "Maintenance", "name": "Distance Until Service", "sensor_type": "distance_until_service", "unit": "km",
     "io_element_id": 400, "min_value": 0, "max_value": 100000, "warning_threshold": 1000, "critical_threshold": 100},
    {"component": "Maintenance", "name": "Remaining Distance", "sensor_type": "remaining_distance", "unit": "km",
     "io_element_id": 866, "min_value": 0, "max_value": 2000, "warning_threshold": None, "critical_threshold": None},
    {"component": "Maintenance", "name": "DTC Count", "sensor_type": "dtc_count", "unit": "",
     "io_element_id": 160, "min_value": 0, "max_value": 20, "warning_threshold": 1, "critical_threshold": 3},
]

_MODEL_CATALOGS = {
    "fmc001": FMC001_SENSOR_CATALOG,
    "fmc150": FMC150_SENSOR_CATALOG,
}

# ── Telemetry catalog (for dashboard preview before vehicles are registered) ───
# GPS block is always present on every AVL record from the bridge.
TELEMETRY_GPS_FIELDS = [
    {"field": "latitude", "name": "Latitude", "unit": "°"},
    {"field": "longitude", "name": "Longitude", "unit": "°"},
    {"field": "speed", "name": "GNSS Speed", "unit": "km/h"},
    {"field": "altitude", "name": "Altitude", "unit": "m"},
    {"field": "angle", "name": "Heading", "unit": "°"},
    {"field": "satellites", "name": "Satellites", "unit": ""},
]

# Meta fields mapped in bridge/avl_map.<model>.json (kind "meta" / "dtc").
TELEMETRY_META_BY_MODEL = {
    "fmc001": [
        {"field": "ignition", "name": "Ignition", "io_element_id": 239,
         "note": "Top-level flag — drives GREY→GREEN health"},
        {"field": "movement", "name": "Movement", "io_element_id": 240, "note": "Top-level flag"},
        {"field": "vin", "name": "VIN", "io_element_id": 256,
         "note": "17-char ASCII, top-level payload field"},
        {"field": "dtc", "name": "Fault codes (DTC)", "io_element_id": 281,
         "note": "Published separately to teltonika/{imei}/dtc (one message per code)"},
    ],
    "fmc150": [
        {"field": "ignition", "name": "Ignition", "io_element_id": 239,
         "note": "Top-level flag — drives GREY→GREEN health"},
        {"field": "movement", "name": "Movement", "io_element_id": 240, "note": "Top-level flag"},
        {"field": "vin", "name": "VIN", "io_element_id": 325,
         "note": "17-char ASCII, top-level payload field"},
        {"field": "dtc", "name": "Fault codes (DTC)", "io_element_id": 282,
         "note": "Published separately to teltonika/{imei}/dtc (one message per code)"},
    ],
}

_DEVICE_LABELS = {
    "fmc001": {
        "label": "FMC001",
        "description": "OBD-II plug-in tracker — engine PIDs depend on which PIDs your car answers.",
    },
    "fmc150": {
        "label": "FMC150",
        "description": "Wired CAN tracker — CAN parameters require Teltonika vehicle compatibility and the correct CAN program.",
    },
}


def get_telemetry_catalog() -> dict:
    """Return the full list of telemetry fields we decode and store, per device model."""
    shared_types = {s["sensor_type"] for s in SHARED_SENSOR_CATALOG}
    models = []
    for device_type, model_catalog in _MODEL_CATALOGS.items():
        info = _DEVICE_LABELS[device_type]
        sensors = []
        for s in SHARED_SENSOR_CATALOG + model_catalog:
            source = "standard" if s["sensor_type"] in shared_types else (
                "obd" if device_type == "fmc001" else "can"
            )
            sensors.append({
                "sensor_type": s["sensor_type"],
                "name": s["name"],
                "unit": s.get("unit") or "",
                "component": s["component"],
                "io_element_id": s.get("io_element_id"),
                "source": source,
            })
        models.append({
            "device_type": device_type,
            "label": info["label"],
            "description": info["description"],
            "sensors": sensors,
            "meta": TELEMETRY_META_BY_MODEL[device_type],
            "gps": TELEMETRY_GPS_FIELDS,
        })
    return {
        "models": models,
        "note": (
            "Not every parameter arrives on every vehicle. Teltonika standard fields "
            "(ignition, speed, voltages, GSM) work on any install; OBD/CAN engine "
            "data depends on your car. Unmapped AVL IDs are logged by the bridge "
            "for discovery — see bridge/avl_map.<model>.json."
        ),
    }


async def provision_vehicle(db: AsyncSession, vehicle: Vehicle) -> int:
    """Attach catalog components + sensors to a freshly registered vehicle.

    The sensor catalog is selected by vehicle.device_type (FMC001 OBD-II vs
    FMC150 CAN). Returns the number of sensors created. Idempotent per vehicle:
    callers must only invoke this on a NEW vehicle (registration enforces IMEI
    uniqueness).
    """
    device_type = getattr(vehicle, "device_type", None) or "fmc001"
    model_catalog = _MODEL_CATALOGS.get(device_type)
    if model_catalog is None:
        logger.warning("Unknown device_type %r for vehicle %s — falling back to fmc001 catalog",
                       device_type, vehicle.id)
        model_catalog = FMC001_SENSOR_CATALOG

    comp_map: dict[str, Component] = {}
    for cdata in COMPONENT_CATALOG:
        comp = Component(vehicle_id=vehicle.id, **cdata)
        db.add(comp)
        comp_map[comp.name] = comp
    await db.flush()

    count = 0
    for sdata in SHARED_SENSOR_CATALOG + model_catalog:
        comp = comp_map.get(sdata["component"])
        if comp is None:
            continue
        sensor_kwargs = {k: v for k, v in sdata.items() if k != "component"}
        db.add(Sensor(component_id=comp.id, **sensor_kwargs))
        count += 1
    await db.flush()

    logger.info("Provisioned vehicle %s (IMEI %s, %s): %d components, %d sensors",
                vehicle.name, vehicle.imei, device_type, len(comp_map), count)
    return count
