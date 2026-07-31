/**
 * PREDICT — Dashboard Page
 * Fleet summary cards + live telemetry grid: every running sensor with its
 * current reading, thresholds, and trigger points, updated via WebSocket.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ClipboardList,
  Eye,
  Radio,
  Truck,
} from 'lucide-react';
import { api } from '../api/client';
import SensorDetailDrawer from '../components/dashboard/SensorDetailDrawer';
import VehicleTelemetryCard from '../components/dashboard/VehicleTelemetryCard';
import type {
  DashboardSummary,
  LiveSensorItem,
  VehicleLiveItem,
  WSMessage,
} from '../types';
import { computeSensorStatus } from '../utils/sensors';

interface Props {
  wsMessages: WSMessage[];
}

interface SelectedSensor {
  vehicleId: number;
  sensorType: string;
}

export default function DashboardPage({ wsMessages }: Props) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [fleet, setFleet] = useState<VehicleLiveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SelectedSensor | null>(null);
  const [now, setNow] = useState(Date.now());
  const lastWsIdx = useRef(0);
  const refreshTimer = useRef<number | null>(null);

  // ── Data fetching ──────────────────────────────────────────────────
  const fetchData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, f] = await Promise.all([
        api.getDashboardSummary(),
        api.getFleetLive(),
      ]);
      setSummary(s);
      setFleet(f);
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(true);
    // Slow fallback poll — WS telemetry handles the fast path
    const interval = setInterval(() => fetchData(), 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // 1s ticker for relative "last update" labels
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Debounced full refresh for non-telemetry events (alerts, health, WOs)
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchData(), 1500);
  }, [fetchData]);

  // ── Live WebSocket updates ─────────────────────────────────────────
  const patchTelemetry = useCallback((payload: any) => {
    const vehicleId = payload?.vehicle_id;
    const data = payload?.data;
    if (!vehicleId || !data) return;
    setFleet((prev) =>
      prev.map((v) => {
        if (v.id !== vehicleId) return v;
        const live = data.sensors ?? {};
        const sensors = v.sensors.map((s) => {
          const r = live[s.sensor_type];
          if (!r || r.value === undefined || r.value === null) return s;
          return {
            ...s,
            value: r.value,
            unit: r.unit ?? s.unit,
            status: computeSensorStatus(r.value, s),
          };
        });
        return {
          ...v,
          sensors,
          ignition: data.ignition ?? v.ignition,
          speed: data.gps?.speed ?? v.speed,
          telemetry_timestamp: data.timestamp ?? v.telemetry_timestamp,
          last_seen: data.timestamp ?? v.last_seen,
        };
      })
    );
  }, []);

  useEffect(() => {
    for (let i = lastWsIdx.current; i < wsMessages.length; i++) {
      const msg = wsMessages[i];
      if (msg.channel === 'ws:telemetry') {
        patchTelemetry(msg.data);
      } else if (
        msg.channel === 'ws:alerts' ||
        msg.channel === 'ws:health' ||
        msg.channel === 'ws:workorders'
      ) {
        scheduleRefresh();
      }
    }
    lastWsIdx.current = wsMessages.length;
  }, [wsMessages, patchTelemetry, scheduleRefresh]);

  // ── Selected sensor (derived so it stays live) ─────────────────────
  const selectedVehicle = selected
    ? fleet.find((v) => v.id === selected.vehicleId)
    : undefined;
  const selectedSensor: LiveSensorItem | undefined = selectedVehicle?.sensors.find(
    (s) => s.sensor_type === selected?.sensorType
  );

  const onlineCount = fleet.filter(
    (v) => v.telemetry_timestamp && now - new Date(v.telemetry_timestamp).getTime() <= 30_000
  ).length;

  // ── Loading skeleton ───────────────────────────────────────────────
  if (loading) {
    return (
      <div className="p-6 space-y-5">
        <div className="h-8 w-64 bg-gray-200 rounded-lg animate-pulse" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-28 bg-white rounded-xl border border-gray-200 animate-pulse" />
          ))}
        </div>
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-72 bg-white rounded-xl border border-gray-200 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>
          <p className="text-sm text-gray-500">
            Live sensor telemetry, thresholds, and trigger points across the fleet
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 text-emerald-700 rounded-lg border border-emerald-200">
            <Radio className="w-4 h-4 animate-pulse" />
            <span className="text-sm font-medium tabular-nums">
              {onlineCount}/{fleet.length} streaming
            </span>
          </div>
          {summary?.shadow_mode && (
            <div className="flex items-center gap-2 px-3 py-2 bg-purple-100 text-purple-800 rounded-lg border border-purple-300">
              <Eye className="w-4 h-4" />
              <span className="text-sm font-medium">Shadow Mode</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Summary Cards ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <SummaryCard
          icon={<Truck className="w-6 h-6 text-predict-600" />}
          iconBg="bg-predict-50"
          value={summary?.total_vehicles ?? 0}
          label="Total Vehicles"
          sub={
            <div className="flex gap-2 text-xs">
              {([
                ['bg-emerald-500', summary?.green_count],
                ['bg-amber-500', summary?.yellow_count],
                ['bg-red-500', summary?.red_count],
                ['bg-gray-400', summary?.grey_count],
              ] as const).map(([cls, n], i) => (
                <span key={i} className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${cls}`} />
                  {n ?? 0}
                </span>
              ))}
            </div>
          }
        />
        <SummaryCard
          icon={<AlertTriangle className="w-6 h-6 text-red-600" />}
          iconBg="bg-red-50"
          value={summary?.active_alerts ?? 0}
          label="Active Alerts"
          sub={<p className="text-xs text-red-600">{summary?.critical_alerts ?? 0} critical</p>}
        />
        <SummaryCard
          icon={<ClipboardList className="w-6 h-6 text-blue-600" />}
          iconBg="bg-blue-50"
          value={summary?.open_work_orders ?? 0}
          label="Open Work Orders"
          sub={<p className="text-xs text-blue-600">{summary?.in_progress_work_orders ?? 0} in progress</p>}
        />
        <SummaryCard
          icon={<Eye className="w-6 h-6 text-purple-600" />}
          iconBg="bg-purple-50"
          value={summary?.shadow_work_orders ?? 0}
          label="Shadow Work Orders"
          sub={<p className="text-xs text-purple-600">Pending review</p>}
        />
      </div>

      {/* ── Live Telemetry ─────────────────────────────────────────── */}
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-5 h-5 text-predict-600" />
        <h2 className="text-lg font-semibold text-gray-900">Live Sensor Telemetry</h2>
        <span className="text-xs text-gray-400">— every sensor, its reading, and trigger points</span>
      </div>

      {fleet.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 py-16 text-center text-gray-400">
          No vehicles found. Ensure the simulator is running.
        </div>
      ) : (
        <div className="grid grid-cols-1 2xl:grid-cols-2 gap-5">
          {fleet.map((v) => (
            <VehicleTelemetryCard
              key={v.id}
              vehicle={v}
              now={now}
              onSelectSensor={(s) => setSelected({ vehicleId: v.id, sensorType: s.sensor_type })}
            />
          ))}
        </div>
      )}

      {/* ── Sensor detail drawer ───────────────────────────────────── */}
      {selectedVehicle && selectedSensor && (
        <SensorDetailDrawer
          vehicle={selectedVehicle}
          sensor={selectedSensor}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

// ── Summary card ─────────────────────────────────────────────────────────────
function SummaryCard({
  icon,
  iconBg,
  value,
  label,
  sub,
}: {
  icon: React.ReactNode;
  iconBg: string;
  value: number;
  label: string;
  sub: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-3">
        <div className={`p-2 ${iconBg} rounded-lg`}>{icon}</div>
        <span className="text-3xl font-bold text-gray-900 tabular-nums">{value}</span>
      </div>
      <p className="text-sm text-gray-500">{label}</p>
      <div className="mt-2">{sub}</div>
    </div>
  );
}
