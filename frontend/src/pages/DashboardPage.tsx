/**
 * PREDICT — Dashboard Page
 * Fleet summary + live sensor telemetry grid.
 * Data flow: initial REST load + WebSocket patches; 30s REST reconciliation.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../api/client';
import SensorDetailDrawer from '../components/dashboard/SensorDetailDrawer';
import TelemetryCatalogPanel from '../components/dashboard/TelemetryCatalogPanel';
import VehicleTelemetryCard from '../components/dashboard/VehicleTelemetryCard';
import Badge from '../components/ui/Badge';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import EmptyState from '../components/ui/EmptyState';
import { useWsSubscription } from '../ws/WsContext';
import type {
  DashboardSummary,
  LiveSensorItem,
  TelemetryCatalog,
  VehicleLiveItem,
} from '../types';
import { computeSensorStatus } from '../utils/sensors';

interface SelectedSensor {
  vehicleId: number;
  sensorType: string;
}

const healthOrder: Record<string, number> = {
  red: 0,
  yellow: 1,
  green: 2,
  grey: 3,
};

const healthFilters = ['all', 'red', 'yellow', 'green', 'grey'] as const;

function sortFleet(list: VehicleLiveItem[]): VehicleLiveItem[] {
  return [...list].sort((a, b) => {
    const healthDiff = (healthOrder[a.health] ?? 99) - (healthOrder[b.health] ?? 99);
    if (healthDiff !== 0) return healthDiff;
    return (b.active_alert_count ?? 0) - (a.active_alert_count ?? 0);
  });
}

/** "N of M live" badge with its own clock so the page doesn't tick. */
function LiveCountBadge({ fleet }: { fleet: VehicleLiveItem[] }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);
  const online = fleet.filter(
    (v) => v.telemetry_timestamp && now - new Date(v.telemetry_timestamp).getTime() <= 30_000
  ).length;
  return (
    <Badge tone={online > 0 ? 'success' : 'neutral'}>
      {online} of {fleet.length} live
    </Badge>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [fleet, setFleet] = useState<VehicleLiveItem[]>([]);
  const [telemetryCatalog, setTelemetryCatalog] = useState<TelemetryCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SelectedSensor | null>(null);
  const [search, setSearch] = useState('');
  const [healthFilter, setHealthFilter] = useState<string>('all');
  const refreshTimer = useRef<number | null>(null);

  const fetchData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, f] = await Promise.all([
        api.getDashboardSummary(),
        api.getFleetLive(),
      ]);
      setSummary(s);
      setFleet(sortFleet(f));
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(true);
    // Reconciliation poll: WS is the primary update path.
    const interval = setInterval(() => fetchData(), 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // The telemetry catalog is static — fetch it once.
  useEffect(() => {
    api.getTelemetryCatalog().then(setTelemetryCatalog).catch(console.error);
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchData(), 1500);
  }, [fetchData]);

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

  useWsSubscription(
    ['ws:telemetry', 'ws:health', 'ws:alerts', 'ws:workorders'],
    (msg) => {
      if (msg.channel === 'ws:telemetry') {
        patchTelemetry(msg.data);
      } else if (msg.channel === 'ws:health') {
        const vehicleId = msg.data?.vehicle_id;
        const health = msg.data?.health;
        if (vehicleId && health) {
          setFleet((prev) =>
            sortFleet(prev.map((v) => (v.id === vehicleId ? { ...v, health } : v)))
          );
        }
        scheduleRefresh();
      } else {
        scheduleRefresh();
      }
    }
  );

  const visibleFleet = useMemo(() => {
    const q = search.trim().toLowerCase();
    return fleet.filter((v) => {
      if (healthFilter !== 'all' && v.health !== healthFilter) return false;
      if (!q) return true;
      return (
        v.name.toLowerCase().includes(q) ||
        (v.license_plate ?? '').toLowerCase().includes(q) ||
        v.imei.includes(q)
      );
    });
  }, [fleet, search, healthFilter]);

  const selectedVehicle = selected
    ? fleet.find((v) => v.id === selected.vehicleId)
    : undefined;
  const selectedSensor: LiveSensorItem | undefined = selectedVehicle?.sensors.find(
    (s) => s.sensor_type === selected?.sensorType
  );

  const handleSelectSensor = useCallback(
    (vehicleId: number, sensor: LiveSensorItem) =>
      setSelected({ vehicleId, sensorType: sensor.sensor_type }),
    []
  );

  if (loading) {
    return (
      <div className="page-content space-y-4">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-lg animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Dashboard"
        description="Fleet health, alerts, and live sensor readings"
        actions={
          <>
            <LiveCountBadge fleet={fleet} />
            {summary?.shadow_mode && <Badge tone="purple">Shadow mode on</Badge>}
          </>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Vehicles"
          value={summary?.total_vehicles ?? 0}
          detail={
            <span>
              {summary?.green_count ?? 0} healthy · {summary?.yellow_count ?? 0} warning ·{' '}
              {summary?.red_count ?? 0} critical · {summary?.grey_count ?? 0} offline
            </span>
          }
        />
        <StatCard
          label="Active alerts"
          value={summary?.active_alerts ?? 0}
          detail={`${summary?.critical_alerts ?? 0} critical`}
        />
        <StatCard
          label="Open work orders"
          value={summary?.open_work_orders ?? 0}
          detail={`${summary?.in_progress_work_orders ?? 0} in progress`}
        />
        <StatCard
          label="Shadow work orders"
          value={summary?.shadow_work_orders ?? 0}
          detail="Pending review"
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="section-title mb-0">Live telemetry</h2>
          <p className="text-sm text-gray-600">Click a sensor for history and thresholds.</p>
        </div>
        {fleet.length > 1 && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Name, plate, IMEI…"
                className="filter-select pl-8 w-48"
              />
            </div>
            {healthFilters.map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setHealthFilter(h)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-medium capitalize border ${
                  healthFilter === h
                    ? 'bg-predict-50 border-predict-300 text-predict-700'
                    : 'bg-white border-gray-200 text-gray-600 hover:text-gray-900'
                }`}
              >
                {h}
              </button>
            ))}
          </div>
        )}
      </div>

      {fleet.length === 0 ? (
        <>
          <EmptyState message="No vehicles yet. Open Assets → Register vehicle (IMEI + device type), then configure the tracker via SMS." />
          {telemetryCatalog && (
            <TelemetryCatalogPanel
              catalog={telemetryCatalog.models}
              note={telemetryCatalog.note}
            />
          )}
        </>
      ) : visibleFleet.length === 0 ? (
        <EmptyState message="No vehicles match your filter." />
      ) : (
        <div className="space-y-4">
          {visibleFleet.map((v) => (
            <VehicleTelemetryCard
              key={v.id}
              vehicle={v}
              onSelectSensor={handleSelectSensor}
            />
          ))}
        </div>
      )}

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
