/**
 * PREDICT — API Client
 * Centralized fetch wrapper for all backend REST endpoints.
 */
import type {
  Alert,
  BehaviorScorecard,
  BehaviorVehicleDetail,
  Component,
  DashboardSummary,
  Fleet,
  MaintenanceHistory,
  Rule,
  RuleInput,
  Sensor,
  SensorHistory,
  SensorReading,
  TelemetryCatalog,
  TimelineEvent,
  Trip,
  TripDetail,
  User,
  Vehicle,
  VehicleLiveItem,
  VehicleRegisterInput,
  WorkOrder,
  WorkOrderTemplate,
} from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

/** FastAPI `detail` can be a string, an object, or a validation-error array —
 * normalize to a readable message instead of "[object Object]". */
function normalizeErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => {
        if (typeof d === 'string') return d;
        const loc = Array.isArray(d?.loc) ? d.loc.slice(1).join('.') : '';
        return loc ? `${loc}: ${d?.msg ?? ''}` : d?.msg ?? '';
      })
      .filter(Boolean);
    if (msgs.length) return msgs.join('; ');
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail);
    } catch {
      /* fall through */
    }
  }
  return fallback;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl + API_PREFIX;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const config: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    };

    const response = await fetch(url, config);

    if (response.status === 204) {
      return undefined as T;
    }

    if (!response.ok) {
      const fallback = `API Error: ${response.status}`;
      const body = await response.json().catch(() => null);
      throw new Error(normalizeErrorDetail(body?.detail, fallback));
    }

    return response.json();
  }

  // ── Dashboard ──────────────────────────────────────────────────────────────
  getDashboardSummary() {
    return this.request<DashboardSummary>('/dashboard/summary');
  }

  getFleetLive() {
    return this.request<VehicleLiveItem[]>('/dashboard/fleet/live');
  }

  getTelemetryCatalog() {
    return this.request<TelemetryCatalog>('/dashboard/telemetry-catalog');
  }

  getVehicleReadings(vehicleId: number, sensorType?: string, hours = 1) {
    const params = new URLSearchParams({ hours: String(hours) });
    if (sensorType) params.set('sensor_type', sensorType);
    return this.request<SensorReading[]>(`/dashboard/vehicles/${vehicleId}/readings?${params}`);
  }

  /** Bucketed sensor history (Timescale continuous aggregates for long ranges). */
  getSensorHistory(
    vehicleId: number,
    sensorType: string,
    hours: number,
    resolution = 'auto',
    range?: { from?: string; to?: string },
  ) {
    const params = new URLSearchParams({
      sensor_type: sensorType,
      hours: String(hours),
      resolution,
    });
    if (range?.from && range?.to) {
      params.set('from', range.from);
      params.set('to', range.to);
    }
    return this.request<SensorHistory>(`/dashboard/vehicles/${vehicleId}/history?${params}`);
  }

  /** CSV download URL for sensor history (same filters as getSensorHistory). */
  sensorHistoryCsvUrl(
    vehicleId: number,
    sensorType: string,
    hours: number,
    resolution = 'auto',
    range?: { from?: string; to?: string },
  ) {
    const params = new URLSearchParams({
      sensor_type: sensorType,
      hours: String(hours),
      resolution,
    });
    if (range?.from && range?.to) {
      params.set('from', range.from);
      params.set('to', range.to);
    }
    return `${this.baseUrl}/dashboard/vehicles/${vehicleId}/history/csv?${params}`;
  }

  /** Merged event stream: alerts, work orders, maintenance, health, DTCs. */
  getVehicleTimeline(vehicleId: number, limit = 100, skip = 0) {
    const params = new URLSearchParams({
      limit: String(limit),
      skip: String(skip),
    });
    return this.request<TimelineEvent[]>(
      `/dashboard/vehicles/${vehicleId}/timeline?${params}`
    );
  }

  // ── Assets ──────────────────────────────────────────────────────────────────
  getFleets() {
    return this.request<Fleet[]>('/assets/fleets');
  }

  getVehicles(params?: { fleet_id?: number; health?: string; is_active?: boolean }) {
    const query = new URLSearchParams();
    if (params?.fleet_id) query.set('fleet_id', String(params.fleet_id));
    if (params?.health) query.set('health', params.health);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const q = query.toString();
    return this.request<Vehicle[]>(`/assets/vehicles${q ? '?' + q : ''}`);
  }

  getVehicle(id: number) {
    return this.request<Vehicle>(`/assets/vehicles/${id}`);
  }

  registerVehicle(data: VehicleRegisterInput) {
    return this.request<Vehicle>('/assets/vehicles/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  updateVehicle(id: number, data: Partial<VehicleRegisterInput> & { is_active?: boolean }) {
    return this.request<Vehicle>(`/assets/vehicles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  deleteVehicle(id: number) {
    return this.request<void>(`/assets/vehicles/${id}`, { method: 'DELETE' });
  }

  getComponents(vehicleId: number) {
    return this.request<Component[]>(`/assets/vehicles/${vehicleId}/components`);
  }

  getSensors(componentId: number) {
    return this.request<Sensor[]>(`/assets/components/${componentId}/sensors`);
  }

  updateSensor(
    sensorId: number,
    data: {
      name?: string;
      unit?: string;
      min_value?: number | null;
      max_value?: number | null;
      warning_threshold?: number | null;
      critical_threshold?: number | null;
      is_active?: boolean;
    }
  ) {
    return this.request<Sensor>(`/assets/sensors/${sensorId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // ── Work Orders ──────────────────────────────────────────────────────────────
  getWorkOrders(params?: {
    status?: string;
    priority?: string;
    is_shadow?: boolean;
    vehicle_id?: number;
    skip?: number;
    limit?: number;
  }) {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.priority) query.set('priority', params.priority);
    if (params?.is_shadow !== undefined) query.set('is_shadow', String(params.is_shadow));
    if (params?.vehicle_id !== undefined) query.set('vehicle_id', String(params.vehicle_id));
    if (params?.skip) query.set('skip', String(params.skip));
    if (params?.limit) query.set('limit', String(params.limit));
    const q = query.toString();
    return this.request<WorkOrder[]>(`/workorders${q ? '?' + q : ''}`);
  }

  assignWorkOrder(id: number, assignedTo: string) {
    return this.request<WorkOrder>(`/workorders/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ assigned_to: assignedTo }),
    });
  }

  completeWorkOrder(id: number, completedBy: string, notes?: string, component?: string) {
    return this.request<WorkOrder>(`/workorders/${id}/complete`, {
      method: 'POST',
      body: JSON.stringify({
        completed_by: completedBy,
        completion_notes: notes,
        component: component || undefined,
      }),
    });
  }

  closeWorkOrder(id: number) {
    return this.request<WorkOrder>(`/workorders/${id}/close`, {
      method: 'POST',
    });
  }

  cancelWorkOrder(id: number) {
    return this.request<WorkOrder>(`/workorders/${id}/cancel`, {
      method: 'POST',
    });
  }

  approveWorkOrder(id: number) {
    return this.request<WorkOrder>(`/workorders/${id}/approve`, {
      method: 'POST',
    });
  }

  // ── Alerts ──────────────────────────────────────────────────────────────────
  getAlerts(params?: { status?: string; severity?: string; vehicle_id?: number; skip?: number; limit?: number }) {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.severity) query.set('severity', params.severity);
    if (params?.vehicle_id) query.set('vehicle_id', String(params.vehicle_id));
    if (params?.skip) query.set('skip', String(params.skip));
    if (params?.limit) query.set('limit', String(params.limit));
    const q = query.toString();
    return this.request<Alert[]>(`/alerts${q ? '?' + q : ''}`);
  }

  acknowledgeAlert(id: number) {
    return this.request<Alert>(`/alerts/${id}/acknowledge`, { method: 'POST' });
  }

  resolveAlert(id: number) {
    return this.request<Alert>(`/alerts/${id}/resolve`, { method: 'POST' });
  }

  suppressAlert(id: number) {
    return this.request<Alert>(`/alerts/${id}/suppress`, { method: 'POST' });
  }

  // ── Rules ────────────────────────────────────────────────────────────────────
  getRules(params?: { rule_type?: string; is_active?: boolean }) {
    const query = new URLSearchParams();
    if (params?.rule_type) query.set('rule_type', params.rule_type);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const q = query.toString();
    return this.request<Rule[]>(`/rules${q ? '?' + q : ''}`);
  }

  createRule(data: RuleInput) {
    return this.request<Rule>('/rules', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  updateRule(id: number, data: Partial<RuleInput>) {
    return this.request<Rule>(`/rules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  deleteRule(id: number) {
    return this.request<void>(`/rules/${id}`, { method: 'DELETE' });
  }

  getTemplates() {
    return this.request<WorkOrderTemplate[]>('/rules/templates');
  }

  // ── System ───────────────────────────────────────────────────────────────────
  getUsers() {
    return this.request<User[]>('/system/users');
  }

  getShadowMode() {
    return this.request<{ shadow_mode: boolean }>('/system/shadow-mode');
  }

  setShadowMode(enabled: boolean) {
    return this.request<{ shadow_mode: boolean }>(
      `/system/shadow-mode?enabled=${enabled}`,
      { method: 'POST' }
    );
  }

  getVehicleHistory(vehicleId: number) {
    return this.request<MaintenanceHistory[]>(`/system/history/vehicle/${vehicleId}`);
  }

  // ── Behavior ───────────────────────────────────────────────────────────────
  getBehaviorSummary(days = 1) {
    return this.request<BehaviorScorecard[]>(`/behavior/summary?days=${days}`);
  }

  getVehicleBehavior(vehicleId: number, days = 14) {
    return this.request<BehaviorVehicleDetail>(
      `/behavior/vehicles/${vehicleId}?days=${days}`
    );
  }

  getVehicleTrips(vehicleId: number, limit = 50, skip = 0) {
    return this.request<Trip[]>(
      `/behavior/vehicles/${vehicleId}/trips?limit=${limit}&skip=${skip}`
    );
  }

  getTripDetail(vehicleId: number, tripId: number) {
    return this.request<TripDetail>(
      `/behavior/vehicles/${vehicleId}/trips/${tripId}`
    );
  }
}

export const api = new ApiClient(API_URL);
