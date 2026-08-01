/**
 * PREDICT — VehicleTelemetryCard
 * Vehicle summary + sensor grid. Memoized: only re-renders when its own
 * vehicle data changes, with a local clock for the staleness indicator.
 */
import { memo, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { LiveSensorItem, VehicleLiveItem } from '../../types';
import Badge from '../ui/Badge';
import RelativeTime from '../ui/RelativeTime';
import SensorTile from './SensorTile';

interface Props {
  vehicle: VehicleLiveItem;
  onSelectSensor: (vehicleId: number, sensor: LiveSensorItem) => void;
}

const healthTone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  green: 'success',
  yellow: 'warning',
  red: 'danger',
  grey: 'neutral',
};

function VehicleTelemetryCardInner({ vehicle, onSelectSensor }: Props) {
  const ts = vehicle.telemetry_timestamp ?? vehicle.last_seen;

  // Local 15s clock for the stale indicator — doesn't tick the page.
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(t);
  }, []);
  const stale = ts ? now - new Date(ts).getTime() > 300_000 : true;

  return (
    <div className="panel overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                to={`/vehicles/${vehicle.id}`}
                className="text-base font-semibold text-gray-900 hover:text-predict-700 hover:underline"
              >
                {vehicle.name}
              </Link>
              <Badge tone={healthTone[vehicle.health] ?? 'neutral'}>{vehicle.health}</Badge>
            </div>
            <p className="text-sm text-gray-600 mt-0.5">
              {vehicle.license_plate ?? 'No plate'} · IMEI {vehicle.imei}
            </p>
          </div>

          <div className="text-sm text-gray-600 space-y-1 text-right">
            <p>
              Ignition:{' '}
              <span className="font-medium text-gray-900">
                {vehicle.ignition == null ? '—' : vehicle.ignition ? 'On' : 'Off'}
              </span>
              {' · '}
              Speed: <span className="font-medium text-gray-900 tabular-nums">
                {vehicle.speed != null ? `${Math.round(vehicle.speed)} km/h` : '—'}
              </span>
            </p>
            <p className="tabular-nums">
              {stale ? (
                <RelativeTime timestamp={ts} prefix="Last update" className="text-gray-500" />
              ) : (
                <span className="text-green-700">
                  Live · <RelativeTime timestamp={ts} prefix="updated" />
                </span>
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
              onClick={() => onSelectSensor(vehicle.id, s)}
            />
          ))
        )}
      </div>
    </div>
  );
}

const VehicleTelemetryCard = memo(VehicleTelemetryCardInner);
export default VehicleTelemetryCard;
