# Connect Your Car to the Dashboard — FMC001 Setup Guide

> Everything you need to stream **real** car sensor data from a Teltonika
> **FMC001** (OBD-II plug-and-play tracker) into the PREDICT dashboard —
> **without disturbing the resqmatics platform** the device already reports to.
> (Looking for the wired FMC150 CAN tracker? See [FMC150-SETUP.md](FMC150-SETUP.md).)

## How the data flows

```
                ┌── 4G LTE (primary server, UNCHANGED) ──► resqmatics
Car OBD-II ──plug──► FMC001 ─┤
                └── 4G LTE (Second Server, Duplicate) ──► <VPS_STATIC_IP>:5123
                                                              └► fmc-bridge ─► MQTT ─► backend ─► dashboard
```

The FMC001 **cannot stream over USB or Bluetooth** — those are config-only.
LTE to a TCP server is the only telemetry path. The device speaks Teltonika's
binary **Codec 8 Extended** protocol; the `bridge` service decodes it and
republishes to MQTT in the exact JSON shape the backend consumes — so the
backend, rule engine, and dashboard need zero hardware-specific knowledge.

**Duplicate mode (why your resqmatics view keeps working):** the FMC001 has a
*Second Server* setting. In **Duplicate** mode it sends every record to BOTH
the primary server (resqmatics) and our bridge. Caveat: the device only clears
records from internal memory once **both** servers ACK. If our endpoint is
unreachable for a long time, the device buffer fills up — short outages just
backfill later (and the rule engine ignores records older than
`RULE_MAX_RECORD_AGE_SECONDS=300`, so backfilled history never fires phantom
alerts). Pick an endpoint accordingly (section C).

## Information Checklist — collect ALL of this BEFORE starting

### A. From the FMC001 device

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 1 | **IMEI** (15 digits) | Sticker on device / box / resqmatics asset page / Teltonika Configurator → Device Info | ① `.env` → `BRIDGE_DEVICES` as `867648042983435:fmc001` (bridge accept-list + model routing) ② `POST /api/v1/assets/vehicles/register` (register the car so the backend accepts its data). **Done for IMEI 867648042983435.** |

### B. From the SIM card

Nothing to do. The SIM/APN already works (the device is live on resqmatics) —
do **not** touch the APN or primary server settings. Just budget for roughly
**2× data** (~50–100 MB/month) because Duplicate mode sends every record twice.

### C. From your machine — the public endpoint

The stack runs on a **VPS with a static IP** (see README → "Hosting on a VPS"):
the bridge container publishes port `5123`, so the endpoint is simply
**`<VPS_STATIC_IP>:5123`** — configure it on the device once, forever. No
tunnel, no address churn. (Bench testing on a laptop instead? Use the
machine's LAN IP with a router port-forward for `5123`.)

| # | Information | Where it gets plugged in |
|---|---|---|
| 2 | **Public endpoint** = `<VPS_STATIC_IP>:5123` | TCT app / Configurator → **GPRS → Second Server → Domain + Port**, Protocol = **TCP**, Mode = **Duplicate** |
| 3 | **MQTT credentials** | `.env` (`MQTT_USERNAME` / `MQTT_PASSWORD`) — already wired into the bridge container, nothing to do |
| 4 | **Backend API URL** | `http://<VPS_STATIC_IP>:8000` (or `http://localhost:8000` when run locally) — used for vehicle registration (already done) |

### D. From the car

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 5 | **OBD-II port location** | Usually under the steering column | The FMC001 plugs straight in — **no wiring, no fuse taps, no CAN-H/CAN-L** (unlike the FMC150) |
| 6 | Which OBD PIDs your car answers | Discovered automatically — see "first drive" below | Nothing to configure; the bridge logs what arrives |

Ignition detection is automatic (the FMC001 detects ignition from OBD power
voltage, 13.2–30 V by default).

### E. Configurator selections (TCT app over Bluetooth, or micro-USB + Teltonika Configurator)

| Setting | Value |
|---|---|
| Data protocol | **Codec 8 Extended** — mandatory. VIN (256), fault codes (281) and service distance (402) do not exist in plain Codec 8 |
| GPRS → **primary** Server + APN | **DO NOT TOUCH** — this is the resqmatics feed |
| GPRS → **Second Server** | Mode = **Duplicate**, Domain + Port = your endpoint (C-2), Protocol = **TCP** |
| Record period / Send period | **10s / 10s** (near-real-time feed; also increases resqmatics data density + SIM usage) |
| I/O parameters to enable (priority Low) | Keep the defaults (239 Ignition · 240 Movement · 21 GSM Signal · 66 External Voltage · 67 Battery Voltage · 24 Speed · 16 Total Odometer) and add: **30** DTC count · **31** Engine Load · **32** Coolant Temp · **35** Intake MAP · **36** RPM · **37** Speed (OBD) · **39** Intake Air Temp · **41** Throttle · **42** Runtime · **48** Fuel Level · **51** Control Module Voltage · **53** Ambient Temp · **58** Oil Temp · **60** Fuel Rate · **256** VIN · **281** Fault Codes · **402** Distance Until Service |

> Reality check: the FMC001 is **store-and-forward**, not a literal byte
> stream. It generates records on schedule and pushes them in batches,
> buffering to internal memory when coverage drops.

## What shows up on the dashboard (AVL → sensor mapping)

| AVL ID | Dashboard sensor | Unit | Notes |
|---|---|---|---|
| 239 | Ignition state | on/off | Drives GREY→GREEN health transition |
| 66 | battery_voltage | V | Sent in mV → ÷1000 by bridge |
| 67 | tracker_battery_voltage | V | FMC001 internal battery, ÷1000 |
| 16 | odometer | km | Sent in m → ÷1000 |
| 24 | vehicle_speed | km/h | GNSS-based |
| 37 | vehicle_speed_obd | km/h | ECU-reported |
| 21 | gsm_signal | 1–5 | Link quality |
| 240 | Movement flag | 0/1 | Top-level payload field |
| 256 | VIN | — | Top-level payload field (ASCII, not a sensor tile) |
| 36 | engine_rpm | RPM | OBD PID — car-dependent |
| 32 | coolant_temperature | °C | OBD PID |
| 31 | engine_load | % | OBD PID |
| 48 | fuel_level | % | OBD PID (FMC001 id — differs from FMC150's CAN id 89) |
| 60 | fuel_rate | L/h | OBD PID, ÷100 |
| 58 | engine_oil_temperature | °C | OBD PID |
| 41 | throttle_position | % | OBD PID |
| 39 | intake_air_temperature | °C | OBD PID |
| 35 | intake_map | kPa | OBD PID |
| 42 | engine_runtime | s | OBD PID |
| 53 | ambient_air_temperature | °C | OBD PID |
| 51 | control_module_voltage | V | ECU supply voltage, ÷1000 — charging-system health |
| 30 | dtc_count | — | Number of active fault codes |
| 43 | mil_on_distance | km | Distance driven with check-engine light on |
| 49 | codes_cleared_distance | km | Distance since codes last cleared |
| 281 | → Alerts page (fault codes) | — | Comma-separated ASCII; bridge splits and publishes each code |
| 402 | distance_until_service | km | OEM PID — the predictive-maintenance gem; **not every car answers it** |

> Not every car answers every OBD PID — that's normal. **Discovery tool:** the
> bridge logs every *unmapped* AVL ID it receives — run
> `docker compose logs -f bridge` after your first drive to see exactly what
> your car sends, then edit `bridge/avl_map.fmc001.json` (no code changes
> needed). If your car never reports AVL 402, deactivate the two
> service-countdown rules on the Rules page so they can't fire on a stale
> value.

## Bring-up steps (in order)

1. **Collect** the checklist items above (most are already done for the
   current setup: vehicle registered, rules created, IMEI allowlist set).
2. **Start the stack**: `docker compose up --build`
   (6 services: mosquitto, postgres, redis, backend, bridge, frontend).
3. **(Already done) Register the car**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/assets/vehicles/register \
     -H "Content-Type: application/json" \
     -d "{\"name\": \"My Car\", \"imei\": \"867648042983435\", \"license_plate\": \"<PLATE>\", \"make\": \"<MAKE>\", \"model\": \"<MODEL>\"}"
   ```
   Creates the vehicle **plus** 4 components and 22 sensors from the catalog.
   To add plate/make/model later: `PATCH /api/v1/assets/vehicles/1`.
4. **Note the public endpoint** per section C — `<VPS_STATIC_IP>:5123` (make
   sure the VPS firewall allows inbound TCP 5123 and the stack is running).
5. **Configure the FMC001** (section E) — TCT app over Bluetooth next to the
   car, or micro-USB + Teltonika Configurator. Only the *Second Server*,
   *Data Protocol*, *I/O list*, and *Data Acquisition* change.
6. **Take a drive**, watch live tiles + alerts. Check
   `docker compose logs bridge` for unmapped AVL IDs and tune
   `bridge/avl_map.fmc001.json` to taste.

## Rules for the new sensors (fresh DB vs existing DB)

Fresh databases get these automatically from `backend/app/db/init_db.py`.
An **already-seeded** DB (like this one) needs them via the API — template
first, then rules referencing its id (34 in this database — check
`GET /api/v1/rules/templates`):

```bash
curl -X POST http://localhost:8000/api/v1/rules/templates -H "Content-Type: application/json" \
  -d "{\"name\": \"Scheduled Maintenance\", \"description\": \"Vehicle is approaching (or past) its manufacturer service interval.\", \"default_priority\": \"medium\", \"estimated_duration_minutes\": 120, \"instructions\": \"1. Review service countdown and odometer\\n2. Book service appointment\\n3. Perform scheduled maintenance\\n4. Reset service interval\"}"

curl -X POST http://localhost:8000/api/v1/rules -H "Content-Type: application/json" \
  -d "{\"name\": \"Service Due Soon\", \"rule_type\": \"threshold\", \"sensor_type\": \"distance_until_service\", \"operator\": \"<\", \"threshold_value\": 1000, \"duration_seconds\": 0, \"severity\": \"warning\", \"work_order_template_id\": 34}"

curl -X POST http://localhost:8000/api/v1/rules -H "Content-Type: application/json" \
  -d "{\"name\": \"Service Overdue\", \"rule_type\": \"threshold\", \"sensor_type\": \"distance_until_service\", \"operator\": \"<\", \"threshold_value\": 100, \"duration_seconds\": 0, \"severity\": \"critical\", \"work_order_template_id\": 34}"

curl -X POST http://localhost:8000/api/v1/rules -H "Content-Type: application/json" \
  -d "{\"name\": \"High Engine Oil Temperature\", \"rule_type\": \"threshold\", \"sensor_type\": \"engine_oil_temperature\", \"operator\": \">\", \"threshold_value\": 125, \"duration_seconds\": 300, \"severity\": \"warning\", \"work_order_template_id\": 1}"

curl -X POST http://localhost:8000/api/v1/rules -H "Content-Type: application/json" \
  -d "{\"name\": \"Low Control Module Voltage\", \"rule_type\": \"threshold\", \"sensor_type\": \"control_module_voltage\", \"operator\": \"<\", \"threshold_value\": 12, \"duration_seconds\": 300, \"severity\": \"warning\", \"work_order_template_id\": 5}"
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Device never connects to our bridge | Second Server domain/port wrong, UDP instead of TCP, VPS firewall blocking 5123, or the stack is down (`docker compose ps` on the VPS) |
| resqmatics stopped updating too | Device memory full because the second server is unreachable — disable Duplicate mode or fix the endpoint, then let the buffer drain |
| `REJECTED unknown IMEI` in bridge logs | IMEI not in `BRIDGE_DEVICES` (currently locked to `867648042983435:fmc001`) |
| Records in bridge logs, empty dashboard | Car not registered (step 3) — backend drops unknown IMEIs by design |
| Connects, but no RPM/fuel/coolant | Car doesn't answer those OBD PIDs, or Codec 8 Extended not selected — check bridge logs for what actually arrives |
| No VIN / no fault codes / no service distance | Data Protocol still on plain Codec 8 — switch to Codec 8 Extended (section E) |
| Fault codes arrive as hex garbage | `avl_map.fmc001.json` entry for 281 lost its `"encoding": "ascii"` — restore it |
| Service alerts fired for a car that never reports AVL 402 | Can't happen from missing data (rules skip absent sensors) — but if the car reports a bogus 0, deactivate the two service rules on the Rules page |
| Alerts fired for an old trip | Should not happen — rule engine skips records older than `RULE_MAX_RECORD_AGE_SECONDS` (default 300s) |

## Reference — files that matter

| File | Role |
|---|---|
| `bridge/fmc_bridge.py` | TCP server: IMEI handshake, IMEI→model routing, AVL loop, MQTT publisher (ASCII decode + DTC split) |
| `bridge/codec8e.py` | Codec 8/8E parser (unit-tested in `bridge/tests/`) |
| `bridge/avl_map.fmc001.json` | **FMC001 AVL ID → sensor mapping — edit this, not code** |
| `backend/app/services/provisioning.py` | Component/sensor catalog for new vehicles (keep AVL IDs in sync with `avl_map.fmc001.json`) |
| `backend/app/db/init_db.py` | Seeds rules + work-order templates for fresh databases |
| `backend/app/ingestion/mqtt_service.py` | The seam: consumes the bridge's JSON unchanged |
