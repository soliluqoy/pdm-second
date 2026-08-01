"""
PREDICT — Bridge payload-mapping tests (FMC001 OBD + FMC150 CAN profiles).

Validates record_to_payload() against golden Codec 8E frames: AVL IDs from
each model's avl_map.<model>.json land in the JSON contract the backend
consumes, including ASCII decoding of the variable-length X group (VIN,
comma-separated fault codes). Both models must normalize into the SAME
sensor_type strings so rules/dashboard stay device-agnostic.
No hardware and no MQTT broker needed (record_to_payload is a pure function).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))         # tests/ (frame builders)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # bridge/ (codec8e, fmc_bridge)

from codec8e import parse_avl_packet  # noqa: E402
from fmc_bridge import IO_MAPS, parse_device_registry, record_to_payload  # noqa: E402
from test_codec8e import TS_MS, build_packet, build_record  # noqa: E402

IMEI = "867648042983435"
IMEI_CAN = "350424061234001"


def _payload_for(record, model="fmc001", imei=IMEI):
    """Returns (telemetry, dtcs) for backward-compatible assertions."""
    records, _ = parse_avl_packet(build_packet([record]))
    payload, dtcs, _events = record_to_payload(imei, records[0], IO_MAPS[model], model)
    return payload, dtcs


def _full_for(record, model="fmc001", imei=IMEI):
    records, _ = parse_avl_packet(build_packet([record]))
    return record_to_payload(imei, records[0], IO_MAPS[model], model)


# ── Device registry parsing ───────────────────────────────────────────────────
def test_device_registry_parses_imei_model_pairs():
    devices = parse_device_registry(f"{IMEI}:fmc001, {IMEI_CAN}:FMC150")
    assert devices == {IMEI: "fmc001", IMEI_CAN: "fmc150"}


def test_device_registry_bare_imei_gets_default_model():
    devices = parse_device_registry(IMEI)
    assert devices == {IMEI: "fmc001"}


def test_device_registry_empty():
    assert parse_device_registry("") == {}
    assert parse_device_registry(" , ,") == {}


# ── FMC001 (OBD-II IDs) ───────────────────────────────────────────────────────
def test_fmc001_obd_ids_mapped_and_scaled():
    payload, dtcs = _payload_for(build_record(
        TS_MS,
        io_1b={239: 1, 48: 63, 32: 91, 41: 18},
        io_2b={36: 2400, 51: 14200, 60: 458},
    ))
    assert payload["imei"] == IMEI
    assert payload["ignition"] is True
    assert payload["sensors"]["fuel_level"]["value"] == 63            # AVL 48 (FMC001)
    assert payload["sensors"]["coolant_temperature"]["value"] == 91   # AVL 32
    assert payload["sensors"]["throttle_position"]["value"] == 18     # AVL 41
    assert payload["sensors"]["engine_rpm"]["value"] == 2400          # AVL 36
    assert payload["sensors"]["control_module_voltage"]["value"] == pytest.approx(14.2)  # 51, x0.001
    assert payload["sensors"]["fuel_rate"]["value"] == pytest.approx(4.58)               # 60, x0.01
    assert dtcs == []


def test_fmc001_ascii_fault_codes_split_into_individual_dtcs():
    _, dtcs = _payload_for(build_record(TS_MS, io_xb={281: b"P0128,P0300"}))
    assert dtcs == ["P0128", "P0300"]


def test_fmc001_ascii_fault_codes_tolerate_padding():
    _, dtcs = _payload_for(build_record(TS_MS, io_xb={281: b"\x00P0420 \x00"}))
    assert dtcs == ["P0420"]


def test_fmc001_ascii_vin_becomes_meta_field_not_sensor():
    payload, _ = _payload_for(build_record(TS_MS, io_xb={256: b"WVWZZZ1JZXW000001"}))
    assert payload["vin"] == "WVWZZZ1JZXW000001"
    assert "vin" not in payload["sensors"]


def test_fmc001_ascii_entries_are_only_vin_and_dtc():
    ascii_ids = {avl_id for avl_id, e in IO_MAPS["fmc001"].items() if e.get("encoding") == "ascii"}
    assert ascii_ids == {256, 281}  # only VIN + fault codes decode as ASCII


def test_unmapped_id_ignored_in_payload():
    payload, _ = _payload_for(build_record(TS_MS, io_1b={200: 1}))  # sleep mode: not mapped
    assert payload["sensors"] == {}
    assert payload["ignition"] is None  # unknown until AVL 239 arrives


# ── FMC150 (CAN IDs) ──────────────────────────────────────────────────────────
def test_fmc150_can_ids_mapped_and_scaled():
    payload, dtcs = _payload_for(build_record(
        TS_MS,
        io_1b={239: 1, 89: 63, 82: 18, 81: 88},
        io_2b={85: 2400, 115: 910},
        io_4b={87: 12345678},
    ), model="fmc150", imei=IMEI_CAN)
    assert payload["imei"] == IMEI_CAN
    assert payload["ignition"] is True
    assert payload["sensors"]["fuel_level"]["value"] == 63                  # AVL 89 (FMC150)
    assert payload["sensors"]["throttle_position"]["value"] == 18           # AVL 82
    assert payload["sensors"]["vehicle_speed_obd"]["value"] == 88           # AVL 81 (CAN speed)
    assert payload["sensors"]["engine_rpm"]["value"] == 2400                # AVL 85
    assert payload["sensors"]["coolant_temperature"]["value"] == pytest.approx(91.0)  # 115, x0.1
    assert payload["sensors"]["odometer"]["value"] == pytest.approx(12345.678)        # 87, m→km
    assert dtcs == []


def test_fmc150_normalizes_to_same_sensor_types_as_fmc001():
    """The device-agnostic contract: identical quantity → identical sensor_type."""
    fmc001_payload, _ = _payload_for(build_record(
        TS_MS, io_1b={48: 63, 32: 91}, io_2b={36: 2400}))
    fmc150_payload, _ = _payload_for(build_record(
        TS_MS, io_1b={89: 63}, io_2b={85: 2400, 115: 910}), model="fmc150", imei=IMEI_CAN)
    for sensor_type in ("engine_rpm", "coolant_temperature", "fuel_level"):
        assert sensor_type in fmc001_payload["sensors"]
        assert sensor_type in fmc150_payload["sensors"]


def test_fmc150_gnss_odometer_id_16_is_deliberately_unmapped():
    # 87 (true CAN mileage) owns the 'odometer' sensor_type; 16 must not collide.
    payload, _ = _payload_for(build_record(TS_MS, io_4b={16: 80234567}),
                              model="fmc150", imei=IMEI_CAN)
    assert "odometer" not in payload["sensors"]


def test_fmc150_ascii_fault_codes_split_into_individual_dtcs():
    _, dtcs = _payload_for(build_record(TS_MS, io_xb={282: b"P0128,P0300"}),
                           model="fmc150", imei=IMEI_CAN)
    assert dtcs == ["P0128", "P0300"]


def test_fmc150_ascii_vin_becomes_meta_field_not_sensor():
    payload, _ = _payload_for(build_record(TS_MS, io_xb={325: b"WVWZZZ1JZXW000001"}),
                              model="fmc150", imei=IMEI_CAN)
    assert payload["vin"] == "WVWZZZ1JZXW000001"
    assert "vin" not in payload["sensors"]


def test_fmc150_ascii_entries_are_only_vin_and_dtc():
    ascii_ids = {avl_id for avl_id, e in IO_MAPS["fmc150"].items() if e.get("encoding") == "ascii"}
    assert ascii_ids == {325, 282}  # only VIN + fault codes decode as ASCII


def test_fmc150_record_does_not_pick_up_fmc001_ids():
    # 36 is RPM on the FMC001 but undefined on the FMC150 — must stay unmapped.
    payload, _ = _payload_for(build_record(TS_MS, io_2b={36: 2400}),
                              model="fmc150", imei=IMEI_CAN)
    assert payload["sensors"] == {}


# ── Eco-driving / overspeeding events (AVL 253/254/255) ───────────────────────
def test_green_driving_emits_harsh_brake_event():
    payload, dtcs, events = _full_for(build_record(
        TS_MS, io_1b={253: 2, 254: 42},
    ))
    assert dtcs == []
    assert len(events) == 1
    assert events[0]["event_type"] == "harsh_brake"
    assert events[0]["value"] == 42
    assert events[0]["source"] == "device"
    assert events[0]["imei"] == IMEI
    assert "green_driving_type" not in payload["sensors"]


def test_overspeeding_emits_speeding_event():
    _, _, events = _full_for(build_record(TS_MS, io_1b={255: 130}))
    assert len(events) == 1
    assert events[0]["event_type"] == "speeding"
    assert events[0]["value"] == 130


def test_movement_meta_forwarded_on_payload():
    payload, _ = _payload_for(build_record(TS_MS, io_1b={240: 1}))
    assert payload["movement"] is True
