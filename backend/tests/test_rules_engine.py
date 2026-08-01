"""Unit tests for rule-engine helpers (no DB / Redis required)."""
from app.rules.engine import (
    EQUALITY_EPSILON,
    OPERATORS,
    SCHEDULED_SENSOR_TYPES,
    _condition_met,
    _extract_value,
    _rule_applies_to_vehicle,
)


class _FakeRule:
    def __init__(self, vehicle_id=None):
        self.vehicle_id = vehicle_id


def test_extract_value_nested_and_plain():
    assert _extract_value({"value": 42.5, "unit": "°C"}) == 42.5
    assert _extract_value(99) == 99.0
    assert _extract_value(None) is None
    assert _extract_value({"value": None}) is None
    assert _extract_value({"value": "not-a-number"}) is None


def test_operators():
    assert _condition_met(110, ">", 100) is True
    assert _condition_met(100, ">", 100) is False
    assert _condition_met(11.4, "<", 11.5) is True
    assert _condition_met(12.0, "==", 12.0) is True
    # Float equality uses a tolerance — exact binary equality would fail.
    assert _condition_met(1.0 + EQUALITY_EPSILON / 2, "==", 1.0) is True
    assert _condition_met(1.0 + EQUALITY_EPSILON * 10, "==", 1.0) is False
    assert _condition_met(1, "!=", 1) is False  # unknown operator


def test_operators_cover_expected_set():
    assert set(OPERATORS) == {">", "<", ">=", "<=", "=="}


def test_rule_vehicle_scope():
    assert _rule_applies_to_vehicle(_FakeRule(None), 7) is True
    assert _rule_applies_to_vehicle(_FakeRule(7), 7) is True
    assert _rule_applies_to_vehicle(_FakeRule(7), 8) is False


def test_scheduled_sensor_types():
    assert "odometer" in SCHEDULED_SENSOR_TYPES
    assert "engine_hours" in SCHEDULED_SENSOR_TYPES
