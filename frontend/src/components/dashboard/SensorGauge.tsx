/**
 * PREDICT — SensorGauge
 * Mini horizontal gauge showing live value position across safe/warning/
 * critical zones derived from the sensor's thresholds.
 */
import type { LiveSensorItem } from '../../types';
import { statusStyles } from '../../utils/sensors';

interface Props {
  sensor: LiveSensorItem;
}

interface Zone {
  from: number;
  to: number;
  color: string;
}

export default function SensorGauge({ sensor }: Props) {
  const { min_value: min, max_value: max, warning_threshold: warn, critical_threshold: crit, direction, value, status } = sensor;

  // Need a range to render a gauge
  if (min == null || max == null || max <= min) {
    return <div className="h-2 rounded-full bg-gray-100" title="No operating range defined" />;
  }

  const pct = (x: number) => Math.min(100, Math.max(0, ((x - min) / (max - min)) * 100));

  // Build colored zones between the trigger points
  const zones: Zone[] = [];
  if (warn != null && crit != null) {
    if (direction === 'high') {
      zones.push({ from: min, to: warn, color: '#10b981' });
      zones.push({ from: warn, to: crit, color: '#f59e0b' });
      zones.push({ from: crit, to: max, color: '#ef4444' });
    } else {
      zones.push({ from: min, to: crit, color: '#ef4444' });
      zones.push({ from: crit, to: warn, color: '#f59e0b' });
      zones.push({ from: warn, to: max, color: '#10b981' });
    }
  }

  const valuePct = value != null ? pct(value) : null;
  const markerColor = statusStyles[status].zone;

  return (
    <div className="relative pt-1 pb-0.5">
      {/* Zone track */}
      <div className="h-1.5 rounded-full overflow-hidden flex bg-gray-200">
        {zones.length > 0 ? (
          zones.map((z, i) => (
            <div
              key={i}
              className="h-full opacity-30"
              style={{ width: `${pct(z.to) - pct(z.from)}%`, backgroundColor: z.color }}
            />
          ))
        ) : (
          <div className="h-full w-full bg-emerald-500 opacity-30" />
        )}
      </div>

      {/* Threshold tick marks */}
      {warn != null && (
        <div
          className="absolute w-0.5 h-2.5 bg-amber-500 rounded-full -translate-x-1/2"
          style={{ left: `${pct(warn)}%`, top: '2px' }}
          title={`Warning trigger: ${warn}${sensor.unit ?? ''}`}
        />
      )}
      {crit != null && (
        <div
          className="absolute w-0.5 h-2.5 bg-red-600 rounded-full -translate-x-1/2"
          style={{ left: `${pct(crit)}%`, top: '2px' }}
          title={`Critical trigger: ${crit}${sensor.unit ?? ''}`}
        />
      )}

      {/* Value marker */}
      {valuePct != null && (
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 transition-all duration-500 ease-out"
          style={{ left: `${valuePct}%` }}
        >
          <div
            className="w-3 h-3 rounded-full bg-white shadow ring-2"
            style={{ ['--tw-ring-color' as any]: markerColor, boxShadow: `0 0 0 2px ${markerColor}` }}
          />
        </div>
      )}
    </div>
  );
}
