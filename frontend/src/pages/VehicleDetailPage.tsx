/**
 * PREDICT — Vehicle Detail Page
 * Full history (range-picker chart), merged event timeline, and vehicle info.
 * Linked from dashboard cards and the Assets page.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ArrowLeft } from 'lucide-react';
import { api } from '../api/client';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import RelativeTime from '../components/ui/RelativeTime';
import type {
  HistoryPoint,
  SensorHistory,
  TimelineEvent,
  Vehicle,
  VehicleLiveItem,
} from '../types';
import { formatSensorValue } from '../utils/sensors';

const RANGES: { label: string; hours: number }[] = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
];

const healthTone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  green: 'success',
  yellow: 'warning',
  red: 'danger',
  grey: 'neutral',
};

const severityTone: Record<string, 'danger' | 'warning' | 'info' | 'neutral'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
};

type Tab = 'history' | 'timeline';

export default function VehicleDetailPage() {
  const { vehicleId } = useParams<{ vehicleId: string }>();
  const id = Number(vehicleId);

  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [live, setLive] = useState<VehicleLiveItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('history');
  const [hours, setHours] = useState(24);
  const [sensorType, setSensorType] = useState<string>('');
  const [history, setHistory] = useState<SensorHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    setLoading(true);
    setError(null);
    Promise.all([api.getVehicle(id), api.getFleetLive()])
      .then(([v, fleet]) => {
        setVehicle(v);
        const liveItem = fleet.find((x) => x.id === id) ?? null;
        setLive(liveItem);
        // Prefer a sensor that has a live value; else the first configured.
        const preferred =
          liveItem?.sensors.find((s) => s.value != null)?.sensor_type ??
          liveItem?.sensors[0]?.sensor_type ??
          '';
        setSensorType(preferred);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load vehicle'))
      .finally(() => setLoading(false));
  }, [id]);

  const loadHistory = useCallback(async () => {
    if (!Number.isFinite(id) || !sensorType) return;
    setHistoryLoading(true);
    try {
      const h = await api.getSensorHistory(id, sensorType, hours);
      setHistory(h);
    } catch (e) {
      console.error('Failed to load history:', e);
      setHistory(null);
    } finally {
      setHistoryLoading(false);
    }
  }, [id, sensorType, hours]);

  const loadTimeline = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    setTimelineLoading(true);
    try {
      setTimeline(await api.getVehicleTimeline(id, 200));
    } catch (e) {
      console.error('Failed to load timeline:', e);
    } finally {
      setTimelineLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (tab === 'history') loadHistory();
  }, [tab, loadHistory]);

  useEffect(() => {
    if (tab === 'timeline') loadTimeline();
  }, [tab, loadTimeline]);

  const sensorMeta = live?.sensors.find((s) => s.sensor_type === sensorType);

  const chartPoints = useMemo(
    () =>
      (history?.points ?? []).map((p: HistoryPoint) => ({
        time: new Date(p.t).toLocaleString([], {
          month: hours > 48 ? 'short' : undefined,
          day: hours > 48 ? 'numeric' : undefined,
          hour: '2-digit',
          minute: '2-digit',
        }),
        value: p.value,
        min: p.min_value ?? p.value,
        max: p.max_value ?? p.value,
      })),
    [history, hours]
  );

  const stats = useMemo(() => {
    if (!chartPoints.length) return null;
    const vals = chartPoints.map((p) => p.value);
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }, [chartPoints]);

  if (loading) return <LoadingState message="Loading vehicle…" />;
  if (error || !vehicle) {
    return (
      <div className="page-content">
        <EmptyBack message={error ?? 'Vehicle not found'} />
      </div>
    );
  }

  return (
    <div className="page-content">
      <PageHeader
        title={vehicle.name}
        description={`${vehicle.license_plate ?? 'No plate'} · IMEI ${vehicle.imei} · ${(vehicle.device_type || 'fmc001').toUpperCase()}`}
        actions={
          <>
            <Badge tone={healthTone[vehicle.health] ?? 'neutral'}>{vehicle.health}</Badge>
            <Link to="/" className="btn-secondary text-sm flex items-center gap-1.5">
              <ArrowLeft className="w-3.5 h-3.5" /> Dashboard
            </Link>
          </>
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <InfoChip label="Last seen">
          <RelativeTime timestamp={vehicle.last_seen} />
        </InfoChip>
        <InfoChip label="Active alerts">{vehicle.active_alert_count ?? 0}</InfoChip>
        <InfoChip label="Open work orders">{vehicle.open_work_order_count ?? 0}</InfoChip>
        <InfoChip label="Ignition">
          {live?.ignition == null ? '—' : live.ignition ? 'On' : 'Off'}
        </InfoChip>
      </div>

      <div className="flex gap-2 border-b border-gray-200 mb-4">
        {(['history', 'timeline'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px capitalize ${
              tab === t
                ? 'border-predict-500 text-predict-700'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'history' && (
        <div className="panel p-4 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[200px] flex-1">
              <label className="filter-label">Sensor</label>
              <select
                className="filter-select w-full mt-1"
                value={sensorType}
                onChange={(e) => setSensorType(e.target.value)}
              >
                {(live?.sensors ?? []).map((s) => (
                  <option key={s.sensor_type} value={s.sensor_type}>
                    {s.name}{s.unit ? ` (${s.unit})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <button
                  key={r.hours}
                  type="button"
                  onClick={() => setHours(r.hours)}
                  className={`px-2.5 py-1.5 rounded-md text-xs font-medium border ${
                    hours === r.hours
                      ? 'bg-predict-50 border-predict-300 text-predict-700'
                      : 'bg-white border-gray-200 text-gray-600'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            {history && (
              <Badge tone="neutral">resolution: {history.resolution}</Badge>
            )}
          </div>

          {historyLoading ? (
            <div className="h-72 flex items-center justify-center text-sm text-gray-400 animate-pulse">
              Loading history…
            </div>
          ) : chartPoints.length === 0 ? (
            <div className="h-72 flex items-center justify-center text-sm text-gray-400">
              No readings in this window.
            </div>
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartPoints} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <defs>
                    <linearGradient id="hist-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#0e87eb" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#0e87eb" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#9ca3af' }} minTickGap={50} />
                  <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} width={50} />
                  <Tooltip
                    formatter={(v: any) => [
                      `${formatSensorValue(Number(v))}${sensorMeta?.unit ?? ''}`,
                      sensorMeta?.name ?? sensorType,
                    ]}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  {sensorMeta?.warning_threshold != null && (
                    <ReferenceLine
                      y={sensorMeta.warning_threshold}
                      stroke="#f59e0b"
                      strokeDasharray="5 4"
                    />
                  )}
                  {sensorMeta?.critical_threshold != null && (
                    <ReferenceLine
                      y={sensorMeta.critical_threshold}
                      stroke="#ef4444"
                      strokeDasharray="5 4"
                    />
                  )}
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#0e87eb"
                    strokeWidth={2}
                    fill="url(#hist-grad)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {stats && (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Min', v: stats.min },
                { label: 'Avg', v: stats.avg },
                { label: 'Max', v: stats.max },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-gray-200 p-3 text-center">
                  <p className="text-xs text-gray-500">{s.label}</p>
                  <p className="text-lg font-semibold text-gray-900 tabular-nums">
                    {formatSensorValue(s.v)}
                    <span className="text-xs font-normal text-gray-500 ml-0.5">
                      {sensorMeta?.unit ?? ''}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'timeline' && (
        <div className="panel">
          {timelineLoading ? (
            <p className="px-4 py-8 text-sm text-gray-400 text-center animate-pulse">Loading timeline…</p>
          ) : timeline.length === 0 ? (
            <p className="px-4 py-8 text-sm text-gray-500 text-center">No events yet.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {timeline.map((e) => (
                <li key={`${e.kind}-${e.id}`} className="px-4 py-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <Badge tone="neutral">{e.kind.replace('_', ' ')}</Badge>
                      {e.severity && (
                        <Badge tone={severityTone[e.severity] ?? 'neutral'}>{e.severity}</Badge>
                      )}
                      {e.status && <Badge tone="neutral">{e.status}</Badge>}
                    </div>
                    <p className="font-medium text-gray-900">{e.title}</p>
                    {e.description && (
                      <p className="text-sm text-gray-600 mt-0.5 line-clamp-2">{e.description}</p>
                    )}
                    {e.kind === 'alert' && e.work_order_id && (
                      <Link
                        to={`/workorders`}
                        className="text-xs text-predict-600 hover:underline mt-1 inline-block"
                      >
                        Work order #{e.work_order_id}
                      </Link>
                    )}
                    {e.kind === 'work_order' && e.alert_id && (
                      <Link
                        to={`/alerts?highlight=${e.alert_id}`}
                        className="text-xs text-predict-600 hover:underline mt-1 inline-block"
                      >
                        Alert #{e.alert_id}
                      </Link>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 shrink-0 tabular-nums">
                    {new Date(e.timestamp).toLocaleString()}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function InfoChip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm font-medium text-gray-900 mt-0.5">{children}</p>
    </div>
  );
}

function EmptyBack({ message }: { message: string }) {
  return (
    <div className="text-center py-16">
      <p className="text-gray-600">{message}</p>
      <Link to="/" className="btn-primary mt-4 inline-block">Back to dashboard</Link>
    </div>
  );
}
