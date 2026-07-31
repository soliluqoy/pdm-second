/**
 * PREDICT — SensorTile
 * One live sensor: name, live value, gauge with threshold markers,
 * trigger-point caption, and flash-on-update animation.
 */
import { useEffect, useRef, useState } from 'react';
import type { LiveSensorItem } from '../../types';
import {
  formatSensorValue,
  sensorIcon,
  statusStyles,
  thresholdCaptions,
} from '../../utils/sensors';
import SensorGauge from './SensorGauge';

interface Props {
  sensor: LiveSensorItem;
  onClick?: () => void;
}

export default function SensorTile({ sensor, onClick }: Props) {
  const [flash, setFlash] = useState(false);
  const prevValue = useRef<number | null | undefined>(sensor.value);

  // Flash briefly when a new live value arrives
  useEffect(() => {
    if (sensor.value !== prevValue.current && sensor.value != null) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 700);
      prevValue.current = sensor.value;
      return () => clearTimeout(t);
    }
    prevValue.current = sensor.value;
  }, [sensor.value]);

  const styles = statusStyles[sensor.status];
  const Icon = sensorIcon(sensor.sensor_type);
  const captions = thresholdCaptions(sensor);
  const offline = sensor.status === 'offline';

  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left rounded-lg border p-3 w-full transition-all duration-300 cursor-pointer
        hover:shadow-md hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-predict-400
        ${styles.border} ${flash ? 'bg-predict-100' : styles.tileBg}`}
      title={`${sensor.name} — ${styles.label}. Click for history.`}
    >
      {/* Name + status */}
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <Icon className={`w-3.5 h-3.5 shrink-0 ${offline ? 'text-gray-400' : 'text-predict-600'}`} />
          <span className="text-[11px] font-medium text-gray-600 truncate">{sensor.name}</span>
        </div>
        <span className={`w-2 h-2 rounded-full shrink-0 ${styles.dot} ${sensor.status === 'critical' ? 'animate-pulse' : ''}`} />
      </div>

      {/* Live value */}
      <div className="flex items-baseline gap-1 mb-2">
        <span className={`text-xl font-bold tabular-nums ${offline ? 'text-gray-400' : 'text-gray-900'}`}>
          {formatSensorValue(sensor.value)}
        </span>
        {sensor.unit && <span className="text-xs text-gray-500">{sensor.unit}</span>}
      </div>

      {/* Gauge with threshold markers */}
      <SensorGauge sensor={sensor} />

      {/* Trigger points */}
      <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5">
        {captions.length > 0 ? (
          captions.map((c) => (
            <span
              key={c.severity}
              className={`text-[10px] font-medium tabular-nums ${
                c.severity === 'critical' ? 'text-red-600' : 'text-amber-600'
              }`}
            >
              {c.text}
            </span>
          ))
        ) : (
          <span className="text-[10px] text-gray-400">no trigger</span>
        )}
      </div>
    </button>
  );
}
