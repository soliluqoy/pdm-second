# PREDICT — Comprehensive Fix & Integration Plan

> **Goal:** Close the full loop — simulator → MQTT → ingestion → rule engine → alerts/work orders → WebSocket → dashboard UI → technician feedback — with no silent failures and verifiable end-to-end behavior.

**Last audited:** 2026-07-31  
**Frontend build:** `npm run build` passes (`tsc -b && vite build`)

---

## Executive Summary

The stack is **~70% wired**. Telemetry ingestion, Redis caching, REST APIs, WebSocket fan-out, and the new live dashboard UI work today. The **rule engine is completely missing**, which breaks the product's core promise: anomalies never become alerts, work orders, or health degradation. Several secondary bugs prevent real-time updates on non-dashboard pages and cause demo misalignment between simulator timing and rule durations.

This plan is ordered by dependency: build the missing backend brain first, align demo data, then connect the frontend live layer everywhere, then polish and verify.

---

## System Status Matrix

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| **Transport** | Mosquitto MQTT | ✅ Working | Auth, topics, healthcheck OK |
| **Transport** | FMC150 simulator | ⚠️ Partial | Publishes telemetry/DTCs; anomalies too short; fuel drains forever; ignition never cycles |
| **Ingestion** | `mqtt_service.py` | ⚠️ Partial | Stores readings, Redis cache, WS telemetry; rule calls silently no-op |
| **Engine** | `app/rules/engine.py` | 🔴 **Missing** | ImportError swallowed → zero alerts/WOs/health changes |
| **API** | REST endpoints | ✅ Working | All routes match frontend client paths |
| **API** | `/dashboard/fleet/live` | ✅ Working | Bulk live sensors + thresholds + rules (new) |
| **Realtime** | Redis pub/sub → WS | ⚠️ Partial | Only `ws:telemetry` is actively published; alert/WO/health publishers unused |
| **Frontend** | Dashboard live UI | ✅ Working | `VehicleTelemetryCard`, `SensorDetailDrawer`, WS patch + 15s fallback poll |
| **Frontend** | Alerts / Work Orders | ⚠️ Partial | Fetch-on-mount only; no WS, no polling → engine output invisible until manual reload |
| **Frontend** | WebSocket hook | 🐛 Bug | Unmount `close()` schedules zombie reconnect (StrictMode leak) |
| **Frontend** | API client typing | ⚠️ Partial | `getFleetLive` typed; most methods still return `any` |
| **Ops** | SQL echo | 🐛 Noisy | `echo=settings.DEBUG` logs every INSERT |
| **Ops** | Mosquitto logs | 🐛 Hidden | File-only logging; `docker compose logs mosquitto` empty |
| **Repo** | Build artifacts | ⚠️ Untracked | `*.tsbuildinfo`, generated `vite.config.js` not gitignored |

---

## Target Data Flow (must all be green)

```
Simulator ──MQTT──► mqtt_service ──► TimescaleDB (history)
                         │
                         ├──► Redis vehicle:{id}:state
                         │
                         ├──► publish_telemetry ──► WS ws:telemetry ──► Dashboard (live sensors)
                         │
                         └──► rules/engine ──► Alert + WorkOrder (DB)
                                    │
                                    ├──► publish_alert ──► WS ws:alerts ──► Alerts page + Dashboard summary
                                    ├──► publish_work_order ──► WS ws:workorders ──► Work Orders page + Dashboard summary
                                    └──► publish_health_update ──► WS ws:health ──► Dashboard health badges
```

**Technician loop (already implemented in API, needs engine to populate data):**

```
Work Orders: assign → complete → MaintenanceHistory + resolve linked Alert
```

---

## Bug Registry

### 🔴 Critical (blocks demo)

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| C1 | Rule engine package does not exist | `backend/app/rules/` missing; `mqtt_service.py:168` swallows `ImportError` | No alerts, WOs, YELLOW/RED health — README Step 4 impossible |
| C2 | Anomaly duration < rule duration | Simulator: 3–10 cycles (30–100s); coolant rules need 300s sustained | Even with engine, flagship coolant rule never fires |
| C3 | `publish_alert` / `publish_health_update` never called | `redis_client.py` defined; only `publish_telemetry` used | Dashboard summary cards and Alerts page stay at 0 |

### 🟠 High (broken real-time UX)

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| H1 | WS zombie reconnect on unmount | `useWebSocket.ts:51–57, 72–74` | Extra socket after StrictMode remount |
| H2 | Alerts page never auto-refreshes | `AlertsPage.tsx` — fetch once on filter change | Engine alerts invisible without F5 |
| H3 | Work Orders page never auto-refreshes | `WorkOrdersPage.tsx` — same | Auto-generated WOs invisible without F5 |
| H4 | GREY→GREEN never broadcasts health | `mqtt_service.py:143–144` sets health but `publish_health_update` unused | Dashboard health chips stay grey until REST poll |
| H5 | WO assign/complete don't publish WS | `workorders.py` — only manual `create` calls `publish_work_order` | Other pages miss status changes |
| H6 | Alert ack/resolve don't publish WS | `alerts.py` | Dashboard alert counts stale until poll |

### 🟡 Medium (demo quality / correctness)

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| M1 | Missing DTC rules P0500, P0115 | `init_db.py` SEED_RULES | Simulator emits these; would be dropped by engine |
| M2 | Fuel only drains, never refills | `fmc150_sim.py:141–144` | All vehicles eventually sit at 0% fuel |
| M3 | Ignition hardcoded `True` | `fmc150_sim.py:73, 111` | Dead `if not self.ignition` branches; unrealistic idle |
| M4 | Dead `fuel_level` assignment in low-fuel branch | `fmc150_sim.py:127–128` | Overwritten at line 144 anyway |
| M5 | `patchTelemetry` doesn't patch `health` | `DashboardPage.tsx:81–108` | OK if `ws:health` works; otherwise health stale between polls |
| M6 | Assets page static | `AssetsPage.tsx` | Vehicle health never updates while page open |

### 🟢 Low (polish)

| ID | Issue | Location | Fix |
|----|-------|----------|-----|
| L1 | SQL echo tied to DEBUG | `database.py:17` | Add `SQL_ECHO` setting, default `false` |
| L2 | Mosquitto logs file-only | `mosquitto.conf:10` | Add `log_dest stdout` |
| L3 | API client returns `any` | `client.ts` | Wire to `types/index.ts` interfaces |
| L4 | Build artifacts untracked | `*.tsbuildinfo`, `vite.config.js` | Add to `.gitignore` |
| L5 | `getFleetHealth()` unused | `client.ts:48` | Remove or use on Assets page |

---

## Phase 1 — Rule Engine (unblocks everything)

**Priority:** Do this first. Nothing else in the alert/WO pipeline matters until it exists.

### 1.1 Create `backend/app/rules/` package

```
backend/app/rules/
  __init__.py
  engine.py      # evaluate_telemetry, evaluate_dtc
  duration.py    # Redis-backed sustained-condition tracking (optional split)
```

### 1.2 `evaluate_telemetry(vehicle_id, imei, sensors, ts)`

For each **active** `Rule` where `rule_type == THRESHOLD` and `sensor_type` matches:

1. Extract numeric value from sensor dict (`{value, unit}` or plain float).
2. Evaluate operator (`>`, `<`, `>=`, `<=`, `==`) against `threshold_value`.
3. **Duration tracking** (Redis keys, e.g. `rule:{rule_id}:vehicle:{vehicle_id}:since`):
   - Condition **met**: set `since` on first breach; if `(now - since) >= duration_seconds` (or `duration_seconds == 0`), trigger.
   - Condition **not met**: delete `since` key (reset sustained timer).
4. **Dedup**: skip if an ACTIVE or ACKNOWLEDGED alert already exists for `(vehicle_id, rule_id)`.
5. On trigger:
   - Insert `Alert` (title, message, trigger_value, trigger_timestamp, severity).
   - Load linked `WorkOrderTemplate`; create `WorkOrder` with status `SHADOW` if shadow mode else `OPEN`, `is_shadow` flag set accordingly.
   - Link `alert.work_order_id` ↔ `wo.alert_id`.
   - Recompute vehicle health: any ACTIVE critical → RED; any ACTIVE warning (no critical) → YELLOW; else GREEN.
   - `publish_alert(...)`, `publish_work_order(...)`, and if health changed `publish_health_update(...)`.

### 1.3 `evaluate_dtc(vehicle_id, imei, dtc_code, description, severity)`

1. Find active DTC rule matching `dtc_code`.
2. Dedup on `(vehicle_id, rule_id)` same as above.
3. Create alert + work order + health update + WS broadcasts.

### 1.4 Wire ingestion (remove silent failure)

In `mqtt_service.py`:

```python
# Replace try/except ImportError: pass with direct import at module top
from app.rules.engine import evaluate_dtc, evaluate_telemetry
```

- On GREY→GREEN transition, call `publish_health_update(vehicle.id, "green")`.
- Log rule engine errors at ERROR level; never swallow ImportError.

### 1.5 Rule engine reads shadow mode

Use same logic as `system.py`: DB `SystemConfig shadow_mode` first, fallback to `settings.SHADOW_MODE`.

**Acceptance:** After ~2 min of simulator running, `GET /api/v1/alerts?status=active` returns rows; `GET /api/v1/workorders` returns shadow WOs; vehicle health includes YELLOW/RED.

---

## Phase 2 — Simulator & Seed Alignment

Make the demo reliably trigger rules without waiting forever or missing DTCs.

### 2.1 Simulator anomaly durations

In `fmc150_sim.py`:

```python
# Map anomaly type → minimum cycles to exceed longest matching rule duration
ANOMALY_DURATIONS = {
    "high_coolant_temp": random.randint(35, 45),   # 350–450s > 300s rule
    "high_rpm": random.randint(8, 12),              # 80–120s > 60s rule
    "low_battery": random.randint(8, 12),
    "high_engine_load": random.randint(35, 45),
    "low_tire_pressure": random.randint(3, 6),      # duration_seconds=0 rules
    "low_fuel": random.randint(3, 6),
}
```

Replace `random.randint(3, 10)` with type-specific durations.

### 2.2 Fuel & ignition realism

- Refill fuel to 70–95% when it drops below 15% (simulate refuel stop).
- Randomly toggle ignition off ~5% of cycles when speed == 0; skip telemetry sensor generation when off (already partially handled).

### 2.3 Seed missing DTC rules

Add to `SEED_RULES` in `init_db.py`:

```python
{"name": "DTC P0500 - Speed Sensor", "rule_type": RuleType.DTC, "dtc_code": "P0500", ...},
{"name": "DTC P0115 - Coolant Circuit", "rule_type": RuleType.DTC, "dtc_code": "P0115", ...},
```

**Requires:** `docker compose down -v && docker compose up --build` to re-seed.

**Acceptance:** Coolant anomaly triggers critical alert within ~6 min; DTC P0500/P0115 appear on Alerts page.

---

## Phase 3 — Frontend Real-Time Integration

Connect all pages to the same live event stream the dashboard already consumes.

### 3.1 Fix WebSocket zombie reconnect

In `useWebSocket.ts`:

- Add `mountedRef` or `intentionalCloseRef`.
- Set flag before `ws.close()` in cleanup; in `onclose`, skip reconnect when intentional.
- Clear reconnect timer in cleanup **before** closing socket.

### 3.2 Share WS events app-wide

**Option A (minimal):** Pass `wsMessages` from `App.tsx` to `AlertsPage` and `WorkOrdersPage` (same pattern as `DashboardPage`).

**Option B (cleaner):** Extract `WsProvider` context with `{ connected, messages, subscribe }`.

On `ws:alerts` / `ws:workorders` → refetch list (debounced 1s, same as dashboard `scheduleRefresh`).

### 3.3 Polling fallback

Add 10s `setInterval` on Alerts and Work Orders pages as belt-and-suspenders when WS disconnects.

### 3.4 Dashboard health patch (optional optimization)

In `DashboardPage`, on `ws:health` messages, patch `fleet[].health` in state immediately instead of waiting for debounced full refetch.

### 3.5 Type the API client

Replace `any` return types in `client.ts` with interfaces from `types/index.ts`:

- `getDashboardSummary()` → `DashboardSummary`
- `getAlerts()` → `Alert[]`
- `getWorkOrders()` → `WorkOrder[]`
- etc.

Remove dead `getFleetHealth()` or wire it into Assets page health column.

**Acceptance:** Open Alerts + Work Orders tabs; within minutes of anomaly, rows appear without manual refresh. WS indicator stays stable under React StrictMode.

---

## Phase 4 — Backend WS Broadcast Completeness

Ensure every state mutation that affects the dashboard pushes an event.

| Action | Add publish |
|--------|-------------|
| Rule engine creates alert | `publish_alert` ✅ (Phase 1) |
| Rule engine creates WO | `publish_work_order` ✅ (Phase 1) |
| Health recompute | `publish_health_update` ✅ (Phase 1) |
| GREY→GREEN on first telemetry | `publish_health_update` |
| Alert acknowledge / resolve | `publish_alert` (updated payload or `{id, status}`) |
| WO assign / complete / close | `publish_work_order` |

---

## Phase 5 — Polish & Repo Hygiene

| Task | File | Change |
|------|------|--------|
| Separate SQL echo from DEBUG | `config.py`, `database.py` | `SQL_ECHO: bool = False`; `echo=settings.SQL_ECHO` |
| Mosquitto stdout logging | `mosquitto.conf` | `log_dest stdout` (keep file dest if desired) |
| Gitignore build artifacts | `.gitignore` | `*.tsbuildinfo`, `frontend/vite.config.js`, `frontend/vite.config.d.ts` |
| Remove silent ImportError | `mqtt_service.py` | Direct imports |

---

## Phase 6 — End-to-End Verification Checklist

Run after all phases:

```bash
docker compose down -v
docker compose up --build
# wait ~60s
```

### Automated

```bash
# Backend syntax
python -m compileall backend/app

# Frontend
cd frontend && npm run build
```

### Manual (README Step 4 — full loop)

| # | Check | Expected |
|---|-------|----------|
| 1 | Open http://localhost:5173 | Sidebar shows **Live** (green pulse) |
| 2 | Dashboard | 5 vehicles; GREY→GREEN within 30s; live sensor tiles updating |
| 3 | Wait 3–8 min | Summary cards: Active Alerts > 0; Shadow WOs > 0 |
| 4 | Alerts page (`/alerts`) | New rows appear **without F5** |
| 5 | Work Orders page (`/workorders`) | Shadow WOs appear **without F5** |
| 6 | Click sensor tile → drawer | 1h chart loads with threshold reference lines |
| 7 | Assign + complete a WO | Status changes; maintenance history written (`GET /api/v1/system/history`) |
| 8 | Rules page shadow toggle | New WOs respect mode |
| 9 | `docker compose logs backend` | Rule engine log lines on trigger; no ImportError |
| 10 | StrictMode | No duplicate WS connections (DevTools → Network → WS) |

### API spot-checks

```bash
curl -s http://localhost:8000/api/v1/dashboard/summary | jq .
curl -s "http://localhost:8000/api/v1/alerts?status=active" | jq 'length'
curl -s http://localhost:8000/api/v1/workorders | jq 'length'
curl -s http://localhost:8000/api/v1/dashboard/fleet/live | jq '.[0].sensors | length'
# Expect: 12 sensors per vehicle, live values populated
```

---

## Implementation Order (single sprint)

```
Day 1 ── Phase 1 (rule engine) + Phase 2 (simulator/seed)
         └── Verify alerts/WOs appear via API

Day 2 ── Phase 3 (frontend WS) + Phase 4 (backend WS completeness)
         └── Verify UI auto-updates

Day 3 ── Phase 5 (polish) + Phase 6 (full E2E checklist)
         └── README demo script passes end-to-end
```

---

## File Change Map

| File | Action |
|------|--------|
| `backend/app/rules/__init__.py` | **Create** |
| `backend/app/rules/engine.py` | **Create** — core evaluation logic |
| `backend/app/ingestion/mqtt_service.py` | Wire engine; broadcast GREY→GREEN |
| `backend/app/api/alerts.py` | Add WS publish on ack/resolve |
| `backend/app/api/workorders.py` | Add WS publish on assign/complete/close |
| `backend/app/config.py` | Add `SQL_ECHO` |
| `backend/app/db/database.py` | Use `SQL_ECHO` |
| `backend/app/db/init_db.py` | Add P0500/P0115 DTC rules |
| `simulator/fmc150_sim.py` | Longer anomalies; fuel refill; ignition cycles |
| `frontend/src/hooks/useWebSocket.ts` | Fix zombie reconnect |
| `frontend/src/App.tsx` | Share WS with Alerts/WOs (or add context) |
| `frontend/src/pages/AlertsPage.tsx` | WS listener + 10s poll |
| `frontend/src/pages/WorkOrdersPage.tsx` | WS listener + 10s poll |
| `frontend/src/api/client.ts` | Proper TypeScript return types |
| `mosquitto/mosquitto.conf` | stdout logging |
| `.gitignore` | tsbuildinfo + generated vite configs |

### Already done (in current branch — keep)

| File | Status |
|------|--------|
| `backend/app/api/dashboard.py` | `/fleet/live` endpoint with bulk sensor+rule data |
| `backend/app/schemas/schemas.py` | `VehicleLiveItem`, `LiveSensorItem`, `TriggerRuleInfo` |
| `frontend/src/pages/DashboardPage.tsx` | Live telemetry grid + WS patch |
| `frontend/src/components/dashboard/*` | VehicleTelemetryCard, SensorTile, SensorGauge, SensorDetailDrawer |
| `frontend/src/utils/sensors.ts` | Client-side status computation |
| `frontend/src/types/index.ts` | Live telemetry types |

---

## Contract Verification (confirmed healthy — do not break)

- MQTT topics: `fmc150/{imei}/telemetry`, `fmc150/{imei}/dtc`
- MQTT payload shape matches ingestion parser (nested `{value, unit}` sensors)
- Simulator IMEIs match seed vehicles (`350424061234001`–`005`)
- Sensor types in simulator match seed sensors (`engine_rpm`, `coolant_temperature`, `tire_pressure_fl`, etc.)
- REST paths match `frontend/src/api/client.ts` (`/api/v1/...`)
- WS message shape: `{ channel: "ws:telemetry"|"ws:alerts"|"ws:workorders"|"ws:health", data: {...} }`
- Redis channels match `ws/handler.py` subscriptions
- Work order complete → maintenance history + alert resolve (API already correct)
- Shadow mode: DB config + runtime `settings.SHADOW_MODE` sync via `/system/shadow-mode`

---

## Success Criteria

The project is **done** when a fresh `docker compose up --build` run completes the README demo script without manual page reloads:

1. Vehicles stream live sensor data on the dashboard.
2. Anomalies automatically create alerts and shadow work orders.
3. Health badges turn YELLOW/RED on affected vehicles.
4. Alerts and Work Orders pages update in real time.
5. Technician can assign, complete, and close the loop with maintenance history.
6. No silent ImportError, no zombie WebSockets, no empty Mosquitto logs in `docker compose logs`.
