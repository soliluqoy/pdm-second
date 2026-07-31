# PREDICT — Project Status & Backlog

> **Purpose:** Living reference for architecture, verification, and remaining polish.  
> The original sprint plan is **largely complete** — the full loop (simulator → MQTT → ingestion → rule engine → alerts/work orders → WebSocket → dashboard) is working in the running stack.

**Last audited:** 2026-07-31  
**Verified:** `docker compose up --build` running; 10+ active alerts and shadow WOs via API; Mosquitto logs visible in compose output; `npm run build` passes.

---

## Is this file still needed?

**Yes, but as a status/backlog doc — not an urgent build plan.**

Most critical gaps from the original plan are closed. Keep this file for:

- End-to-end verification checklist (Phase 6 below)
- Architecture / data-flow reference
- Remaining polish and correctness items
- Contract invariants that must not regress

When all backlog items are done and automated tests exist, this can be folded into README or archived.

---

## Executive Summary

The stack is **~90% complete**. Telemetry ingestion, rule engine, Redis caching, REST APIs, WebSocket fan-out, and live dashboard UI all work today. Anomalies reliably create alerts and shadow work orders; Alerts and Work Orders pages auto-refresh via WebSocket + 10s polling.

**Remaining gaps** are mostly secondary UX and health-state consistency — not blockers for the README demo.

---

## System Status Matrix

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| **Transport** | Mosquitto MQTT | ✅ Working | Auth, topics, healthcheck, stdout logging |
| **Transport** | FMC150 simulator | ✅ Working | Type-specific anomaly durations; fuel refill; ignition cycles |
| **Ingestion** | `mqtt_service.py` | ✅ Working | Stores readings, Redis cache, WS telemetry, rule engine wired |
| **Engine** | `app/rules/engine.py` | ✅ Working | Threshold + DTC rules; duration tracking; dedup; health recompute on trigger |
| **API** | REST endpoints | ✅ Working | All routes match frontend client paths |
| **API** | `/dashboard/fleet/live` | ✅ Working | Bulk live sensors + thresholds + rules |
| **Realtime** | Redis pub/sub → WS | ✅ Working | All four channels published from engine + ingestion |
| **Frontend** | Dashboard live UI | ✅ Working | WS patch + 15s fallback poll; `ws:health` patches badges |
| **Frontend** | Alerts / Work Orders | ✅ Working | WS listener + 10s poll; no manual F5 needed |
| **Frontend** | WebSocket hook | ✅ Fixed | `intentionalClose` prevents StrictMode zombie reconnect |
| **Frontend** | API client typing | ✅ Working | Typed returns via `types/index.ts` |
| **Frontend** | Assets page | ⚠️ Partial | Fetch-on-mount only; health badges stale while page open |
| **Ops** | SQL echo | ✅ Fixed | `SQL_ECHO` setting, default `false` |
| **Ops** | Mosquitto logs | ✅ Fixed | `log_dest stdout` + file |
| **Ops** | Build artifacts | ✅ Fixed | `*.tsbuildinfo`, generated vite configs gitignored |
| **Quality** | Automated tests | 🔴 Missing | No unit/integration/E2E tests in repo |

---

## Target Data Flow (current — all green)

```
Simulator ──MQTT──► mqtt_service ──► TimescaleDB (history)
                         │
                         ├──► Redis vehicle:{id}:state
                         │
                         ├──► publish_telemetry ──► WS ws:telemetry ──► Dashboard (live sensors)
                         │
                         └──► rules/engine ──► Alert + WorkOrder (DB)
                                    │
                                    ├──► publish_alert ──► WS ws:alerts ──► Alerts + Dashboard summary
                                    ├──► publish_work_order ──► WS ws:workorders ──► Work Orders + Dashboard
                                    └──► publish_health_update ──► WS ws:health ──► Dashboard health badges
```

**Technician loop (implemented):**

```
Work Orders: assign → complete → MaintenanceHistory + resolve linked Alert
```

---

## Completed Work (original plan)

| Phase | Scope | Status |
|-------|-------|--------|
| **1 — Rule engine** | `backend/app/rules/` package, ingestion wiring, WS broadcasts on trigger | ✅ Done |
| **2 — Simulator & seed** | Anomaly durations, fuel refill, ignition, P0500/P0115 DTC rules | ✅ Done |
| **3 — Frontend realtime** | WS zombie fix, shared `wsMessages` in App, Alerts/WOs WS + poll | ✅ Done |
| **4 — Backend WS completeness** | GREY→GREEN, alert ack/resolve, WO assign/complete/close publish | ✅ Mostly done (see backlog) |
| **5 — Polish** | `SQL_ECHO`, Mosquitto stdout, `.gitignore`, typed API client | ✅ Done |

### Key files delivered

| File | What it does |
|------|--------------|
| `backend/app/rules/engine.py` | Threshold + DTC evaluation, duration tracking, alert/WO creation, health recompute |
| `backend/app/ingestion/mqtt_service.py` | Direct engine import; GREY→GREEN + `publish_health_update` |
| `backend/app/api/alerts.py` | `publish_alert` on acknowledge/resolve |
| `backend/app/api/workorders.py` | `publish_work_order` on assign/complete/close/create |
| `simulator/fmc150_sim.py` | Realistic anomaly durations, refuel, ignition cycles |
| `frontend/src/hooks/useWebSocket.ts` | Intentional-close guard against zombie reconnect |
| `frontend/src/App.tsx` | Central WS; passes `wsMessages` to Dashboard, Alerts, Work Orders |
| `frontend/src/pages/AlertsPage.tsx` | WS + 10s polling |
| `frontend/src/pages/WorkOrdersPage.tsx` | WS + 10s polling |
| `frontend/src/pages/DashboardPage.tsx` | Telemetry patch + immediate `ws:health` badge update |
| `frontend/src/api/client.ts` | Fully typed REST methods |

---

## Remaining Backlog

### 🟠 High (correctness / stale UI)

| ID | Issue | Location | Impact |
|----|-------|----------|--------|
| H7 | Health not recomputed when alerts resolve | `alerts.py` resolve/ack; `workorders.py` complete (auto-resolves alert) | Vehicle stays YELLOW/RED until REST poll or new alert; no `publish_health_update` |
| H8 | WO complete doesn't publish resolved alert | `workorders.py:complete` | Alerts page on another tab may miss alert status change until poll |
| H9 | Assets page never auto-refreshes | `AssetsPage.tsx` | Vehicle health and alert counts stale while page open |

### 🟡 Medium (consistency / DX)

| ID | Issue | Location | Fix |
|----|-------|----------|-----|
| M7 | Alert suppress has no WS broadcast | `alerts.py:suppress` | Add `publish_alert` (same as ack/resolve) |
| M8 | WO cancel has no WS broadcast | `workorders.py:cancel` | Add `publish_work_order` |
| M9 | `getFleetHealth()` unused | `client.ts` | Wire into Assets page or remove |
| M10 | README says sidebar shows **"Live"** | `README.md` Step 4 | UI shows "Connected" / "Disconnected" — align docs or UI label |
| M11 | Shared health recompute helper | `_recompute_health` only in `engine.py` | Extract to shared module; call from alert/WO endpoints on resolve |

### 🟢 Low (future / nice-to-have)

| ID | Issue | Suggestion |
|----|-------|------------|
| L6 | No `WsProvider` context | Optional refactor — current App-level `wsMessages` prop works |
| L7 | No automated tests | Add pytest for rule engine + API smoke tests; optional Playwright for E2E |
| L8 | No CI pipeline | GitHub Actions: `compileall`, `npm run build`, docker compose smoke |
| L9 | Auth / multi-tenant | Out of PoC scope; document if production-bound |
| L10 | Alert dedup only checks ACTIVE/ACK | Resolved alert re-triggers immediately — may be intended; document behavior |

---

## Suggested Next Steps (priority order)

1. **Health on resolve** — When an alert is resolved (manually or via WO complete), recompute vehicle health and `publish_health_update`. Also `publish_alert` from WO complete when linked alert is resolved.
2. **Assets page live layer** — Pass `wsMessages` (or poll every 15s) and patch vehicle health / alert counts.
3. **WS on suppress/cancel** — One-liner publishes for parity with other mutations.
4. **Automated tests** — Start with rule engine unit tests (threshold, duration, dedup, DTC).
5. **README alignment** — Fix "Live" vs "Connected" wording.

---

## End-to-End Verification Checklist

Run after changes or fresh deploy:

```bash
docker compose down -v
docker compose up --build
# wait ~60s
```

### Automated

```bash
python -m compileall backend/app
cd frontend && npm run build
```

### Manual (README Step 4 — full loop)

| # | Check | Expected |
|---|-------|----------|
| 1 | Open http://localhost:5173 | Sidebar shows **Connected** (green dot) when WS up |
| 2 | Dashboard | 5 vehicles; GREY→GREEN within 30s; live sensor tiles updating |
| 3 | Wait 3–8 min | Summary cards: Active Alerts > 0; Shadow WOs > 0 |
| 4 | Alerts page (`/alerts`) | New rows appear **without F5** |
| 5 | Work Orders page (`/workorders`) | Shadow WOs appear **without F5** |
| 6 | Click sensor tile → drawer | 1h chart loads with threshold reference lines |
| 7 | Assign + complete a WO | Status changes; maintenance history written (`GET /api/v1/system/history`) |
| 8 | Rules page shadow toggle | New WOs respect mode |
| 9 | `docker compose logs backend` | Rule engine log lines on trigger; no ImportError |
| 10 | `docker compose logs mosquitto` | Connection/auth lines visible (not empty) |
| 11 | StrictMode | No duplicate WS connections (DevTools → Network → WS) |
| 12 | After resolving last alert on a vehicle | Health returns toward GREEN (⚠️ fails today — backlog H7) |

### API spot-checks

```bash
curl -s http://localhost:8000/api/v1/dashboard/summary
curl -s "http://localhost:8000/api/v1/alerts?status=active"
curl -s http://localhost:8000/api/v1/workorders
curl -s http://localhost:8000/api/v1/dashboard/fleet/live
# Expect: 12 sensors per vehicle, live values populated
```

---

## Contract Verification (do not break)

- MQTT topics: `fmc150/{imei}/telemetry`, `fmc150/{imei}/dtc`
- MQTT payload shape matches ingestion parser (nested `{value, unit}` sensors)
- Simulator IMEIs match seed vehicles (`350424061234001`–`005`)
- Sensor types in simulator match seed sensors (`engine_rpm`, `coolant_temperature`, `tire_pressure_fl`, etc.)
- REST paths match `frontend/src/api/client.ts` (`/api/v1/...`)
- WS message shape: `{ channel: "ws:telemetry"|"ws:alerts"|"ws:workorders"|"ws:health", data: {...} }`
- Redis channels match `ws/handler.py` subscriptions
- Work order complete → maintenance history + alert resolve (API correct; WS/health broadcast incomplete — see H7/H8)
- Shadow mode: DB config + runtime `settings.SHADOW_MODE` sync via `/system/shadow-mode`

---

## Success Criteria (PoC complete)

The PoC demo is **functionally complete** today. Full "done" includes backlog items above:

1. ✅ Vehicles stream live sensor data on the dashboard.
2. ✅ Anomalies automatically create alerts and shadow work orders.
3. ✅ Health badges turn YELLOW/RED on affected vehicles.
4. ✅ Alerts and Work Orders pages update in real time.
5. ✅ Technician can assign, complete, and close the loop with maintenance history.
6. ✅ No silent ImportError, no zombie WebSockets, Mosquitto logs visible in compose.
7. ⚠️ Health returns to GREEN/YELLOW correctly when alerts are resolved (H7).
8. ⚠️ Assets page reflects live health (H9).
9. ⚠️ Automated test coverage (L7).
