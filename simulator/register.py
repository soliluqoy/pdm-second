"""Ensure the simulated FMC150 vehicle exists in PREDICT (register if missing)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("simulator.register")


def ensure_vehicle(api_base: str, vehicle_cfg: dict[str, Any]) -> dict[str, Any]:
    """POST /api/v1/assets/vehicles/register, or return existing vehicle on 409."""
    imei = str(vehicle_cfg["imei"])
    base = api_base.rstrip("/")
    payload = {
        "name": vehicle_cfg.get("name", "Sim FMC150"),
        "license_plate": vehicle_cfg.get("license_plate"),
        "make": vehicle_cfg.get("make"),
        "model": vehicle_cfg.get("model"),
        "year": vehicle_cfg.get("year"),
        "vin": vehicle_cfg.get("vin"),
        "imei": imei,
        "device_type": vehicle_cfg.get("device_type", "fmc150"),
        "is_active": True,
    }

    with httpx.Client(timeout=15.0) as client:
        r = client.post(f"{base}/api/v1/assets/vehicles/register", json=payload)
        if r.status_code == 201:
            data = r.json()
            logger.info(
                "Registered vehicle id=%s name=%r imei=%s device_type=%s",
                data.get("id"),
                data.get("name"),
                imei,
                data.get("device_type"),
            )
            return data

        if r.status_code == 409:
            existing = _find_by_imei(client, base, imei)
            if existing:
                logger.info(
                    "Vehicle already registered id=%s name=%r imei=%s",
                    existing.get("id"),
                    existing.get("name"),
                    imei,
                )
                return existing
            raise RuntimeError(
                f"IMEI {imei} already exists but was not found in vehicle list"
            )

        r.raise_for_status()
        return r.json()


def _find_by_imei(client: httpx.Client, base: str, imei: str) -> dict[str, Any] | None:
    r = client.get(f"{base}/api/v1/assets/vehicles")
    r.raise_for_status()
    for v in r.json():
        if v.get("imei") == imei:
            return v
    return None
