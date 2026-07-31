/**
 * PREDICT — TypeScript Types
 * Mirrors backend Pydantic schemas.
 */

export type AssetHealth = 'green' | 'yellow' | 'red' | 'grey';
export type AlertSeverity = 'critical' | 'warning' | 'info';
export type AlertStatus = 'active' | 'acknowledged' | 'resolved' | 'suppressed';
export type WorkOrderStatus = 'shadow' | 'open' | 'in_progress' | 'completed' | 'closed' | 'cancelled';
export type WorkOrderPriority = 'urgent' | 'high' | 'medium' | 'low';
export type RuleType = 'threshold' | 'dtc' | 'scheduled';
export type UserRole = 'admin' | 'fleet_manager' | 'technician';

export interface Fleet {
  id: number;
  name: string;
  description?: string;
  is_active: boolean;
  vehicle_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Vehicle {
  id: number;
  fleet_id?: number;
  name: string;
  license_plate?: string;
  make?: string;
  model?: string;
  year?: number;
  vin?: string;
  imei: string;
  is_active: boolean;
  health: AssetHealth;
  last_seen?: string;
  fleet_name?: string;
  component_count?: number;
  active_alert_count?: number;
  open_work_order_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Component {
  id: number;
  vehicle_id: number;
  name: string;
  component_type?: string;
  description?: string;
  sensor_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Sensor {
  id: number;
  component_id: number;
  name: string;
  sensor_type: string;
  unit?: string;
  io_element_id?: number;
  min_value?: number;
  max_value?: number;
  warning_threshold?: number;
  critical_threshold?: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Rule {
  id: number;
  name: string;
  description?: string;
  rule_type: RuleType;
  sensor_id?: number;
  sensor_type?: string;
  operator?: string;
  threshold_value?: number;
  duration_seconds: number;
  dtc_code?: string;
  interval_value?: number;
  severity: AlertSeverity;
  work_order_template_id?: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkOrderTemplate {
  id: number;
  name: string;
  description: string;
  default_priority: WorkOrderPriority;
  estimated_duration_minutes: number;
  instructions?: string;
  created_at: string;
  updated_at: string;
}

export interface Alert {
  id: number;
  vehicle_id: number;
  rule_id?: number;
  sensor_id?: number;
  severity: AlertSeverity;
  status: AlertStatus;
  title: string;
  message: string;
  trigger_value?: number;
  trigger_timestamp?: string;
  work_order_id?: number;
  vehicle_name?: string;
  created_at: string;
}

export interface WorkOrder {
  id: number;
  vehicle_id: number;
  alert_id?: number;
  template_id?: number;
  title: string;
  description: string;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  instructions?: string;
  assigned_to?: string;
  assigned_at?: string;
  completed_at?: string;
  completed_by?: string;
  completion_notes?: string;
  is_shadow: boolean;
  vehicle_name?: string;
  created_at: string;
  updated_at: string;
}

export interface SensorReading {
  id: number;
  timestamp: string;
  vehicle_id: number;
  sensor_type: string;
  sensor_name?: string;
  value: number;
  unit?: string;
  quality?: string;
  latitude?: number;
  longitude?: number;
  speed?: number;
  ignition?: boolean;
}

export interface DashboardSummary {
  total_vehicles: number;
  green_count: number;
  yellow_count: number;
  red_count: number;
  grey_count: number;
  active_alerts: number;
  critical_alerts: number;
  open_work_orders: number;
  shadow_work_orders: number;
  in_progress_work_orders: number;
  shadow_mode: boolean;
}

export interface VehicleHealthItem {
  id: number;
  name: string;
  imei: string;
  health: AssetHealth;
  last_seen?: string;
  license_plate?: string;
  active_alert_count: number;
  open_work_order_count: number;
  latest_readings?: Record<string, { value: number; unit: string }>;
}

export type SensorStatus = 'ok' | 'warning' | 'critical' | 'offline';
export type SensorDirection = 'high' | 'low';

export interface TriggerRuleInfo {
  id: number;
  name: string;
  operator?: string;
  threshold_value?: number;
  duration_seconds: number;
  severity: AlertSeverity;
}

export interface LiveSensorItem {
  sensor_type: string;
  name: string;
  unit?: string;
  value?: number;
  min_value?: number;
  max_value?: number;
  warning_threshold?: number;
  critical_threshold?: number;
  direction: SensorDirection;
  status: SensorStatus;
  rules: TriggerRuleInfo[];
}

export interface VehicleLiveItem {
  id: number;
  name: string;
  imei: string;
  license_plate?: string;
  health: AssetHealth;
  last_seen?: string;
  ignition?: boolean;
  speed?: number;
  telemetry_timestamp?: string;
  active_alert_count: number;
  open_work_order_count: number;
  sensors: LiveSensorItem[];
}

export interface MaintenanceHistory {
  id: number;
  vehicle_id: number;
  work_order_id?: number;
  event_type: string;
  title: string;
  description?: string;
  performed_by?: string;
  event_date: string;
}

export interface WSMessage {
  channel: string;
  data: any;
}