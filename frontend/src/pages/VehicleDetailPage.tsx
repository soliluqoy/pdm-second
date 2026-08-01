/**
 * PREDICT — Vehicle Detail Page
 * History (multi-sensor / custom range / bands / CSV), timeline, and assets.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ArrowLeft, Download } from 'lucide-react';
import { api } from '../api/client';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import RelativeTime from '../components/ui/RelativeTime';
import { queryKeys } from '../queryClient';
import type {
  Component,
  HistoryPoint,
  Sensor,
  SensorHistory,
  TimelineEvent,
} from '../types';
import { formatSensorValue } from '../utils/sensors';

const RANGES: { label: string; hours: number }[] = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
];

const SERIES_COLORS = ['#0e87eb', '#10b981', '#f59e0b', '#8b5cf6'];
const MAX_SENSORS = 4;
const TIMELINE_PAGE = 100;

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

const kindTone: Record<string, 'danger' | 'warning' | 'info' | 'neutral' | 'success' | 'purple'> = {
  alert: 'danger',
  work_order: 'info',
  maintenance: 'success',
  health: 'neutral',
  dtc: 'warning',
  driving: 'purple',
};

type Tab = 'history' | 'timeline' | 'assets';

interface ThresholdDraft {
  warning: string;
  critical: string;
}

export default function VehicleDetailPage() {
  const { vehicleId } = useParams<{ vehicleId: string }>();
  const id = Number(vehicleId);
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const initialTab = (searchParams.get('tab') as Tab) || 'history';
  const initialSensor = searchParams.get('sensor') || '';

  const [tab, setTab] = useState<Tab>(
    ['history', 'timeline', 'assets'].includes(initialTab) ? initialTab : 'history'
  );
  const [hours, setHours] = useState(24);
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [useCustom, setUseCustom] = useState(false);
  const [selectedSensors, setSelectedSensors] = useState<string[]>(
    initialSensor ? [initialSensor] : []
  );
  const [histories, setHistories] = useState<Record<string, SensorHistory>>({});
  const [historyLoading, setHistoryLoading] = useState(false);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineHasMore, setTimelineHasMore] = useState(false);
  const [components, setComponents] = useState<Component[]>([]);
  const [selectedComponent, setSelectedComponent] = useState<Component | null>(null);
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [editingSensor, setEditingSensor] = useState<number | null>(null);
  const [thresholdDraft, setThresholdDraft] = useState<ThresholdDraft>({ warning: '', critical: '' });
  const [sensorError, setSensorError] = useState<string | null>(null);

  const vehicleQuery = useQuery({
    queryKey: queryKeys.vehicle(id),
    queryFn: () => api.getVehicle(id),
    enabled: Number.isFinite(id),
  });

  const fleetQuery = useQuery({
    queryKey: queryKeys.fleetLive,
    queryFn: () => api.getFleetLive(),
    enabled: Number.isFinite(id),
  });

  const vehicle = vehicleQuery.data ?? null;
  const live = fleetQuery.data?.find((x) => x.id === id) ?? null;
  const loading = vehicleQuery.isLoading || fleetQuery.isLoading;
  const error = vehicleQuery.error
    ? vehicleQuery.error instanceof Error
      ? vehicleQuery.error.message
      : 'Failed to load vehicle'
    : null;

  // Seed selected sensors from live data / deep link
  useEffect(() => {
    if (!live?.sensors.length) return;
    setSelectedSensors((prev) => {
      if (prev.length) {
        const valid = prev.filter((s) => live.sensors.some((x) => x.sensor_type === s));
        return valid.length ? valid.slice(0, MAX_SENSORS) : prev;
      }
      if (initialSensor && live.sensors.some((s) => s.sensor_type === initialSensor)) {
        return [initialSensor];
      }
      const preferred =
        live.sensors.find((s) => s.value != null)?.sensor_type ??
        live.sensors[0]?.sensor_type;
      return preferred ? [preferred] : [];
    });
  }, [live, initialSensor]);

  const range = useMemo(() => {
    if (useCustom && customFrom && customTo) {
      return {
        from: new Date(customFrom).toISOString(),
        to: new Date(customTo).toISOString(),
      };
    }
    return undefined;
  }, [useCustom, customFrom, customTo]);

  const loadHistory = useCallback(async () => {
    if (!Number.isFinite(id) || !selectedSensors.length) return;
    setHistoryLoading(true);
    try {
      const entries = await Promise.all(
        selectedSensors.map(async (st) => {
          const h = await api.getSensorHistory(id, st, hours, 'auto', range);
          return [st, h] as const;
        })
      );
      setHistories(Object.fromEntries(entries));
    } catch (e) {
      console.error('Failed to load history:', e);
      setHistories({});
    } finally {
      setHistoryLoading(false);
    }
  }, [id, selectedSensors, hours, range]);

  const loadTimeline = useCallback(async (append = false) => {
    if (!Number.isFinite(id)) return;
    setTimelineLoading(true);
    try {
      const skip = append ? timeline.length : 0;
      const page = await api.getVehicleTimeline(id, TIMELINE_PAGE, skip);
      setTimeline((prev) => (append ? [...prev, ...page] : page));
      setTimelineHasMore(page.length === TIMELINE_PAGE);
    } catch (e) {
      console.error('Failed to load timeline:', e);
    } finally {
      setTimelineLoading(false);
    }
  }, [id, timeline.length]);

  const loadAssets = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      const c = await api.getComponents(id);
      setComponents(c);
      setSelectedComponent(null);
      setSensors([]);
    } catch (e) {
      console.error('Failed to load components:', e);
    }
  }, [id]);

  useEffect(() => {
    if (tab === 'history') void loadHistory();
  }, [tab, loadHistory]);

  useEffect(() => {
    if (tab === 'timeline') void loadTimeline(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, id]);

  useEffect(() => {
    if (tab === 'assets') void loadAssets();
  }, [tab, loadAssets]);

  const switchTab = (t: Tab) => {
    setTab(t);
    const next = new URLSearchParams(searchParams);
    next.set('tab', t);
    if (selectedSensors[0]) next.set('sensor', selectedSensors[0]);
    setSearchParams(next, { replace: true });
  };

  const toggleSensor = (st: string) => {
    setSelectedSensors((prev) => {
      if (prev.includes(st)) {
        if (prev.length === 1) return prev;
        return prev.filter((x) => x !== st);
      }
      if (prev.length >= MAX_SENSORS) return prev;
      return [...prev, st];
    });
  };

  const primarySensor = selectedSensors[0] ?? '';
  const primaryMeta = live?.sensors.find((s) => s.sensor_type === primarySensor);
  const primaryHistory = histories[primarySensor];

  const chartPoints = useMemo(() => {
    if (!selectedSensors.length) return [];
    const byTs = new Map<string, Record<string, number | string>>();
    for (const st of selectedSensors) {
      const pts = histories[st]?.points ?? [];
      for (const p of pts) {
        const key = p.t;
        const row = byTs.get(key) ?? { t: key };
        row[st] = p.value;
        if (st === primarySensor) {
          row.min = p.min_value ?? p.value;
          row.max = p.max_value ?? p.value;
          row.bandBase = p.min_value ?? p.value;
          row.bandSize = (p.max_value ?? p.value) - (p.min_value ?? p.value);
        }
        byTs.set(key, row);
      }
    }
    const sorted = [...byTs.entries()].sort(([a], [b]) => a.localeCompare(b));
    const spanHours = useCustom && range
      ? (new Date(range.to).getTime() - new Date(range.from).getTime()) / 3_600_000
      : hours;
    return sorted.map(([, row]) => ({
      ...row,
      time: new Date(String(row.t)).toLocaleString([], {
        month: spanHours > 48 ? 'short' : undefined,
        day: spanHours > 48 ? 'numeric' : undefined,
        hour: '2-digit',
        minute: '2-digit',
      }),
    }));
  }, [histories, selectedSensors, primarySensor, hours, useCustom, range]);

  const showBand =
    !!primaryHistory &&
    primaryHistory.resolution !== 'raw' &&
    chartPoints.some((p) => {
      const size = (p as Record<string, unknown>).bandSize;
      return typeof size === 'number' && size > 0;
    });

  const stats = useMemo(() => {
    const pts = (primaryHistory?.points ?? []) as HistoryPoint[];
    if (!pts.length) return null;
    const vals = pts.map((p) => p.value);
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }, [primaryHistory]);

  const downloadCsv = () => {
    if (!primarySensor) return;
    const url = api.sensorHistoryCsvUrl(id, primarySensor, hours, 'auto', range);
    window.open(url, '_blank');
  };

  const selectComponent = async (c: Component) => {
    setSelectedComponent(c);
    setEditingSensor(null);
    try {
      setSensors(await api.getSensors(c.id));
    } catch (e) {
      console.error('Failed to fetch sensors:', e);
      setSensors([]);
    }
  };

  const startEditThresholds = (s: Sensor) => {
    setEditingSensor(s.id);
    setSensorError(null);
    setThresholdDraft({
      warning: s.warning_threshold != null ? String(s.warning_threshold) : '',
      critical: s.critical_threshold != null ? String(s.critical_threshold) : '',
    });
  };

  const saveThresholds = async (s: Sensor) => {
    setSensorError(null);
    const warning = thresholdDraft.warning.trim() === '' ? null : Number(thresholdDraft.warning);
    const critical = thresholdDraft.critical.trim() === '' ? null : Number(thresholdDraft.critical);
    if ((warning != null && Number.isNaN(warning)) || (critical != null && Number.isNaN(critical))) {
      setSensorError('Thresholds must be numbers.');
      return;
    }
    try {
      const updated = await api.updateSensor(s.id, {
        warning_threshold: warning,
        critical_threshold: critical,
      });
      setSensors((prev) => prev.map((x) => (x.id === s.id ? updated : x)));
      setEditingSensor(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.fleetLive });
    } catch (e) {
      setSensorError(e instanceof Error ? e.message : 'Failed to save thresholds');
    }
  };

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
        {(['history', 'timeline', 'assets'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => switchTab(t)}
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
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <button
                  key={r.hours}
                  type="button"
                  onClick={() => {
                    setHours(r.hours);
                    setUseCustom(false);
                  }}
                  className={`px-2.5 py-1.5 rounded-md text-xs font-medium border ${
                    !useCustom && hours === r.hours
                      ? 'bg-predict-50 border-predict-300 text-predict-700'
                      : 'bg-white border-gray-200 text-gray-600'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label className="filter-label">From</label>
                <input
                  type="datetime-local"
                  className="filter-select mt-1 text-xs"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                />
              </div>
              <div>
                <label className="filter-label">To</label>
                <input
                  type="datetime-local"
                  className="filter-select mt-1 text-xs"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                />
              </div>
              <button
                type="button"
                className="btn-secondary text-xs"
                disabled={!customFrom || !customTo}
                onClick={() => setUseCustom(true)}
              >
                Apply range
              </button>
            </div>
            {primaryHistory && (
              <Badge tone="neutral">resolution: {primaryHistory.resolution}</Badge>
            )}
            <button
              type="button"
              className="btn-secondary text-xs flex items-center gap-1 ml-auto"
              onClick={downloadCsv}
              disabled={!primarySensor}
            >
              <Download className="w-3.5 h-3.5" /> CSV
            </button>
          </div>

          <div>
            <p className="filter-label mb-1.5">
              Sensors (up to {MAX_SENSORS}) — first selected is primary (bands / CSV)
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(live?.sensors ?? []).map((s) => {
                const active = selectedSensors.includes(s.sensor_type);
                const idx = selectedSensors.indexOf(s.sensor_type);
                return (
                  <button
                    key={s.sensor_type}
                    type="button"
                    onClick={() => toggleSensor(s.sensor_type)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium border ${
                      active
                        ? 'border-transparent text-white'
                        : 'bg-white border-gray-200 text-gray-600'
                    }`}
                    style={
                      active
                        ? { backgroundColor: SERIES_COLORS[idx] ?? SERIES_COLORS[0] }
                        : undefined
                    }
                  >
                    {s.name}
                  </button>
                );
              })}
            </div>
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
                <ComposedChart data={chartPoints} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <defs>
                    <linearGradient id="band-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#0e87eb" stopOpacity={0.2} />
                      <stop offset="100%" stopColor="#0e87eb" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#9ca3af' }} minTickGap={50} />
                  <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} width={50} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  {primaryMeta?.warning_threshold != null && (
                    <ReferenceLine y={primaryMeta.warning_threshold} stroke="#f59e0b" strokeDasharray="5 4" />
                  )}
                  {primaryMeta?.critical_threshold != null && (
                    <ReferenceLine y={primaryMeta.critical_threshold} stroke="#ef4444" strokeDasharray="5 4" />
                  )}
                  {showBand && (
                    <Area
                      type="monotone"
                      dataKey="bandBase"
                      stackId="band"
                      stroke="none"
                      fill="transparent"
                      legendType="none"
                      isAnimationActive={false}
                    />
                  )}
                  {showBand && (
                    <Area
                      type="monotone"
                      dataKey="bandSize"
                      stackId="band"
                      stroke="none"
                      fill="url(#band-grad)"
                      legendType="none"
                      isAnimationActive={false}
                    />
                  )}
                  {selectedSensors.map((st, i) => (
                    <Line
                      key={st}
                      type="monotone"
                      dataKey={st}
                      name={live?.sensors.find((s) => s.sensor_type === st)?.name ?? st}
                      stroke={SERIES_COLORS[i] ?? SERIES_COLORS[0]}
                      strokeWidth={i === 0 ? 2 : 1.5}
                      dot={false}
                      connectNulls
                    />
                  ))}
                </ComposedChart>
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
                  <p className="text-xs text-gray-500">{s.label} (primary)</p>
                  <p className="text-lg font-semibold text-gray-900 tabular-nums">
                    {formatSensorValue(s.v)}
                    <span className="text-xs font-normal text-gray-500 ml-0.5">
                      {primaryMeta?.unit ?? ''}
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
          {timelineLoading && timeline.length === 0 ? (
            <p className="px-4 py-8 text-sm text-gray-400 text-center animate-pulse">Loading timeline…</p>
          ) : timeline.length === 0 ? (
            <p className="px-4 py-8 text-sm text-gray-500 text-center">No events yet.</p>
          ) : (
            <>
              <ul className="divide-y divide-gray-100">
                {timeline.map((e) => (
                  <li key={`${e.kind}-${e.id}`} className="px-4 py-3 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <Badge tone={kindTone[e.kind] ?? 'neutral'}>{e.kind.replace('_', ' ')}</Badge>
                        {e.severity && (
                          <Badge tone={severityTone[e.severity] ?? 'neutral'}>{e.severity}</Badge>
                        )}
                        {e.status && e.kind !== 'health' && (
                          <Badge tone="neutral">{e.status}</Badge>
                        )}
                        {e.kind === 'health' && e.status && (
                          <Badge tone={healthTone[e.status] ?? 'neutral'}>{e.status}</Badge>
                        )}
                      </div>
                      <p className="font-medium text-gray-900">{e.title}</p>
                      {e.description && (
                        <p className="text-sm text-gray-600 mt-0.5 line-clamp-2">{e.description}</p>
                      )}
                      {e.kind === 'alert' && e.work_order_id && (
                        <Link
                          to="/workorders"
                          className="text-xs text-predict-600 hover:underline mt-1 inline-block"
                        >
                          Work order #{e.work_order_id}
                        </Link>
                      )}
                      {(e.kind === 'work_order' || e.kind === 'dtc') && e.alert_id && (
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
              {timelineHasMore && (
                <div className="text-center py-3 border-t border-gray-100">
                  <button
                    type="button"
                    className="btn-secondary text-sm"
                    disabled={timelineLoading}
                    onClick={() => void loadTimeline(true)}
                  >
                    {timelineLoading ? 'Loading…' : 'Load more'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'assets' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <section className="panel">
            <header className="px-4 py-3 border-b border-gray-200">
              <h2 className="font-semibold text-gray-900">Components</h2>
            </header>
            <div className="max-h-[420px] overflow-y-auto">
              {components.length === 0 ? (
                <p className="px-4 py-8 text-sm text-gray-500 text-center">No components</p>
              ) : (
                components.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => void selectComponent(c)}
                    className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 ${
                      selectedComponent?.id === c.id ? 'bg-predict-50 border-l-4 border-l-predict-500' : ''
                    }`}
                  >
                    <p className="font-medium text-gray-900">{c.name}</p>
                    <p className="text-sm text-gray-600">
                      {c.component_type} · {c.sensor_count} sensors
                    </p>
                  </button>
                ))
              )}
            </div>
          </section>

          <section className="panel">
            <header className="px-4 py-3 border-b border-gray-200">
              <h2 className="font-semibold text-gray-900">Sensors</h2>
            </header>
            <div className="max-h-[420px] overflow-y-auto">
              {!selectedComponent ? (
                <p className="px-4 py-8 text-sm text-gray-500 text-center">Select a component</p>
              ) : sensors.length === 0 ? (
                <p className="px-4 py-8 text-sm text-gray-500 text-center">No sensors</p>
              ) : (
                sensors.map((s) => (
                  <div key={s.id} className="px-4 py-3 border-b border-gray-100">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-medium text-gray-900">{s.name}</p>
                        <p className="text-sm text-gray-600">
                          {s.sensor_type} · {s.unit || '—'}
                        </p>
                      </div>
                      {editingSensor !== s.id && (
                        <button
                          type="button"
                          className="btn-secondary text-xs"
                          onClick={() => startEditThresholds(s)}
                        >
                          Edit
                        </button>
                      )}
                    </div>
                    {editingSensor === s.id ? (
                      <div className="mt-2 space-y-2">
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="text-xs text-gray-500">Warning</label>
                            <input
                              type="number"
                              className="filter-select w-full mt-0.5 text-sm"
                              value={thresholdDraft.warning}
                              onChange={(e) =>
                                setThresholdDraft((d) => ({ ...d, warning: e.target.value }))
                              }
                            />
                          </div>
                          <div>
                            <label className="text-xs text-gray-500">Critical</label>
                            <input
                              type="number"
                              className="filter-select w-full mt-0.5 text-sm"
                              value={thresholdDraft.critical}
                              onChange={(e) =>
                                setThresholdDraft((d) => ({ ...d, critical: e.target.value }))
                              }
                            />
                          </div>
                        </div>
                        {sensorError && <p className="text-xs text-red-700">{sensorError}</p>}
                        <div className="flex gap-2">
                          <button type="button" className="btn-primary text-xs" onClick={() => void saveThresholds(s)}>
                            Save
                          </button>
                          <button type="button" className="btn-secondary text-xs" onClick={() => setEditingSensor(null)}>
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <dl className="mt-2 text-sm space-y-1">
                        <div className="flex justify-between gap-4">
                          <dt className="text-gray-500">Warning</dt>
                          <dd className="text-amber-700 tabular-nums">
                            {s.warning_threshold != null ? `${s.warning_threshold}${s.unit || ''}` : '—'}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4">
                          <dt className="text-gray-500">Critical</dt>
                          <dd className="text-red-700 tabular-nums">
                            {s.critical_threshold != null ? `${s.critical_threshold}${s.unit || ''}` : '—'}
                          </dd>
                        </div>
                      </dl>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
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
