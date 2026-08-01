"""Unit tests for baseline / anomaly helpers."""
from app.services.baselines import (
    BASELINE_SENSORS,
    WINDOW,
    Z_SCORE_THRESHOLD,
    _anomaly_key,
)


def test_baseline_sensor_set():
    assert "battery_voltage" in BASELINE_SENSORS
    assert "coolant_temperature" in BASELINE_SENSORS
    assert "fuel_consumed" in BASELINE_SENSORS


def test_z_score_threshold():
    assert Z_SCORE_THRESHOLD == 3.0
    assert WINDOW == "30d"


def test_anomaly_dedupe_key():
    assert _anomaly_key(1, "battery_voltage", "zscore") == "anomaly:1:battery_voltage:zscore"
