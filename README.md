# PREDICT — Predictive Maintenance CMMS

Real Teltonika tracker data → MQTT → rule engine → alerts & work orders → live dashboard.

Supported hardware: **FMC001** (OBD-II plug-in) and **FMC150** (wired CAN). No simulator.

```
Car OBD-II → FMC001 ┐
                     ├─ 4G LTE → <HOST>:5123 → bridge (Codec 8/8E)
Car CAN ───→ FMC150 ┘                              ↓
                              MQTT (Mosquitto) → FastAPI → TimescaleDB + Redis
                                                       ↓
                                          React dashboard (WebSocket)
```

| Service    | Port | Role                                      |
|------------|------|-------------------------------------------|
| Frontend   | 5173 | React 18 + Vite 6 + Tailwind              |
| Backend    | 8000 | FastAPI — REST, WebSocket, MQTT ingestion |
| Bridge     | 5123 | Teltonika AVL TCP → MQTT                  |
| PostgreSQL | 5432 | TimescaleDB 2.17 (PG 16)                  |
| Redis      | 6379 | Live state + pub/sub                      |
| Mosquitto  | 1883 | MQTT (9001 = MQTT over WebSocket)         |

---

## Prerequisites

- Docker Desktop (Compose v2), ~2 GB free RAM
- Free ports: `5173`, `8000`, `5432`, `6379`, `1883`, `9001`, `5123`
- A reachable TCP endpoint for trackers (`<HOST>:5123`) — VPS with static IP recommended
- Teltonika FMC001 and/or FMC150 + active M2M SIM

---

## Build & run

### Full stack (recommended)

```bash
# 1. Environment
copy .env.example .env          # Windows
# cp .env.example .env          # Linux / macOS

# 2. Build images and start all 6 services
docker compose up --build

# Detached (background)
docker compose up --build -d
```

On startup the backend creates the schema, enables TimescaleDB, and seeds
operational data only (users, work-order templates, rules) — **no demo vehicles**.

| URL | Purpose |
|-----|---------|
| http://localhost:5173 | Dashboard |
| http://localhost:8000/docs | Swagger API |
| http://localhost:8000/health | Health check |

### Stop / reset / logs

```bash
docker compose down              # stop (volumes kept)
docker compose down -v           # stop and wipe all data
docker compose ps                # service status
docker compose logs -f bridge    # device connect, AVL decode, ACKs
docker compose logs -f backend   # ingestion + rule engine
docker compose restart bridge    # reload AVL maps after edit
docker compose restart backend
```

### Hosting on a VPS

1. Small VPS (1 vCPU / 2 GB) with a **static IPv4**
2. Install Docker + Compose, copy the repo + `.env`
3. Open inbound TCP **5123** (and `5173`/`8000` only if the UI should be public)
4. `docker compose up --build -d`
5. Point each tracker at `<VPS_STATIC_IP>:5123`

Bench on a laptop: use the LAN IP with a router port-forward for `5123`.

### Build / run services individually (dev)

```bash
# Frontend
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # tsc -b && vite build
npm run preview

# Backend (needs Postgres, Redis, Mosquitto from compose or local)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Bridge (needs Mosquitto)
cd bridge
pip install -r requirements.txt
python fmc_bridge.py
```

### Tests & checks

```bash
python -m pytest bridge/tests/ -v     # Codec 8/8E + AVL payload mapping
python -m compileall backend/app      # backend syntax check
cd frontend && npm run build          # TypeScript + Vite production build
```

### Key environment variables

Copy from `.env.example`. Defaults work locally.

| Area | Variables |
|------|-----------|
| DB | `POSTGRES_*`, `DATABASE_URL` |
| Redis | `REDIS_URL` |
| MQTT | `MQTT_HOST`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TELEMETRY_TOPIC`, `MQTT_DTC_TOPIC` |
| Rules | `SHADOW_MODE`, `RULE_MAX_RECORD_AGE_SECONDS` (default 300) |
| Bridge | `BRIDGE_PORT`, `BACKEND_URL`, `BRIDGE_DEVICES` (optional override), `BRIDGE_DEFAULT_MODEL` |
| Frontend | `VITE_API_URL`, `VITE_WS_URL`, `VITE_TRACKER_SERVER` (SMS template host) |

Leave `BRIDGE_DEVICES` **empty** for normal ops. The bridge polls
`GET /api/v1/system/device-registry` (IMEI → `device_type` from registered
vehicles) and picks `avl_map.<model>.json`. Set `BRIDGE_DEVICES` only as a
bench allowlist/override.

Set `VITE_TRACKER_SERVER` to your VPS static IP (or hostname) so the Assets
SMS helper can build a copy-paste `setparam` body. That value is **not** used
by the TCP listener.

---

## Connect a vehicle

### 1. Register the car (Assets UI)

Open http://localhost:5173/assets → **Register vehicle**.

Required: name, 15-digit IMEI, device type (`fmc001` / `fmc150`).  
Optional: license plate, SIM phone (for SMS), VIN / make / year / fleet.

Registration provisions components/sensors from the catalog so the dashboard
and rules know sensor types before the first record arrives. The bridge learns
the IMEI→model map from this registration (leave `BRIDGE_DEVICES` empty).

Unknown IMEIs are still dropped by the backend on purpose until registered.

API fallback:

```bash
curl -X POST http://localhost:8000/api/v1/assets/vehicles/register \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"My Car\", \"imei\": \"YOUR_15_DIGIT_IMEI\", \"license_plate\": \"SXX1234A\", \"device_type\": \"fmc001\", \"sim_phone\": \"+60123456789\"}"
```

### 2. Configure the tracker (external SMS)

PREDICT does **not** send SMS. The same templates are on
http://localhost:5173/assets under **SMS config templates** (Copy buttons).
Send from your phone to the **device SIM**.

Both devices speak **Codec 8 Extended** over TCP to `<HOST>:5123`. Set
`VITE_TRACKER_SERVER=<HOST>` in `.env` so the UI fills the host (otherwise it
shows `<VPS_STATIC_IP>`). Messages need **two leading spaces** if the device
has no SMS login/password.

**FMC001 — Second server (Duplicate)** — keep the current platform, also stream to PREDICT:

```text
  setparam 2010:2;2007:<HOST>;2008:5123;2009:0
```

| ID | Meaning |
|----|---------|
| 2010:2 | Second server = Duplicate |
| 2007 | VPS IP / hostname |
| 2008 | Port 5123 |
| 2009:0 | TCP |

**FMC150 / FMC001 — Primary server** — point the main server at PREDICT:

```text
  setparam 2001:YOUR_APN;2002:;2003:;2004:<HOST>;2005:5123;2006:0
```

| ID | Meaning |
|----|---------|
| 2001 | APN (SIM operator; leave empty if Auto APN works) |
| 2002 / 2003 | APN user / password (often empty) |
| 2004 | VPS IP / hostname |
| 2005 | Port 5123 |
| 2006:0 | TCP |

USB/Bluetooth Configurator works the same. Devices are store-and-forward; the
rule engine skips records older than `RULE_MAX_RECORD_AGE_SECONDS` so buffered
trips never fire phantom alerts.

#### FMC001 (OBD-II plug-in)

| What | Value |
|------|--------|
| Data protocol | **Codec 8 Extended** |
| GPRS → primary server / APN | Leave alone if already on another platform |
| GPRS → **Second Server** | Mode = **Duplicate**, Domain+Port = `<HOST>:5123`, Protocol = **TCP** |
| Record / send period | 10s / 10s |
| I/O to enable (priority Low) | Defaults plus OBD PIDs: 30, 31, 32, 35, 36, 37, 39, 41, 42, 48, 51, 53, 58, 60, 256, 281, 402 |

Plugs into the OBD-II port — no wiring. Duplicate mode keeps the primary platform
working; both servers must ACK before the device clears its buffer.

#### FMC150 (wired CAN)

| What | Value |
|------|--------|
| Data protocol | **Codec 8 Extended** |
| Server Settings | Domain+Port = `<HOST>:5123`, Protocol = **TCP** |
| Record / send period | 10s / 10s |
| Wiring | CAN-H pin 6, CAN-L pin 14; constant +12V + ground; ignition optional |
| CAN program | Select vehicle from Teltonika compatibility list — GPS/ignition/voltage work on every car; RPM/fuel/coolant need a supported CAN program |

### 3. Verify the pipeline

```bash
docker compose logs -f bridge
# expect: Device connected: IMEI ... then N record(s) published, ACK sent
```

Open http://localhost:5173 — vehicle tile starts **GREY**, flips **GREEN** on
first live record. Sidebar shows **Connected** when the WebSocket is up.

---

## Add / register a new sensor (module)

Data path:

```
Tracker I/O → bridge/avl_map.<model>.json → MQTT → mqtt_service → DB/rules/dashboard
```

Keep the same `sensor_type` string everywhere. FMC001 and FMC150 use **different
AVL IDs** for the same physical quantity, but normalize to the **same**
`sensor_type` so one rule set covers both.

### Checklist (keep these in sync)

| # | File | Purpose |
|---|------|---------|
| 1 | `bridge/avl_map.fmc001.json` and/or `avl_map.fmc150.json` | AVL ID → `sensor_type` (bridge publishes MQTT) |
| 2 | `backend/app/services/provisioning.py` | Catalog rows created on vehicle register |
| 3 | Rules (API, UI, or `SEED_RULES` in `init_db.py`) | Optional alerts / work orders |
| 4 | `frontend/src/utils/sensors.ts` | Optional tile icon |

### Step 1 — Discover the AVL ID

Enable the I/O on the tracker (Codec 8 Extended). Drive or bench-power the unit,
then watch:

```bash
docker compose logs -f bridge
```

Unmapped IDs are logged once per process — that is your discovery tool.

### Step 2 — Map in the bridge (no Python changes)

Edit the model file. Example entry:

```json
{
  "id": 1158,
  "sensor_type": "engine_oil_pressure",
  "name": "Engine Oil Pressure",
  "unit": "kPa",
  "kind": "sensor",
  "scale": 1,
  "offset": 0
}
```

| `kind` | Effect |
|--------|--------|
| `sensor` | `payload.sensors[sensor_type] = { value, unit }` |
| `meta` | Top-level field (`ignition`, `movement`, `vin`, …) |
| `dtc` | Split comma-separated codes → `teltonika/{imei}/dtc` |

Use `"encoding": "ascii"` for VIN / fault-code X-group fields.
Published value = `raw * scale + offset`.

```bash
docker compose restart bridge
```

### Step 3 — Add to the provisioning catalog

In `backend/app/services/provisioning.py`:

- Shared Teltonika standards → `SHARED_SENSOR_CATALOG`
- Model-specific → `FMC001_SENSOR_CATALOG` or `FMC150_SENSOR_CATALOG`

Match `sensor_type` and `io_element_id` to the AVL map. Catalog changes apply to
**newly registered** vehicles. For an existing vehicle, add a sensor via API:

```bash
curl -X POST http://localhost:8000/api/v1/assets/sensors \
  -H "Content-Type: application/json" \
  -d "{\"component_id\": 1, \"name\": \"Oil Pressure\", \"sensor_type\": \"engine_oil_pressure\", \"unit\": \"kPa\", \"io_element_id\": 1158}"
```

(Ingestion will store readings even without a Sensor row; the catalog/API row is
what creates dashboard tiles and threshold coloring.)

### Step 4 — Optional rule

Fresh DBs get `SEED_RULES` from `backend/app/db/init_db.py`. On a running DB,
use the Rules page or:

```bash
# list templates first
curl -s http://localhost:8000/api/v1/rules/templates

curl -X POST http://localhost:8000/api/v1/rules \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"High Oil Pressure\", \"rule_type\": \"threshold\", \"sensor_type\": \"engine_oil_pressure\", \"operator\": \">\", \"threshold_value\": 800, \"duration_seconds\": 60, \"severity\": \"warning\", \"work_order_template_id\": 1, \"is_active\": true}"
```

Sensor-row `warning_threshold` / `critical_threshold` color tiles; **alerts**
come from `Rule` rows.

### Step 5 — Optional frontend icon

Add an entry in `sensorIcons` inside `frontend/src/utils/sensors.ts`
(unknown types fall back to a default icon).

### Step 6 — Enable on the device

Turn on the I/O parameter in Teltonika Configurator / TCT and set priority Low
(or higher). Take a drive and confirm the tile updates.

### Register a whole new device model

1. Add `bridge/avl_map.<model>.json` (auto-loaded by filename)
2. Add `<MODEL>_SENSOR_CATALOG` and register it in `_MODEL_CATALOGS` in `provisioning.py`
3. Extend `Literal["fmc001", "fmc150"]` in `backend/app/schemas/schemas.py`
4. Register the vehicle with `"device_type": "<model>"` (bridge picks it up from device-registry)

### MQTT contract (do not break)

| Topic | Shape |
|-------|--------|
| `teltonika/{imei}/telemetry` | `{ timestamp, imei, ignition?, gps?, sensors: { type: { value, unit } } }` |
| `teltonika/{imei}/dtc` | `{ timestamp, imei, dtc_code, description, severity }` |

Backend wildcards (`.env`): `teltonika/+/telemetry`, `teltonika/+/dtc`.

---

## Sensor maps (AVL → dashboard)

Same physical quantity → same `sensor_type` on both models. Full lists live in
the JSON map files; highlights below.

### Shared / standard

| AVL | sensor_type | Notes |
|-----|-------------|-------|
| 239 | ignition (meta) | Drives GREY→GREEN |
| 240 | movement (meta) | |
| 21 | gsm_signal | |
| 66 | battery_voltage | mV → V (`scale` 0.001) |
| 67 | tracker_battery_voltage | |
| 24 | vehicle_speed | GNSS |

### FMC001 OBD highlights

| AVL | sensor_type |
|-----|-------------|
| 36 | engine_rpm |
| 32 | coolant_temperature |
| 48 | fuel_level |
| 16 | odometer |
| 51 | control_module_voltage |
| 281 | dtc (ASCII) |
| 402 | distance_until_service |
| 256 | vin (meta, ASCII) |

### FMC150 CAN highlights

| AVL | sensor_type |
|-----|-------------|
| 85 | engine_rpm |
| 115 | coolant_temperature (×0.1) |
| 89 | fuel_level |
| 87 | odometer (CAN mileage; GNSS 16 unmapped on purpose) |
| 282 | dtc (ASCII) |
| 400 | distance_until_service |
| 325 | vin (meta, ASCII) |

---

## App pages

| Route | Purpose |
|-------|---------|
| `/` | Fleet health + live sensor tiles |
| `/assets` | Vehicle → component → sensor hierarchy |
| `/workorders` | Assign / complete / close |
| `/alerts` | Rule-engine alerts |
| `/rules` | Threshold + DTC rules, shadow-mode toggle |

### Shadow mode

Default `SHADOW_MODE=true` — auto work orders land in *shadow* for review.
Toggle on the Rules page or:

```bash
curl -X POST "http://localhost:8000/api/v1/system/shadow-mode?enabled=false"
```

---

## Project structure

```
pdm-second/
├── docker-compose.yml
├── .env.example
├── bridge/
│   ├── codec8e.py              # Codec 8/8E parser
│   ├── fmc_bridge.py           # TCP server + MQTT publisher
│   ├── avl_map.fmc001.json     # FMC001 AVL → sensor map (edit this)
│   ├── avl_map.fmc150.json     # FMC150 AVL → sensor map (edit this)
│   └── tests/
├── backend/
│   └── app/
│       ├── api/                # REST routes
│       ├── ingestion/          # MQTT → DB / Redis / rules
│       ├── rules/              # Threshold + DTC engine
│       ├── services/provisioning.py
│       └── db/init_db.py       # Schema + seed templates/rules
├── frontend/                   # React + Vite dashboard
└── mosquitto/                  # Broker image + config
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Device never connects | Wrong APN / SIM PIN / firewall blocking 5123 / stack down (`docker compose ps`) |
| FMC001: primary platform also stalls | Second server unreachable — buffer waits for both ACKs; fix endpoint or disable Duplicate |
| `REJECTED unknown IMEI` | `BRIDGE_DEVICES` allowlist is set and this IMEI is missing — add it or clear `BRIDGE_DEVICES` |
| Bridge OK, empty dashboard | Vehicle not registered — backend drops unknown IMEIs |
| Wrong values / missing RPM/fuel | Wrong `device_type` on register (or stale bridge registry), or car doesn't expose that PID/CAN param — check unmapped AVL logs |
| No VIN / fault codes / service distance | Data protocol still plain Codec 8 — switch to **Codec 8 Extended** |
| Alerts on an old trip | Should not happen if `RULE_MAX_RECORD_AGE_SECONDS` is set (default 300) |
| GPS 0,0 | No sky view — window/antenna |

Useful spot-checks:

```bash
curl -s http://localhost:8000/api/v1/dashboard/summary
curl -s http://localhost:8000/api/v1/dashboard/fleet/live
curl -s "http://localhost:8000/api/v1/alerts?status=active"
curl -s http://localhost:8000/api/v1/workorders
```
