"""Unit test for Redis live-state merge logic (no Redis required)."""
import json


def merge_state(existing: dict | None, state: dict) -> dict:
    """Mirror of redis_client.merge_vehicle_state's pure merge step."""
    merged = dict(existing or {})
    new_sensors = state.pop("sensors", {}) or {}
    old_sensors = merged.get("sensors") or {}
    ts = state.get("timestamp")
    for sensor_type, reading in new_sensors.items():
        if isinstance(reading, dict):
            reading = {**reading, "timestamp": ts}
        else:
            reading = {"value": reading, "unit": None, "timestamp": ts}
        old_sensors[sensor_type] = reading
    for k, v in state.items():
        if v is not None or k not in merged:
            merged[k] = v
    merged["sensors"] = old_sensors
    return merged


def test_partial_record_keeps_previous_sensors():
    existing = {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "ignition": True,
        "sensors": {
            "coolant_temperature": {"value": 90, "unit": "°C", "timestamp": "2026-01-01T00:00:00+00:00"},
            "engine_rpm": {"value": 2000, "unit": "RPM", "timestamp": "2026-01-01T00:00:00+00:00"},
        },
    }
    # Next AVL record only carries RPM (coolant omitted — common on Teltonika).
    partial = {
        "timestamp": "2026-01-01T00:00:10+00:00",
        "ignition": True,
        "sensors": {
            "engine_rpm": {"value": 2100, "unit": "RPM"},
        },
    }
    merged = merge_state(existing, dict(partial))
    assert merged["sensors"]["engine_rpm"]["value"] == 2100
    assert merged["sensors"]["coolant_temperature"]["value"] == 90
    assert merged["sensors"]["engine_rpm"]["timestamp"] == "2026-01-01T00:00:10+00:00"
    # Coolant keeps its own (older) timestamp so the dashboard can age it out.
    assert merged["sensors"]["coolant_temperature"]["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_none_ignition_does_not_clobber():
    existing = {"ignition": True, "sensors": {}}
    partial = {"timestamp": "t", "ignition": None, "sensors": {}}
    merged = merge_state(existing, dict(partial))
    assert merged["ignition"] is True


def test_roundtrip_json_safe():
    merged = merge_state(None, {
        "timestamp": "t",
        "sensors": {"fuel_level": {"value": 50, "unit": "%"}},
    })
    # Must survive a Redis set/get round-trip.
    restored = json.loads(json.dumps(merged))
    assert restored["sensors"]["fuel_level"]["value"] == 50
