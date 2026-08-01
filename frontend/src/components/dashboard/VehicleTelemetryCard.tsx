/**
 * PREDICT — VehicleTelemetryCard
 * Vehicle summary + sensor grid.
 */
import { formatDistanceToNow } from 'date-fns';
import type { LiveSensorItem, VehicleLiveItem } from '../../types';
import Badge from '../ui/Badge';
import SensorTile from './SensorTile';

interface Props {
  vehicle: VehicleLiveItem;
  now: number;
  onSelectSensor: (sensor: LiveSensorItem) => void;
}

const healthTone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  green: 'success',
  yellow: 'warning',
  red: 'danger',
  grey: 'neutral',
};

export default function VehicleTelemetryCard({ vehicle, now, onSelectSensor }: Props) {
  const ts = vehicle.telemetry_timestamp ?? vehicle.last_seen;
  const lastUpdate = ts ? formatDistanceToNow(new Date(ts), { addSuffix: true }) : 'never';
  const stale = ts ? now - new Date(ts).getTime() > 300_000 : true;

  return (
    <div className="panel overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-semibold text-gray-900">{vehicle.name}</h3>
              <Badge tone={healthTone[vehicle.health] ?? 'neutral'}>{vehicle.health}</Badge>
            </div>
            <p className="text-sm text-gray-600 mt-0.5">
              {vehicle.license_plate ?? 'No plate'} · IMEI {vehicle.imei}
            </p>
          </div>

          <div className="text-sm text-gray-600 space-y-1 text-right">
            <p>
              Ignition: <span className="font-medium text-gray-900">{vehicle.ignition ? 'On' : 'Off'}</span>
              {' · '}
              Speed: <span className="font-medium text-gray-900 tabular-nums">
                {vehicle.speed != null ? `${Math.round(vehicle.speed)} km/h` : '—'}
              </span>
            </p>
            <p className="tabular-nums">
              {stale ? (
                <span className="text-gray-500">Last update {lastUpdate}</span>
              ) : (
                <span className="text-green-700">Live · updated {lastUpdate}</span>
              )}
              {vehicle.active_alert_count > 0 && (
                <span className="ml-3 text-red-700">{vehicle.active_alert_count} alert(s)</span>
              )}
              {vehicle.open_work_order_count > 0 && (
                <span className="ml-3 text-blue-700">{vehicle.open_work_order_count} work order(s)</span>
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {vehicle.sensors.length === 0 ? (
          <p className="col-span-full text-sm text-gray-500 py-4 text-center">
            No sensors configured.
          </p>
        ) : (
          vehicle.sensors.map((s) => (
            <SensorTile
              key={s.sensor_type}
              sensor={s}
              onClick={() => onSelectSensor(s)}
            />
          ))
        )}
      </div>
    </div>
  );
}
