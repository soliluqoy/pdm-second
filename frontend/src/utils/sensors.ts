/**
 * PREDICT — Sensor utilities
 * Status computation (mirrors backend), formatting, icons, and status styling.
 */
import type { LiveSensorItem, SensorStatus } from '../types';
import {
  Activity,
  CircleDot,
  Clock,
  Cog,
  Disc,
  Droplets,
  Fuel,
  Gauge,
  Navigation,
  Route,
  Thermometer,
  Zap,
  type LucideIcon,
} from 'lucide-react';

/** Recompute status client-side when live WS telemetry patches a value. */
export function computeSensorStatus(
  value: number | null | undefined,
  sensor: Pick<LiveSensorItem, 'warning_threshold' | 'critical_threshold' | 'direction'>
): SensorStatus {
  if (value === null || value === undefined) return 'offline';
  const { warning_threshold: warn, critical_threshold: crit, direction } = sensor;
  if (direction === 'low') {
    if (crit != null && value <= crit) return 'critical';
    if (warn != null && value <= warn) return 'warning';
  } else {
    if (crit != null && value >= crit) return 'critical';
    if (warn != null && value >= warn) return 'warning';
  }
  return 'ok';
}

export const statusStyles: Record<
  SensorStatus,
  { label: string; text: string; dot: string; border: string; tileBg: string; badge: string; zone: string }
> = {
  ok: {
    label: 'OK',
    text: 'text-emerald-700',
    dot: 'bg-emerald-500',
    border: 'border-emerald-200',
    tileBg: 'bg-white',
    badge: 'bg-emerald-100 text-emerald-700',
    zone: '#10b981',
  },
  warning: {
    label: 'Warning',
    text: 'text-amber-700',
    dot: 'bg-amber-500',
    border: 'border-amber-300',
    tileBg: 'bg-amber-50',
    badge: 'bg-amber-100 text-amber-700',
    zone: '#f59e0b',
  },
  critical: {
    label: 'Critical',
    text: 'text-red-700',
    dot: 'bg-red-500',
    border: 'border-red-300',
    tileBg: 'bg-red-50',
    badge: 'bg-red-100 text-red-700',
    zone: '#ef4444',
  },
  offline: {
    label: 'Offline',
    text: 'text-gray-500',
    dot: 'bg-gray-400',
    border: 'border-gray-200',
    tileBg: 'bg-gray-50',
    badge: 'bg-gray-100 text-gray-500',
    zone: '#9ca3af',
  },
};

// Keys match the sensor_type strings from the provisioning catalog
// (backend/app/services/provisioning.py).
const sensorIcons: Record<string, LucideIcon> = {
  engine_rpm: Gauge,
  coolant_temperature: Thermometer,
  engine_oil_temperature: Thermometer,
  intake_air_temperature: Thermometer,
  ambient_air_temperature: Thermometer,
  engine_load: Activity,
  throttle_position: Activity,
  engine_oil_pressure: Droplets,
  engine_oil_level: Droplets,
  intake_map: Disc,
  battery_voltage: Zap,
  tracker_battery_voltage: Zap,
  control_module_voltage: Zap,
  vehicle_battery_voltage: Zap,
  hv_battery_charge: Zap,
  vehicle_speed: Navigation,
  vehicle_speed_obd: Navigation,
  gsm_signal: CircleDot,
  fuel_level: Fuel,
  fuel_level_liters: Fuel,
  fuel_rate: Fuel,
  fuel_consumed: Fuel,
  odometer: Route,
  distance_until_service: Route,
  remaining_distance: Route,
  mil_on_distance: Route,
  codes_cleared_distance: Route,
  engine_hours: Clock,
  engine_runtime: Clock,
  dtc_count: Cog,
};

export function sensorIcon(sensorType: string): LucideIcon {
  return sensorIcons[sensorType] ?? Activity;
}

/** Format a live sensor value for display. */
export function formatSensorValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

/** Operator symbol implied by threshold direction. */
export function directionOperator(direction: 'high' | 'low'): string {
  return direction === 'low' ? '<' : '>';
}

export interface ThresholdCaption {
  severity: 'warning' | 'critical';
  text: string;
}

/** Human-readable trigger points for a sensor, e.g. "warn >100°C · crit >110°C". */
export function thresholdCaptions(sensor: LiveSensorItem): ThresholdCaption[] {
  const out: ThresholdCaption[] = [];
  const op = directionOperator(sensor.direction);
  const unit = sensor.unit ?? '';
  if (sensor.warning_threshold != null) {
    out.push({ severity: 'warning', text: `warn ${op}${formatSensorValue(sensor.warning_threshold)}${unit}` });
  }
  if (sensor.critical_threshold != null) {
    out.push({ severity: 'critical', text: `crit ${op}${formatSensorValue(sensor.critical_threshold)}${unit}` });
  }
  return out;
}
