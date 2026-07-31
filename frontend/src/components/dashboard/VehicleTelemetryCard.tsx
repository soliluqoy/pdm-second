/**
 * PREDICT — VehicleTelemetryCard
 * A vehicle header (health, ignition, speed, alert/WO badges, last update)
 * plus a live grid of all its sensor tiles.
 */
import { formatDistanceToNow } from 'date-fns';
import { AlertTriangle, ClipboardList, Zap } from 'lucide-react';
import type { LiveSensorItem, VehicleLiveItem } from '../../types';
import SensorTile from './SensorTile';

interface Props {
  vehicle: VehicleLiveItem;
  now: number;
  onSelectSensor: (sensor: LiveSensorItem) => void;
}

const healthChip: Record<string, string> = {
  green: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  yellow: 'bg-amber-100 text-amber-800 border-amber-300',
  red: 'bg-red-100 text-red-800 border-red-300',
  grey: 'bg-gray-100 text-gray-600 border-gray-300',
};

const healthDot: Record<string, string> = {
  green: 'bg-emerald-500',
  yellow: 'bg-amber-500',
  red: 'bg-red-500',
  grey: 'bg-gray-400',
};

const healthRing: Record<string, string> = {
  green: 'border-l-emerald-500',
  yellow: 'border-l-amber-500',
  red: 'border-l-red-500',
  grey: 'border-l-gray-300',
};

export default function VehicleTelemetryCard({ vehicle, now, onSelectSensor }: Props) {
  const ts = vehicle.telemetry_timestamp ?? vehicle.last_seen;
  const lastUpdate = ts
    ? formatDistanceToNow(new Date(ts), { addSuffix: true })
    : 'never';
  const stale = ts ? now - new Date(ts).getTime() > 30_000 : true;

  return (
    <div
      className={`bg-white rounded-xl shadow-sm border border-gray-200 border-l-4 ${healthRing[vehicle.health] ?? healthRing.grey}`}
    >
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 border-b border-gray-100">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${healthDot[vehicle.health] ?? healthDot.grey} ${vehicle.health === 'red' ? 'animate-pulse' : ''}`} />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-gray-900 truncate">{vehicle.name}</h3>
              <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border ${healthChip[vehicle.health] ?? healthChip.grey}`}>
                {vehicle.health}
              </span>
            </div>
            <p className="text-xs text-gray-500 truncate">
              {vehicle.license_plate ?? '—'} · <span className="font-mono">{vehicle.imei}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 ml-auto text-xs">
          {/* Ignition */}
          <span className={`inline-flex items-center gap-1 font-medium ${vehicle.ignition ? 'text-emerald-600' : 'text-gray-400'}`} title={vehicle.ignition ? 'Ignition on' : 'Ignition off'}>
            <Zap className="w-3.5 h-3.5" />
            {vehicle.ignition ? 'IGN ON' : 'IGN OFF'}
          </span>

          {/* Speed */}
          <span className="text-gray-600 tabular-nums" title="GPS speed">
            {vehicle.speed != null ? `${Math.round(vehicle.speed)} km/h` : '— km/h'}
          </span>

          {/* Badges */}
          {vehicle.active_alert_count > 0 && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-semibold" title="Active alerts">
              <AlertTriangle className="w-3 h-3" /> {vehicle.active_alert_count}
            </span>
          )}
          {vehicle.open_work_order_count > 0 && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-semibold" title="Open work orders">
              <ClipboardList className="w-3 h-3" /> {vehicle.open_work_order_count}
            </span>
          )}

          {/* Last update */}
          <span className={`tabular-nums ${stale ? 'text-gray-400' : 'text-emerald-600'}`} title="Last telemetry update">
            {stale ? lastUpdate : `● live · ${lastUpdate}`}
          </span>
        </div>
      </div>

      {/* ── Sensor grid ────────────────────────────────────────────── */}
      <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6 gap-2.5">
        {vehicle.sensors.length === 0 ? (
          <p className="col-span-full text-sm text-gray-400 py-4 text-center">
            No sensors configured for this vehicle.
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
