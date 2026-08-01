/**
 * PREDICT — Dashboard Page
 * Fleet summary + live sensor telemetry grid.
 * Data flow: React Query REST + WebSocket patches; 30s reconciliation.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { LayoutGrid, Rows3, Search } from 'lucide-react';
import { api } from '../api/client';
import SensorDetailDrawer from '../components/dashboard/SensorDetailDrawer';
import TelemetryCatalogPanel from '../components/dashboard/TelemetryCatalogPanel';
import VehicleTelemetryCard from '../components/dashboard/VehicleTelemetryCard';
import Badge from '../components/ui/Badge';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import EmptyState from '../components/ui/EmptyState';
import { useWsSubscription } from '../ws/WsContext';
import { queryKeys } from '../queryClient';
import type { LiveSensorItem, VehicleLiveItem } from '../types';
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
const LAYOUT_KEY = 'predict.dashboard.layout';

function sortFleet(list: VehicleLiveItem[]): VehicleLiveItem[] {
  return [...list].sort((a, b) => {
    const healthDiff = (healthOrder[a.health] ?? 99) - (healthOrder[b.health] ?? 99);
    if (healthDiff !== 0) return healthDiff;
    return (b.active_alert_count ?? 0) - (a.active_alert_count ?? 0);
  });
}

function readLayout(): 'stack' | 'compact' {
  try {
    const v = localStorage.getItem(LAYOUT_KEY);
    return v === 'compact' ? 'compact' : 'stack';
  } catch {
    return 'stack';
  }
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
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<SelectedSensor | null>(null);
  const [search, setSearch] = useState('');
  const [healthFilter, setHealthFilter] = useState<string>('all');
  const [layout, setLayout] = useState<'stack' | 'compact'>(readLayout);

  const summaryQuery = useQuery({
    queryKey: queryKeys.dashboardSummary,
    queryFn: () => api.getDashboardSummary(),
    refetchInterval: 30_000,
  });

  const fleetQuery = useQuery({
    queryKey: queryKeys.fleetLive,
    queryFn: async () => sortFleet(await api.getFleetLive()),
    refetchInterval: 30_000,
  });

  const catalogQuery = useQuery({
    queryKey: queryKeys.telemetryCatalog,
    queryFn: () => api.getTelemetryCatalog(),
    staleTime: Infinity,
  });

  const summary = summaryQuery.data ?? null;
  const fleet = fleetQuery.data ?? [];
  const telemetryCatalog = catalogQuery.data ?? null;
  const loading = summaryQuery.isLoading || fleetQuery.isLoading;

  const setLayoutPref = (next: 'stack' | 'compact') => {
    setLayout(next);
    try {
      localStorage.setItem(LAYOUT_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const patchTelemetry = useCallback(
    (payload: any) => {
      const vehicleId = payload?.vehicle_id;
      const data = payload?.data;
      if (!vehicleId || !data) return;
      queryClient.setQueryData<VehicleLiveItem[]>(queryKeys.fleetLive, (prev) => {
        if (!prev) return prev;
        return prev.map((v) => {
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
        });
      });
    },
    [queryClient]
  );

  useWsSubscription(
    ['ws:telemetry', 'ws:health', 'ws:alerts', 'ws:workorders'],
    (msg) => {
      if (msg.channel === 'ws:telemetry') {
        patchTelemetry(msg.data);
      } else if (msg.channel === 'ws:health') {
        const vehicleId = msg.data?.vehicle_id;
        const health = msg.data?.health;
        if (vehicleId && health) {
          queryClient.setQueryData<VehicleLiveItem[]>(queryKeys.fleetLive, (prev) => {
            if (!prev) return prev;
            return sortFleet(prev.map((v) => (v.id === vehicleId ? { ...v, health } : v)));
          });
        }
        void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
        void queryClient.invalidateQueries({ queryKey: queryKeys.fleetLive });
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
        void queryClient.invalidateQueries({ queryKey: queryKeys.fleetLive });
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
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-gray-200 overflow-hidden">
            <button
              type="button"
              title="Stack layout"
              onClick={() => setLayoutPref('stack')}
              className={`px-2 py-1.5 ${
                layout === 'stack' ? 'bg-predict-50 text-predict-700' : 'bg-white text-gray-500'
              }`}
            >
              <Rows3 className="w-4 h-4" />
            </button>
            <button
              type="button"
              title="Compact grid"
              onClick={() => setLayoutPref('compact')}
              className={`px-2 py-1.5 border-l border-gray-200 ${
                layout === 'compact' ? 'bg-predict-50 text-predict-700' : 'bg-white text-gray-500'
              }`}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>
          {fleet.length > 1 && (
            <>
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
            </>
          )}
        </div>
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
        <div
          className={
            layout === 'compact' ? 'grid grid-cols-1 md:grid-cols-2 gap-4' : 'space-y-4'
          }
        >
          {visibleFleet.map((v) => (
            <VehicleTelemetryCard
              key={v.id}
              vehicle={v}
              onSelectSensor={handleSelectSensor}
              compact={layout === 'compact'}
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
