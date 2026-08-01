# External FMC150 Vehicle Simulator

Standalone tool (not part of the PREDICT product stack). It registers **one** FMC150 vehicle and publishes MQTT telemetry so you can exercise Live telemetry, sensor history graphs, alerts, and work orders **without** a real tracker.

It is **not** wired into `docker-compose` and does not modify backend/frontend/bridge code.

## Prerequisites

1. PREDICT stack running (`docker compose up` from the repo root)
2. Mosquitto reachable at `localhost:1883` (defaults match `.env.example`)
3. Backend at `http://localhost:8000`
4. Python 3.10+

## Enable / disable

| Action | How |
|--------|-----|
| **Enable** | `enabled: true` in `config.yaml`, then run the simulator |
| **Disable** | `Ctrl+C` (stops publishing) **or** set `enabled: false` and exit |
| After stop | Vehicle stays registered; dashboard shows it offline/GREY after the offline watchdog (~5 min) |

There is no toggle in the main app UI — keep this tool out of product code.

## Quick start (Windows)

```powershell
cd simulator
.\start.ps1
```

Or manually:

```powershell
cd simulator
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python run.py
```

Then open **http://localhost:5173/** — you should see **Sim FMC150** under Live telemetry with updating sensor tiles. Click a sensor for history graphs.

## What it does

1. `POST /api/v1/assets/vehicles/register` for IMEI `999150000000001` (`fmc150`) if missing  
2. Publishes every ~2s to `teltonika/{imei}/telemetry` (same JSON contract as the bridge)  
3. Rotates through **cruise** (healthy drift) and **spike** profiles so seed rules can fire:

| Profile | Effect |
|---------|--------|
| `overheat` | Coolant / oil temperature above warning/critical |
| `high_rpm` | Engine RPM spike |
| `low_fuel` | Fuel % into warning/critical band |
| `low_battery` | Battery voltages near 11.2 V |
| `service_due` | Distance until service low |
| `dtc` | DTC count + `P0128` on `teltonika/{imei}/dtc` |

Timing is controlled in `config.yaml` under `spikes` (`cruise_seconds`, `spike_seconds`, `profiles`).

## Config

Edit [`config.yaml`](config.yaml):

- `enabled` — master switch  
- `vehicle.*` — IMEI, name, plate, VIN  
- `api.base_url` / `mqtt.*` — point at your stack  
- `publish.interval_seconds` — publish rate  
- `spikes.enabled: false` — healthy cruise only (no threshold events)

## Cleanup

Stop the simulator, then optionally delete the vehicle from **Assets** in the UI, or leave it registered for the next run (re-register is a no-op on the same IMEI).
