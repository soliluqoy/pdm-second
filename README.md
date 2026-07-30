# PREDICT — Predictive Maintenance CMSS

> **Sensor data → Rule engine → Work orders → Technician feedback loop**

A focused Predictive Maintenance (PdM) Computerized Maintenance Management System (CMMS) that automates the transition from "data anomaly" to "technician task." Built as a local-first PoC with a clean integration seam for the **Teltonika FMC150** telematics gateway.

## How to Run in Your Browser (Complete Guide)

### Prerequisites

- **Docker Desktop** installed and running (includes Docker Compose v2)
  - Windows/Mac: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  - Linux: `docker` + `docker compose` plugin
- ~2 GB free RAM for the containers
- Ports `5173`, `8000`, `5432`, `6379`, `1883`, and `9001` free on your machine

### Step 1 — Create the environment file

```bash
# Linux / macOS / Git Bash
cp .env.example .env

# Windows (cmd.exe)
copy .env.example .env
```

> The defaults in `.env.example` work out of the box — no changes needed for a local run.

### Step 2 — Build and start the full stack

```bash
docker compose up --build
```

This starts **6 services**: `mosquitto` (MQTT broker), `postgres` (TimescaleDB), `redis`, `backend` (FastAPI), `simulator` (FMC150 emulator), and `frontend` (React/Vite). First build takes a few minutes.

On startup the backend automatically:

1. Creates all database tables and enables the TimescaleDB extension
2. Converts `sensor_readings` into a time-series hypertable
3. Seeds a demo fleet — **1 fleet, 5 vehicles** (Truck-001 … Van-005), each with 5 components and 12 sensors, plus 6 work-order templates, 12 rules, and 4 users
4. Connects the MQTT ingestion service and WebSocket listener

The simulator then begins publishing telemetry for all 5 vehicles **every 10 seconds**, injecting random anomalies (~5% probability per cycle) so the rule engine has alerts and work orders to generate.

### Step 3 — Open the app in your browser

| URL | What you get |
|---|---|
| **http://localhost:5173** | 🖥️ **Main dashboard** (the web app) |
| http://localhost:8000/docs | 📖 Interactive API docs (Swagger UI) |
| http://localhost:8000/health | ❤️ Backend health check (JSON) |

Wait ~30–60 seconds after `docker compose up` for all healthchecks to pass and the first telemetry to arrive, then open **http://localhost:5173**.

### Step 4 — Verify everything is working

1. **Dashboard** (`/`) — you should see 5 vehicles with health indicators (they start GREY and turn GREEN as telemetry flows in). The sidebar shows a pulsing **"Live"** dot when the WebSocket is connected.
2. **Wait for anomalies** — within a few minutes the simulator injects faults (high coolant temp, low battery, DTCs, etc.). Watch the **Alerts** page (`/alerts`) and **Work Orders** page (`/workorders`) fill up automatically.
3. **Close the loop** — on Work Orders, assign one to a technician and mark it complete; the vehicle's maintenance history updates (feedback loop).
4. **Shadow mode** — enabled by default, so auto-generated work orders appear in *shadow* status for review. Toggle it on the **Rules** page or via `POST /api/v1/system/shadow-mode?enabled=false`.

### Stopping, restarting, and resetting

```bash
# Stop all services (data is preserved in Docker volumes)
docker compose down

# Stop AND wipe all data (fresh re-seed on next start)
docker compose down -v

# View logs for one service
docker compose logs -f backend
docker compose logs -f simulator

# Rebuild after code changes
docker compose up --build
```

> **Tip:** backend and frontend source folders are mounted as volumes with hot-reload enabled (uvicorn `--reload` + Vite HMR), so most code edits apply without rebuilding.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard shows "Disconnected" | Check `docker compose logs backend` — backend may still be waiting for DB/MQTT healthchecks |
| No vehicles on dashboard | Check `docker compose logs simulator` — it retries the MQTT connection until the broker is ready |
| Port already in use | Stop the conflicting local service (e.g. local Postgres on 5432) or change the port mapping in `docker-compose.yml` |
| Stale/broken data after changes | `docker compose down -v && docker compose up --build` to reset the database and re-seed |

## Architecture

```
FMC150 Simulator → MQTT (Mosquitto) → FastAPI Backend → PostgreSQL/TimescaleDB + Redis
                                         ↓
                                    React Dashboard (WebSocket real-time)
```

| Service    | Port | Technology                     |
|------------|------|--------------------------------|
| Frontend   | 5173 | React 18 + Vite 6 + Tailwind 3 |
| Backend    | 8000 | FastAPI (Python 3.12)          |
| PostgreSQL | 5432 | TimescaleDB 2.17 (PG 16)       |
| Redis      | 6379 | Redis 7                        |
| Mosquitto  | 1883 | Eclipse Mosquitto 2 (MQTT)     |
| Mosquitto  | 9001 | MQTT over WebSocket (debug)    |
| Simulator  | —    | Python FMC150 emulator         |

## Web App Pages

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | Fleet health summary (Green/Yellow/Red/Grey), live vehicle status |
| `/assets` | Assets | Fleet → Vehicle → Component → Sensor hierarchy |
| `/workorders` | Work Orders | Assign, complete, close, cancel — technician feedback loop |
| `/alerts` | Alerts | Active/acknowledged/resolved alerts from the rule engine |
| `/rules` | Rules | Threshold + DTC rules, work-order templates, shadow-mode toggle |

## Core Modules

1. **Asset Registry** — Fleet → Vehicle → Component → Sensor hierarchy
2. **Data Ingestion** — MQTT subscriber stores telemetry in TimescaleDB, caches latest state in Redis
3. **Rule Engine** — Threshold + DTC rules generate alerts automatically
4. **Work Orders** — Auto-generated from alerts; technician assign/complete closes the loop and writes maintenance history
5. **Dashboard** — Fleet health (Green/Yellow/Red/Grey), live updates via WebSocket + 10s polling

## Teltonika FMC150 Integration

The simulator publishes to `fmc150/{imei}/telemetry` (and `fmc150/{imei}/dtc`) using the same JSON payload structure as the real FMC150. To integrate real hardware:

1. Configure FMC150 MQTT parameters via Teltonika FMC Config Tool
2. Point the device at the Mosquitto broker (add TLS + auth for production)
3. Backend unchanged — same topic, same payload contract

The broker requires authentication (default: `predict_sim` / `predict_sim_pass`, configured in `mosquitto/Dockerfile` and `.env`).

## Shadow Mode

When enabled (default: **on**, `SHADOW_MODE=true`), generated work orders are created in "shadow" status for review rather than triggering real maintenance. Toggle via the Rules page in the UI or the API:

```bash
curl -X POST "http://localhost:8000/api/v1/system/shadow-mode?enabled=false"
```

## API

All REST endpoints are under `/api/v1/` — assets, work orders, alerts, dashboard, rules, and system config. Real-time updates are pushed over WebSocket at `ws://localhost:8000/ws`. See interactive docs at `http://localhost:8000/docs`.

## Project Structure

```
pdm-second/
├── docker-compose.yml   # Full-stack orchestration (6 services)
├── .env.example         # Environment config template
├── backend/             # FastAPI app (REST + WebSocket + MQTT ingestion)
├── simulator/           # FMC150 telematics emulator
├── frontend/            # React + Vite + TypeScript dashboard
└── mosquitto/           # MQTT broker config + Dockerfile
```
