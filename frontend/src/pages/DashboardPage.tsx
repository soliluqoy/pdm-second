/**
 * PREDICT — Dashboard Page
 * Fleet summary + live sensor telemetry grid.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import SensorDetailDrawer from '../components/dashboard/SensorDetailDrawer';
import TelemetryCatalogPanel from '../components/dashboard/TelemetryCatalogPanel';
import VehicleTelemetryCard from '../components/dashboard/VehicleTelemetryCard';
import Badge from '../components/ui/Badge';
import PageHeader from '../components/ui/PageHeader';
import StatCard from '../components/ui/StatCard';
import EmptyState from '../components/ui/EmptyState';
import type {
  DashboardSummary,
  LiveSensorItem,
  TelemetryCatalog,
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

const healthOrder: Record<string, number> = {
  red: 0,
  yellow: 1,
  green: 2,
  grey: 3,
};

export default function DashboardPage({ wsMessages }: Props) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [fleet, setFleet] = useState<VehicleLiveItem[]>([]);
  const [telemetryCatalog, setTelemetryCatalog] = useState<TelemetryCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<SelectedSensor | null>(null);
  const [now, setNow] = useState(Date.now());
  const lastWsIdx = useRef(0);
  const refreshTimer = useRef<number | null>(null);

  const fetchData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [s, f, catalog] = await Promise.all([
        api.getDashboardSummary(),
        api.getFleetLive(),
        api.getTelemetryCatalog(),
      ]);
      setSummary(s);
      setTelemetryCatalog(catalog);
      setFleet(
        [...f].sort((a, b) => {
          const healthDiff = (healthOrder[a.health] ?? 99) - (healthOrder[b.health] ?? 99);
          if (healthDiff !== 0) return healthDiff;
          return (b.active_alert_count ?? 0) - (a.active_alert_count ?? 0);
        })
      );
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(true);
    const interval = setInterval(() => fetchData(), 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
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

  useEffect(() => {
    for (let i = lastWsIdx.current; i < wsMessages.length; i++) {
      const msg = wsMessages[i];
      if (msg.channel === 'ws:telemetry') {
        patchTelemetry(msg.data);
      } else if (msg.channel === 'ws:health') {
        const vehicleId = msg.data?.vehicle_id;
        const health = msg.data?.health;
        if (vehicleId && health) {
          setFleet((prev) =>
            prev.map((v) => (v.id === vehicleId ? { ...v, health } : v))
          );
        }
        scheduleRefresh();
      } else if (msg.channel === 'ws:alerts' || msg.channel === 'ws:workorders') {
        scheduleRefresh();
      }
    }
    lastWsIdx.current = wsMessages.length;
  }, [wsMessages, patchTelemetry, scheduleRefresh]);

  const selectedVehicle = selected
    ? fleet.find((v) => v.id === selected.vehicleId)
    : undefined;
  const selectedSensor: LiveSensorItem | undefined = selectedVehicle?.sensors.find(
    (s) => s.sensor_type === selected?.sensorType
  );

  const onlineCount = fleet.filter(
    (v) => v.telemetry_timestamp && now - new Date(v.telemetry_timestamp).getTime() <= 30_000
  ).length;

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
            <Badge tone={onlineCount > 0 ? 'success' : 'neutral'}>
              {onlineCount} of {fleet.length} live
            </Badge>
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
              {summary?.red_count ?? 0} critical · {summary?.grey_count ?? 0} unknown
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

      <h2 className="section-title">Live telemetry</h2>
      <p className="text-sm text-gray-600 mb-4">Click a sensor for history and thresholds.</p>

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
      ) : (
        <div className="space-y-4">
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
