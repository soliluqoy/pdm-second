/**
 * PREDICT — SensorTile
 * One live sensor: name, value, status, and threshold summary. Memoized so
 * WS patches to other sensors/vehicles don't re-render every tile.
 */
import { memo, useEffect, useRef, useState } from 'react';
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

function SensorTileInner({ sensor, onClick }: Props) {
  const [flash, setFlash] = useState(false);
  const prevValue = useRef<number | null | undefined>(sensor.value);

  useEffect(() => {
    if (sensor.value !== prevValue.current && sensor.value != null) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      prevValue.current = sensor.value;
      return () => clearTimeout(t);
    }
    prevValue.current = sensor.value;
  }, [sensor.value]);

  const styles = statusStyles[sensor.status];
  const captions = thresholdCaptions(sensor);
  const offline = sensor.status === 'offline';
  const Icon = sensorIcon(sensor.sensor_type);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left rounded-md border p-3 w-full transition-colors
        hover:border-predict-400 focus:outline-none focus:ring-2 focus:ring-predict-400
        ${styles.border} ${flash ? 'bg-predict-50' : styles.tileBg}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="flex items-center gap-1.5 min-w-0">
          <Icon className={`w-3.5 h-3.5 shrink-0 ${offline ? 'text-gray-400' : 'text-gray-500'}`} />
          <span className="text-sm font-medium text-gray-800 truncate">{sensor.name}</span>
        </span>
        <span className={`text-xs font-medium shrink-0 ${styles.text}`}>{styles.label}</span>
      </div>

      <div className="mb-2">
        <span className={`text-2xl font-semibold tabular-nums ${offline ? 'text-gray-400' : 'text-gray-900'}`}>
          {formatSensorValue(sensor.value)}
        </span>
        {sensor.unit && <span className="text-sm text-gray-500 ml-1">{sensor.unit}</span>}
      </div>

      <SensorGauge sensor={sensor} />

      {captions.length > 0 && (
        <p className="mt-2 text-xs text-gray-500 truncate" title={captions.map((c) => c.text).join(' · ')}>
          {captions.map((c) => c.text).join(' · ')}
        </p>
      )}
    </button>
  );
}

const SensorTile = memo(SensorTileInner);
export default SensorTile;
