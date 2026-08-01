# PREDICT — Predictive Maintenance CMSS

> **Real car sensor data → Rule engine → Work orders → Technician feedback loop**

A Predictive Maintenance (PdM) CMMS that automates the transition from "data
anomaly" to "technician task." Driven by **real Teltonika trackers** — the
**FMC001** (OBD-II plug-in) and/or the **FMC150** (wired CAN) — in your
vehicles. No simulator, no seed data.

**🚗 Connecting a car? Read [FMC001-SETUP.md](FMC001-SETUP.md)** — the exact
checklist of information you need (IMEI, public endpoint, Codec 8 Extended,
Duplicate-mode second server) and where each piece gets plugged in.
*(Wired FMC150 CAN tracker instead? See [FMC150-SETUP.md](FMC150-SETUP.md).)*

## Architecture

```
Car OBD-II port → FMC001 ┐
                          ├→ 4G LTE → <VPS_STATIC_IP>:5123 → fmc-bridge (Codec 8E decode)
Car CAN bus ───→ FMC150 ┘                                    ↓
                              MQTT (Mosquitto) → FastAPI Backend → PostgreSQL/TimescaleDB + Redis
                                                       ↓
                                          React Dashboard (WebSocket real-time)
```

| Service    | Port | Technology                            |
|------------|------|---------------------------------------|
| Frontend   | 5173 | React 18 + Vite 6 + Tailwind 3        |
| Backend    | 8000 | FastAPI (Python 3.12)                 |
| Bridge     | 5123 | Teltonika AVL (Codec 8/8E) TCP → MQTT |
| PostgreSQL | 5432 | TimescaleDB 2.17 (PG 16)              |
| Redis      | 6379 | Redis 7                               |
| Mosquitto  | 1883 | Eclipse Mosquitto 2 (MQTT)            |
| Mosquitto  | 9001 | MQTT over WebSocket (debug)           |

## Quick Start

### Prerequisites

- **Docker Desktop** running (Compose v2), ~2 GB free RAM
- Ports `5173`, `8000`, `5432`, `6379`, `1883`, `9001`, `5123` free
- A **public TCP endpoint** for the trackers to reach the bridge — ideally a
  **VPS with a static IP** (see "Hosting on a VPS" below; any always-on host
  with port `5123` open works)
- A **Teltonika FMC001 and/or FMC150** + M2M SIM (see
  [FMC001-SETUP.md](FMC001-SETUP.md) / [FMC150-SETUP.md](FMC150-SETUP.md))

### 1 — Environment file

```bash
copy .env.example .env   # Windows (cp on Linux/macOS)
```

Defaults work out of the box.

### 2 — Start the stack

```bash
docker compose up --build
```

Starts **6 services**: `mosquitto`, `postgres`, `redis`, `backend`, `bridge`,
`frontend`. On startup the backend creates the schema, enables TimescaleDB,
and seeds **operational data only** (users, work-order templates, rules) —
no demo vehicles.

### 3 — Point your tracker at the bridge

The bridge listens on port `5123` and is already published by docker-compose —
all it needs is a public address. On a VPS with a static IP that address is
simply **`<VPS_STATIC_IP>:5123`** (replace with your server's IP). Enter it in
the tracker's server settings via the TCT app or Teltonika Configurator:

- **FMC001**: GPRS → **Second Server** → Domain + Port, Protocol = TCP,
  Mode = Duplicate (details in FMC001-SETUP.md, sections C + E)
- **FMC150**: **Server Settings** → Domain + Port, Protocol = TCP
  (details in FMC150-SETUP.md, sections C + E)

Also tell the bridge which IMEI is which model in `.env`:

```bash
BRIDGE_DEVICES=867648042983435:fmc001,357234561234567:fmc150
```

#### Hosting on a VPS (static IP)

1. Provision any small VPS (1 vCPU / 2 GB RAM is enough) with a **static IPv4**.
2. Install Docker + Compose plugin, copy this repo and your `.env` over.
3. Open inbound TCP port **`5123`** in the firewall/security group
   (plus `5173`/`8000` only if you want the dashboard reachable publicly).
4. `docker compose up --build -d` — the stack is now always-on.
5. Point each tracker at `<VPS_STATIC_IP>:5123` — configured once, no tunnel,
   no address churn.

Running on a laptop for a bench test instead? Any machine reachable on its
LAN works too — just use that machine's IP:5123 while the car is in Wi-Fi/LAN
coverage of your router with a port-forward. A VPS is the robust always-on
option.

### 4 — Register your car

```bash
curl -X POST http://localhost:8000/api/v1/assets/vehicles/register ^
  -H "Content-Type: application/json" ^
  -d "{\"name\": \"My Car\", \"imei\": \"YOUR_15_DIGIT_IMEI\", \"license_plate\": \"SXX1234A\", \"device_type\": \"fmc001\"}"
```

`device_type` is `"fmc001"` (default) or `"fmc150"` — it selects which sensor
catalog gets provisioned. This creates the vehicle **and** its
components/sensors from the catalog
(`backend/app/services/provisioning.py`), so the dashboard and rule engine
know the sensor types before the first record arrives.

### 5 — Open the app

| URL | What you get |
|---|---|
| **http://localhost:5173** | 🖥️ Main dashboard |
| http://localhost:8000/docs | 📖 Interactive API docs (Swagger) |
| http://localhost:8000/health | ❤️ Health check |

Your car tile starts **GREY** and flips **GREEN** when the first real record
arrives. Watch the pipeline live with `docker compose logs -f bridge`.

### Stopping and resetting

```bash
docker compose down        # stop (data preserved)
docker compose down -v     # stop AND wipe all data
docker compose logs -f bridge    # device connections, AVL decode, ACKs
docker compose logs -f backend   # ingestion + rule engine
```

## Web App Pages

| Route | Page | Purpose |
|---|---|---|
| `/` | Dashboard | Fleet health (Green/Yellow/Red/Grey), live sensor tiles |
| `/assets` | Assets | Vehicle → Component → Sensor hierarchy |
| `/workorders` | Work Orders | Assign, complete, close — technician feedback loop |
| `/alerts` | Alerts | Active/acknowledged/resolved alerts from the rule engine |
| `/rules` | Rules | Threshold + DTC rules, templates, shadow-mode toggle |

## Core Modules

1. **Teltonika Bridge** (`bridge/`) — raw TCP listener; IMEI handshake, Codec
   8/8E decode, CRC verify, ACK; maps AVL I/O elements → sensors via
   `bridge/avl_map.<model>.json` (per-device-model, config-driven, no code
   changes for new parameters); `BRIDGE_DEVICES` routes each IMEI to its model
2. **Data Ingestion** — MQTT subscriber stores readings in TimescaleDB, caches
   latest state in Redis, pushes WebSocket updates
3. **Rule Engine** — threshold + DTC rules generate alerts; **freshness guard**
   skips records older than `RULE_MAX_RECORD_AGE_SECONDS` (device buffers data
   out-of-coverage and burst-uploads later — history never fires alerts)
4. **Work Orders** — auto-generated from alerts; technician assign/complete
   closes the loop into maintenance history
5. **Dashboard** — live fleet health via WebSocket + polling

## Teltonika Integration (FMC001 + FMC150)

Neither tracker speaks MQTT — they stream Teltonika's binary AVL protocol
(Codec 8 Extended) over raw TCP via LTE. The `bridge` service is the adapter:
it decodes AVL and republishes to Mosquitto using the backend's exact JSON
contract (`teltonika/{imei}/telemetry`, `teltonika/{imei}/dtc`), so ingestion,
rules, and the dashboard are hardware-agnostic. Because the IMEI handshake
carries no model info, `BRIDGE_DEVICES=imei:model,...` tells the bridge which
AVL map to apply — FMC001 (OBD-II PID IDs) or FMC150 (CAN IDs) — and both maps
normalize into the **same sensor_type strings**, so one set of rules covers
both trackers.

Full hardware onboarding — OBD plug-in / CAN wiring, server settings,
Configurator settings, troubleshooting:
**[FMC001-SETUP.md](FMC001-SETUP.md)** · **[FMC150-SETUP.md](FMC150-SETUP.md)**.

## Shadow Mode

Enabled by default (`SHADOW_MODE=true`) — generated work orders arrive in
*shadow* status for review. Toggle on the Rules page or:

```bash
curl -X POST "http://localhost:8000/api/v1/system/shadow-mode?enabled=false"
```

## Project Structure

```
pdm-second/
├── docker-compose.yml   # Full-stack orchestration (6 services)
├── .env.example         # Environment config template
├── FMC001-SETUP.md      # 🚗 FMC001 (OBD plug-in) → dashboard onboarding checklist
├── FMC150-SETUP.md      # 🚗 FMC150 (wired CAN) → dashboard onboarding checklist
├── bridge/              # Teltonika AVL (Codec 8/8E) → MQTT bridge
│   ├── codec8e.py       #   Protocol parser (pure functions)
│   ├── fmc_bridge.py    #   TCP server + MQTT publisher (IMEI → model routing)
│   ├── avl_map.fmc001.json  # FMC001 OBD-II AVL ID → sensor mapping (edit this, not code)
│   ├── avl_map.fmc150.json  # FMC150 CAN AVL ID → sensor mapping (edit this, not code)
│   └── tests/           #   Golden-frame parser + payload tests (pytest)
├── backend/             # FastAPI app (REST + WebSocket + MQTT ingestion)
├── frontend/            # React + Vite + TypeScript dashboard
└── mosquitto/           # MQTT broker config + Dockerfile
```

## Tests

```bash
python -m pytest bridge/tests/ -v    # Codec 8/8E parser + payload mapping, both models (30 tests)
```
