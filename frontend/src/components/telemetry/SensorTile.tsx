/**
 * PREDICT — Sensor Tile
 * One sensor: live reading, gauge bar with threshold markers + danger zones,
 * threshold caption, and the active rule trigger points.
 */
import type { SensorTelemetryItem } from '../../types';
import {
  Activity,
  BatteryCharging,
  Cog,
  Disc,
  Disc3,
  Droplets,
  Fuel,
  Gauge,
  Navigation,
  Route,
  Thermometer,
  Timer,
  Zap,
} from 'lucide-react';

const SENSOR_ICONS: Record<string, any> = {
  engine_rpm: Gauge,
  coolant_temperature: Thermometer,
  engine_load: Activity,
  oil_pressure: Droplets,
  transmission_temperature: Cog,
  brake_pressure: Disc,
  tire_pressure_fl: Disc3,
  battery_voltage: BatteryCharging,
  vehicle_speed: Navigation,
  fuel_level: Fuel,
  odometer: Route,
  engine_hours: Timer,
};

const STATUS_STYLES: Record<
  string,
  { tile: string; value: string; fill: string; dot: string; label: string }
> = {
  normal: {
    tile: 'border-gray-200 bg-white',
    value: 'text-gray-900',
    fill: 'bg-emerald-500',
    dot: 'bg-emerald-500',
    label: 'Normal',
  },
  warning: {
    tile: 'border-amber-300 bg-amber-50/50',
    value: 'text-amber-700',
    fill: 'bg-amber-500',
    dot: 'bg-amber-500',
    label: 'Warning threshold crossed',
  },
  critical: {
    tile: 'border-red-300 bg-red-50/60',
    value: 'text-red-700',
    fill: 'bg-red-500',
    dot: 'bg-red-500 animate-pulse',
    label: 'Critical threshold crossed',
  },
  no_data: {
    tile: 'border-gray-200 bg-gray-50',
    value: 'text-gray-400',
    fill: 'bg-gray-300',
    dot: 'bg-gray-300',
    label: 'No data',
  },
};

const SEVERITY_CHIP: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  warning: 'bg-amber-100 text-amber-700 border-amber-200',
  info: 'bg-blue-100 text-blue-700 border-blue-200',
};

const fmtValue = (v?: number) =>
  v == null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: 1 });

const fmtThreshold = (v?: number | null) =>
  v == null ? null : Number.isInteger(v) ? String(v) : v.toFixed(1);

const fmtDuration = (s: number) => {
  if (!s) return 'instant';
  if (s < 60) return `${s}s`;
  if (s % 60 === 0) return `${s / 60}m`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
};

export default function SensorTile({ sensor }: { sensor: SensorTelemetryItem }) {
  const Icon = SENSOR_ICONS[sensor.sensor_type] || Gauge;
  const style = STATUS_STYLES[sensor.status] || STATUS_STYLES.no_data;

  const { min_value: min, max_value: max, warning_threshold: warn, critical_threshold: crit } = sensor;
  const hasScale = min != null && max != null && max > min;
  const pct = (v: number) =>
    hasScale ? Math.min(100, Math.max(0, ((v - (min as number)) / ((max as number) - (min as number))) * 100)) : 0;

  const op = sensor.direction === 'low' ? '<' : '>';
  const warnTxt = fmtThreshold(warn);
  const critTxt = fmtThreshold(crit);

  return (
    <div className={`rounded-lg border p-3 transition-colors ${style.tile}`}>
      {/* Name + status dot */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Icon className="w-4 h-4 text-gray-400 shrink-0" />
          <span className="text-xs font-medium text-gray-600 truncate" title={sensor.name}>
            {sensor.name}
          </span>
        </div>
        <span className={`w-2 h-2 rounded-full shrink-0 ${style.dot}`} title={style.label} />
      </div>

      {/* Live value */}
      <div className="mt-1.5 flex items-baseline gap-1">
        <span className={`text-xl font-bold tabular-nums ${style.value}`}>{fmtValue(sensor.value)}</span>
        {sensor.unit && <span className="text-xs text-gray-400">{sensor.unit}</span>}
      </div>

      {/* Gauge bar: danger zones + value fill + threshold markers */}
      {hasScale && (
        <div className="mt-2">
          <div className="relative h-2 rounded-full bg-gray-200">
            {/* warning danger zone (threshold → dangerous extreme) */}
            {warn != null && (
              <div
                className="absolute top-0 bottom-0 bg-amber-300/50 first:rounded-l-full last:rounded-r-full"
                style={
                  sensor.direction === 'high'
                    ? { left: `${pct(warn)}%`, right: 0, borderRadius: '0 9999px 9999px 0' }
                    : { left: 0, width: `${pct(warn)}%`, borderRadius: '9999px 0 0 9999px' }
                }
              />
            )}
            {/* critical danger zone */}
            {crit != null && (
              <div
                className="absolute top-0 bottom-0 bg-red-400/60"
                style={
                  sensor.direction === 'high'
                    ? { left: `${pct(crit)}%`, right: 0, borderRadius: '0 9999px 9999px 0' }
                    : { left: 0, width: `${pct(crit)}%`, borderRadius: '9999px 0 0 9999px' }
                }
              />
            )}
            {/* live value fill */}
            {sensor.value != null && (
              <div
                className={`absolute left-0 top-0 bottom-0 rounded-full ${style.fill}`}
                style={{ width: `${pct(sensor.value)}%` }}
              />
            )}
            {/* threshold markers */}
            {warn != null && (
              <div
                className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-amber-600"
                style={{ left: `calc(${pct(warn)}% - 1px)` }}
                title={`Warning ${op} ${warnTxt}${sensor.unit || ''}`}
              />
            )}
            {crit != null && (
              <div
                className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-red-700"
                style={{ left: `calc(${pct(crit)}% - 1px)` }}
                title={`Critical ${op} ${critTxt}${sensor.unit || ''}`}
              />
            )}
          </div>
          {/* scale labels */}
          <div className="flex justify-between mt-0.5">
            <span className="text-[10px] text-gray-400 tabular-nums">{fmtThreshold(min)}</span>
            <span className="text-[10px] text-gray-400 tabular-nums">{fmtThreshold(max)}</span>
          </div>
        </div>
      )}

      {/* Threshold caption */}
      {(warnTxt || critTxt) && (
        <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px]">
          {warnTxt && (
            <span className="text-amber-700">
              Warn {op} {warnTxt}{sensor.unit || ''}
            </span>
          )}
          {critTxt && (
            <span className="text-red-700">
              Crit {op} {critTxt}{sensor.unit || ''}
            </span>
          )}
        </div>
      )}

      {/* Rule trigger points */}
      {sensor.triggers.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {sensor.triggers.map((t) => (
            <span
              key={t.rule_id}
              title={`${t.name}: alert when value ${t.operator} ${t.threshold_value}${sensor.unit || ''} for ${fmtDuration(t.duration_seconds)} → ${t.severity}`}
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium ${SEVERITY_CHIP[t.severity] || SEVERITY_CHIP.info}`}
            >
              <Zap className="w-3 h-3" />
              {t.operator} {fmtThreshold(t.threshold_value)}
              {sensor.unit || ''} · {fmtDuration(t.duration_seconds)} → {t.severity}
            </span>
          ))}
        </div>
      )}

      {/* Informational sensors (no thresholds / rules) */}
      {!warnTxt && !critTxt && sensor.triggers.length === 0 && (
        <div className="mt-1.5 text-[11px] text-gray-400">Informational — no thresholds</div>
      )}
    </div>
  );
}
