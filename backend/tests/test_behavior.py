"""Unit tests for driving-behavior helpers (no DB / Redis required)."""
from datetime import datetime, timezone

from app.db.models import DrivingEventType, RuleType
from app.rules.engine import BEHAVIOR_EVENT_TYPES
from app.services.behavior import (
    SPEED_NEAR_ZERO,
    _extract_value,
    _parse_bool,
    _sensor_fuel,
    _sensor_speed,
)


def test_behavior_event_types_cover_enum():
    assert set(BEHAVIOR_EVENT_TYPES) == {e.value for e in DrivingEventType}


def test_rule_type_includes_behavior_and_anomaly():
    assert RuleType.BEHAVIOR.value == "behavior"
    assert RuleType.ANOMALY.value == "anomaly"


def test_extract_value():
    assert _extract_value({"value": 80}) == 80.0
    assert _extract_value(12.5) == 12.5
    assert _extract_value(None) is None


def test_sensor_speed_prefers_obd_then_gnss_sensor_then_gps():
    assert _sensor_speed({"vehicle_speed_obd": {"value": 55}}, {"speed": 40}) == 55.0
    assert _sensor_speed({"vehicle_speed": {"value": 48}}, {"speed": 40}) == 48.0
    assert _sensor_speed({}, {"speed": 40}) == 40.0
    assert _sensor_speed({}, {}) is None


def test_sensor_fuel_prefers_consumed():
    assert _sensor_fuel({
        "fuel_consumed": {"value": 120.5},
        "fuel_level": {"value": 40},
    }) == 120.5
    assert _sensor_fuel({"fuel_level": {"value": 40}}) == 40.0


def test_parse_bool():
    assert _parse_bool(1) is True
    assert _parse_bool(0) is False
    assert _parse_bool(True) is True
    assert _parse_bool(None) is None


def test_harsh_accel_threshold_math():
    """Δspeed/Δt at 10s sampling: 40→80 km/h ≈ 1.11 m/s² (below 3)."""
    prev, cur, dt = 40.0, 80.0, 10.0
    accel = ((cur - prev) * (1000.0 / 3600.0)) / dt
    assert accel < 3.0
    # 0→120 km/h in 10s ≈ 3.33 m/s²
    accel2 = ((120.0 - 0.0) * (1000.0 / 3600.0)) / 10.0
    assert accel2 > 3.0


def test_idle_near_zero_constant():
    assert SPEED_NEAR_ZERO == 3.0
    assert datetime.now(timezone.utc).tzinfo is not None
