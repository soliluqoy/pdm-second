/**
 * PREDICT — SensorDetailDrawer
 * Slide-over panel with a 1-hour history chart (threshold reference lines),
 * window stats, and the active trigger rules for one sensor.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertTriangle, X } from 'lucide-react';
import { api } from '../../api/client';
import type { LiveSensorItem, SensorReading, VehicleLiveItem } from '../../types';
import {
  directionOperator,
  formatSensorValue,
  sensorIcon,
  statusStyles,
} from '../../utils/sensors';

interface Props {
  vehicle: VehicleLiveItem;
  sensor: LiveSensorItem;
  onClose: () => void;
}

interface ChartPoint {
  time: string;
  value: number;
}

const severityChip: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  warning: 'bg-amber-100 text-amber-700',
  info: 'bg-blue-100 text-blue-700',
};

export default function SensorDetailDrawer({ vehicle, sensor, onClose }: Props) {
  const [readings, setReadings] = useState<SensorReading[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getVehicleReadings(vehicle.id, sensor.sensor_type, 1)
      .then((data) => {
        if (!cancelled) setReadings(data as SensorReading[]);
      })
      .catch((e) => console.error('Failed to load readings:', e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [vehicle.id, sensor.sensor_type]);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const points: ChartPoint[] = useMemo(
    () =>
      readings.map((r) => ({
        time: new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        value: r.value,
      })),
    [readings]
  );

  const stats = useMemo(() => {
    if (points.length === 0) return null;
    const vals = points.map((p) => p.value);
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    };
  }, [points]);

  // Y domain padded to include thresholds
  const [yMin, yMax] = useMemo(() => {
    const candidates: number[] = [];
    if (stats) candidates.push(stats.min, stats.max);
    if (sensor.warning_threshold != null) candidates.push(sensor.warning_threshold);
    if (sensor.critical_threshold != null) candidates.push(sensor.critical_threshold);
    if (sensor.value != null) candidates.push(sensor.value);
    if (candidates.length === 0) return [0, 1];
    let lo = Math.min(...candidates);
    let hi = Math.max(...candidates);
    const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }, [stats, sensor]);

  const styles = statusStyles[sensor.status];
  const Icon = sensorIcon(sensor.sensor_type);
  const unit = sensor.unit ?? '';
  const op = directionOperator(sensor.direction);
  const gradientId = `grad-${sensor.sensor_type}`;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full sm:w-[540px] h-full bg-white shadow-2xl overflow-y-auto animate-[slideIn_0.2s_ease-out]">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white border-b border-gray-200 px-5 py-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-predict-50 rounded-lg">
              <Icon className="w-5 h-5 text-predict-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{sensor.name}</h2>
              <p className="text-sm text-gray-500">
                {vehicle.name} · {vehicle.license_plate ?? vehicle.imei}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            title="Close (Esc)"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Current value + status */}
          <div className={`rounded-xl border p-4 flex items-center justify-between ${styles.border} ${styles.tileBg}`}>
            <div>
              <p className="text-xs text-gray-500 mb-0.5">Current reading</p>
              <p className="text-3xl font-bold text-gray-900 tabular-nums">
                {formatSensorValue(sensor.value)}
                <span className="text-base font-medium text-gray-500 ml-1">{unit}</span>
              </p>
            </div>
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${styles.badge}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} />
              {styles.label}
            </span>
          </div>

          {/* History chart */}
          <div className="rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Last 60 minutes</h3>
            {loading ? (
              <div className="h-56 flex items-center justify-center text-sm text-gray-400 animate-pulse">
                Loading history…
              </div>
            ) : points.length === 0 ? (
              <div className="h-56 flex items-center justify-center text-sm text-gray-400">
                No readings in the last hour.
              </div>
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={points} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <defs>
                      <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#0e87eb" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#0e87eb" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#9ca3af' }} minTickGap={40} />
                    <YAxis domain={[yMin, yMax]} tick={{ fontSize: 10, fill: '#9ca3af' }} width={50} />
                    <Tooltip
                      formatter={(v: any) => [`${formatSensorValue(Number(v))}${unit}`, sensor.name]}
                      contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    />
                    {/* Danger zone shading */}
                    {sensor.critical_threshold != null && sensor.direction === 'high' && (
                      <ReferenceArea y1={sensor.critical_threshold} y2={yMax} fill="#ef4444" fillOpacity={0.07} />
                    )}
                    {sensor.critical_threshold != null && sensor.direction === 'low' && (
                      <ReferenceArea y1={yMin} y2={sensor.critical_threshold} fill="#ef4444" fillOpacity={0.07} />
                    )}
                    {sensor.warning_threshold != null && (
                      <ReferenceLine
                        y={sensor.warning_threshold}
                        stroke="#f59e0b"
                        strokeDasharray="5 4"
                        label={{ value: `warn ${op}${formatSensorValue(sensor.warning_threshold)}${unit}`, position: 'insideTopRight', fontSize: 10, fill: '#d97706' }}
                      />
                    )}
                    {sensor.critical_threshold != null && (
                      <ReferenceLine
                        y={sensor.critical_threshold}
                        stroke="#ef4444"
                        strokeDasharray="5 4"
                        label={{ value: `crit ${op}${formatSensorValue(sensor.critical_threshold)}${unit}`, position: 'insideBottomRight', fontSize: 10, fill: '#dc2626' }}
                      />
                    )}
                    <Area type="monotone" dataKey="value" stroke="#0e87eb" strokeWidth={2} fill={`url(#${gradientId})`} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Window stats */}
          {stats && (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Min (1h)', v: stats.min },
                { label: 'Avg (1h)', v: stats.avg },
                { label: 'Max (1h)', v: stats.max },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-gray-200 p-3 text-center">
                  <p className="text-xs text-gray-500">{s.label}</p>
                  <p className="text-lg font-semibold text-gray-900 tabular-nums">
                    {formatSensorValue(s.v)}
                    <span className="text-xs font-normal text-gray-500 ml-0.5">{unit}</span>
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Thresholds */}
          <div className="rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Operating thresholds</h3>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                <span className="text-amber-800">Warning trigger</span>
                <span className="font-semibold text-amber-800 tabular-nums">
                  {sensor.warning_threshold != null ? `${op} ${formatSensorValue(sensor.warning_threshold)}${unit}` : '—'}
                </span>
              </div>
              <div className="flex justify-between rounded-lg bg-red-50 border border-red-200 px-3 py-2">
                <span className="text-red-800">Critical trigger</span>
                <span className="font-semibold text-red-800 tabular-nums">
                  {sensor.critical_threshold != null ? `${op} ${formatSensorValue(sensor.critical_threshold)}${unit}` : '—'}
                </span>
              </div>
            </div>
            {sensor.min_value != null && sensor.max_value != null && (
              <p className="text-xs text-gray-400 mt-2">
                Operating range: {formatSensorValue(sensor.min_value)} – {formatSensorValue(sensor.max_value)}{unit}
                {sensor.direction === 'low' ? ' · low values are bad' : ' · high values are bad'}
              </p>
            )}
          </div>

          {/* Trigger rules */}
          <div className="rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">
              Active trigger rules ({sensor.rules.length})
            </h3>
            {sensor.rules.length === 0 ? (
              <p className="text-sm text-gray-400">No rules fire on this sensor.</p>
            ) : (
              <ul className="space-y-2">
                {sensor.rules.map((r) => (
                  <li key={r.id} className="flex items-center gap-2.5 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                    <AlertTriangle className={`w-4 h-4 shrink-0 ${r.severity === 'critical' ? 'text-red-500' : 'text-amber-500'}`} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 truncate">{r.name}</p>
                      <p className="text-xs text-gray-500 tabular-nums">
                        fires when value {r.operator} {formatSensorValue(r.threshold_value)}{unit}
                        {r.duration_seconds > 0 ? ` sustained ${r.duration_seconds}s` : ''}
                      </p>
                    </div>
                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${severityChip[r.severity] ?? severityChip.warning}`}>
                      {r.severity}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
