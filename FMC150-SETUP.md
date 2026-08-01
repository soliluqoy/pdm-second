# Connect Your Car to the Dashboard — FMC150 Setup Guide

> Everything you need to collect, and exactly where each piece of information
> gets plugged in, to stream **real** car sensor data from a Teltonika
> **FMC150** (wired CAN tracker) into the PREDICT dashboard.
> (Using the OBD-II plug-in FMC001 instead? See [FMC001-SETUP.md](FMC001-SETUP.md).
> Both devices can report to the same stack at once — the bridge routes each
> IMEI to its model via `BRIDGE_DEVICES`.)

## How the data flows

```
Car CAN bus ──wires──► FMC150 ──4G LTE──► <VPS_STATIC_IP>:5123
                                             └► fmc-bridge ──► MQTT ──► backend ──► dashboard
```

The FMC150 **cannot stream over USB or Bluetooth** — those are config-only.
LTE to a TCP server is the only telemetry path. The stack runs on a VPS with a
static IP, so the device points at `<VPS_STATIC_IP>:5123` directly — no tunnel
needed. The device speaks Teltonika's binary **Codec 8 Extended** protocol;
the `bridge` service in this repo decodes it (using `bridge/avl_map.fmc150.json`,
selected by IMEI via `BRIDGE_DEVICES`) and republishes to MQTT in the exact
JSON shape the backend consumes — so the backend, rule engine, and dashboard
need zero hardware-specific knowledge.

## Information Checklist — collect ALL of this BEFORE starting

### A. From the FMC150 device

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 1 | **IMEI** (15 digits) | Sticker on device / box / Teltonika Configurator → Device Info | ① `.env` → `BRIDGE_DEVICES` as `<IMEI>:fmc150` (bridge accept-list + model routing) ② `POST /api/v1/assets/vehicles/register` with `"device_type": "fmc150"` (register the car so the backend accepts its data) |

### B. From the SIM card

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 2 | **APN** | SIM provider's docs/portal | Teltonika Configurator → **GPRS → APN** |
| 3 | **SIM PIN disabled** | Put the SIM in any phone first, disable the PIN | — (a PIN-locked SIM fails silently) |
| 4 | **Data plan active** (~50 MB/month is plenty) | SIM provider portal | — |

### C. From your machine

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 5 | **Public endpoint** = `<VPS_STATIC_IP>:5123` | Your VPS provider's panel (static IPv4). Stack runs on the VPS per README → "Hosting on a VPS"; make sure the firewall allows inbound TCP 5123 | Configurator → **Server Settings → Domain + Port**, Protocol = **TCP** |
| 6 | **MQTT credentials** | `.env` (`MQTT_USERNAME` / `MQTT_PASSWORD`) | Already wired into the bridge container — nothing to do |
| 7 | **Backend API URL** | `http://<VPS_STATIC_IP>:8000` (or `http://localhost:8000` when run locally) | Used for vehicle registration (step A-②) |

### D. From the car

| # | Information | Where to find it | Where it gets plugged in |
|---|---|---|---|
| 8 | **OBD-II port location** — CAN-H = **pin 6**, CAN-L = **pin 14** | Car manual / under the steering column | FMC150 CAN wires |
| 9 | **Constant +12V fuse slot** + chassis ground point | Fuse box diagram | FMC150 red (+) and black (–) wires via fuse tap |
| 10 | **Ignition-switched +12V** (optional) | Fuse box | FMC150 ignition wire — or skip and use voltage-based ignition detection in Configurator |
| 11 | **CAN program number / vehicle compatibility** | Teltonika supported-vehicles list (wiki) | Configurator → **CAN section**. Decides which of fuel/RPM/coolant/DTCs your car exposes — GPS, ignition, and battery voltage work on *every* car |

### E. Configurator selections (the "always stream" setup)

| Setting | Value |
|---|---|
| Data protocol | **Codec 8 Extended** (required — CAN params use 2-byte I/O IDs) |
| Record period / Send period | **10s / 10s** (near-real-time feed) |
| I/O parameters to enable (priority Low) | 239 Ignition · 240 Movement · 66 External Voltage · 67 Battery Voltage · 21 GSM Signal · 24 Speed · + CAN parameters from the table below (subject to D-11) |

> Reality check: the FMC150 is **store-and-forward**, not a literal byte
> stream. It generates records on schedule and pushes them in batches. If
> coverage drops it buffers to internal memory and uploads the backlog when
> the link returns — the backend stores everything but only runs the rule
> engine on fresh records (`RULE_MAX_RECORD_AGE_SECONDS=300`), so old trips
> never fire phantom alerts.

## What shows up on the dashboard (AVL → sensor mapping)

IDs below match `bridge/avl_map.fmc150.json` exactly (verified against the
Teltonika wiki page "FMC150 Teltonika Data Sending Parameters ID").

| AVL ID | Dashboard sensor | Unit | Notes |
|---|---|---|---|
| 239 | Ignition state | on/off | Drives GREY→GREEN health transition |
| 66 | battery_voltage | V | Tracker supply voltage, sent in mV → ÷1000 by bridge |
| 67 | tracker_battery_voltage | V | FMC150 internal backup battery, ÷1000 |
| 24 | vehicle_speed | km/h | GNSS-based |
| 21 | gsm_signal | 1–5 | Link quality |
| 240 | Movement flag | 0/1 | Top-level payload field |
| 85 | engine_rpm | RPM | CAN — only if car supports (D-11) |
| 115 | coolant_temperature | °C | CAN — multiplier 0.1 (raw 910 = 91.0 °C) |
| 81 | vehicle_speed_obd | km/h | CAN — wheel-speed/ECU speed (same sensor_type as FMC001's OBD speed) |
| 82 | throttle_position | % | CAN |
| 89 | fuel_level | % | CAN — **89, not 81** (81 is vehicle speed) |
| 84 | fuel_level_liters | l | CAN — multiplier 0.1 |
| 83 | fuel_consumed | l | CAN — cumulative, multiplier 0.1 |
| 87 | odometer | km | CAN "Total Mileage" — true vehicle mileage, sent in m → ÷1000. (GNSS odometer 16 is deliberately unmapped for this model) |
| 102 | engine_hours | min | CAN — engine work time |
| 168 | vehicle_battery_voltage | V | CAN — battery voltage as reported by the vehicle |
| 152 | hv_battery_charge | % | CAN — EV/hybrid high-voltage battery charge |
| 1396 | ambient_air_temperature | °C | CAN extended |
| 1270 | engine_oil_temperature | °C | CAN extended |
| 1158 | engine_oil_pressure | kPa | CAN extended |
| 1159 | engine_oil_level | % | CAN extended |
| 325 | VIN | — | Top-level payload field (ASCII, not a sensor tile) |
| 160 | dtc_count | — | Number of active fault codes (CAN adapter group) |
| 282 | → Alerts page (DTC) | — | Comma-separated ASCII; bridge splits and publishes each code (LV-CAN200+DTC / CANCONTROL) |
| 400 | distance_until_service | km | CAN — countdown to next scheduled service; only if the car exposes it |
| 866 | remaining_distance | km | CAN — range with current tank/battery |

> ⚠️ CAN parameters arrive **only if your car is on Teltonika's compatibility
> list** and the right CAN program number is selected (D-11). GPS, ignition,
> and voltage work on every car regardless.
> **Discovery tool:** the bridge logs every *unmapped* AVL ID it receives —
> run `docker compose logs -f bridge` after your first drive to see exactly
> what your car sends, then edit `bridge/avl_map.fmc150.json` (no code changes
> needed).

## Bring-up steps (in order)

1. **Collect** the 11 checklist items above.
2. **Start the stack**: `copy .env.example .env` → `docker compose up --build`
   (6 services: mosquitto, postgres, redis, backend, bridge, frontend).
3. **Register the car** (replace the IMEI with yours — note `device_type`):
   ```bash
   curl -X POST http://localhost:8000/api/v1/assets/vehicles/register \
     -H "Content-Type: application/json" \
     -d "{\"name\": \"My Car\", \"imei\": \"350424061234001\", \"device_type\": \"fmc150\", \"license_plate\": \"SXX1234A\", \"make\": \"Toyota\", \"model\": \"Corolla\", \"year\": 2020}"
   ```
   This creates the vehicle **plus** its components and sensors from the
   FMC150 CAN catalog, so the dashboard and rule engine are ready for the
   first record.
4. **Note the public endpoint** — `<VPS_STATIC_IP>:5123` (section C-5).
5. **Configure the FMC150** via USB + Teltonika Configurator (sections B, C, E
   above). Bench power: red→+12V, black→GND, ignition wire→+12V (key-on).
6. **Verify the pipeline** (bench, near a window for GPS):
   - `docker compose logs -f bridge` → `Device connected: IMEI ... (FMC150)` then
     `N record(s) published, ACK sent`
   - MQTT Explorer on `teltonika/#` → JSON payloads flowing
   - Dashboard `http://localhost:5173` → your car tile flips GREY→GREEN with
     live voltage/speed/GPS. *(CAN sensors appear only once wired to the car.)*
7. **Wire into the car** (section D), take a drive, watch live tiles + alerts.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Device never connects | Wrong APN / SIM PIN locked / no data plan / VPS firewall blocking 5123 / stack down (`docker compose ps` on the VPS) |
| Connects, no records | Wrong domain:port in Server Settings, or UDP selected instead of TCP |
| `REJECTED unknown IMEI` in bridge logs | IMEI not in `BRIDGE_DEVICES` (or clear the list to accept all as `BRIDGE_DEFAULT_MODEL`) |
| Records mapped as if OBD (RPM/fuel missing, wrong values) | IMEI pinned to the wrong model — it must be `<IMEI>:fmc150` in `BRIDGE_DEVICES`, not fmc001 |
| Records in bridge logs, empty dashboard | Car not registered (step 3) — backend drops unknown IMEIs by design |
| GPS shows 0,0 | No sky view — move near a window (bench) / re-mount with antenna facing sky (car) |
| No fuel/RPM/coolant values | Car not on CAN compatibility list, or wrong CAN program number — check `docker compose logs bridge` for unmapped AVL IDs |
| Alerts fired for an old trip | Should not happen — rule engine skips records older than `RULE_MAX_RECORD_AGE_SECONDS` (default 300s). Raise it if your send period is longer |

## Reference — files that matter

| File | Role |
|---|---|
| `bridge/fmc_bridge.py` | TCP server: IMEI handshake, IMEI→model routing, AVL loop, MQTT publisher |
| `bridge/codec8e.py` | Codec 8/8E parser (unit-tested in `bridge/tests/`) |
| `bridge/avl_map.fmc150.json` | **FMC150 CAN AVL ID → sensor mapping — edit this, not code** |
| `backend/app/services/provisioning.py` | Component/sensor catalog for new vehicles (keep AVL IDs in sync with `avl_map.fmc150.json`) |
| `backend/app/ingestion/mqtt_service.py` | The seam: consumes the bridge's JSON unchanged |
