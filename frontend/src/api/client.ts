/**
 * PREDICT — API Client
 * Centralized fetch wrapper for all backend REST endpoints.
 */

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

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
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `API Error: ${response.status}`);
    }

    return response.json();
  }

  // ── Dashboard ──────────────────────────────────────────────────────────────
  getDashboardSummary() {
    return this.request<any>('/dashboard/summary');
  }

  getFleetHealth() {
    return this.request<any[]>('/dashboard/health');
  }

  getFleetTelemetry() {
    return this.request<any[]>('/dashboard/telemetry');
  }

  getVehicleReadings(vehicleId: number, sensorType?: string, hours = 1) {
    const params = new URLSearchParams({ hours: String(hours) });
    if (sensorType) params.set('sensor_type', sensorType);
    return this.request<any[]>(`/dashboard/vehicles/${vehicleId}/readings?${params}`);
  }

  getVehicleLatest(vehicleId: number) {
    return this.request<Record<string, any>>(`/dashboard/vehicles/${vehicleId}/latest`);
  }

  // ── Assets ──────────────────────────────────────────────────────────────────
  getFleets() {
    return this.request<any[]>('/assets/fleets');
  }

  getVehicles(params?: { fleet_id?: number; health?: string }) {
    const query = new URLSearchParams();
    if (params?.fleet_id) query.set('fleet_id', String(params.fleet_id));
    if (params?.health) query.set('health', params.health);
    const q = query.toString();
    return this.request<any[]>(`/assets/vehicles${q ? '?' + q : ''}`);
  }

  getVehicle(id: number) {
    return this.request<any>(`/assets/vehicles/${id}`);
  }

  getComponents(vehicleId: number) {
    return this.request<any[]>(`/assets/vehicles/${vehicleId}/components`);
  }

  getSensors(componentId: number) {
    return this.request<any[]>(`/assets/components/${componentId}/sensors`);
  }

  // ── Work Orders ──────────────────────────────────────────────────────────────
  getWorkOrders(params?: { status?: string; priority?: string; is_shadow?: boolean }) {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.priority) query.set('priority', params.priority);
    if (params?.is_shadow !== undefined) query.set('is_shadow', String(params.is_shadow));
    const q = query.toString();
    return this.request<any[]>(`/workorders${q ? '?' + q : ''}`);
  }

  getWorkOrder(id: number) {
    return this.request<any>(`/workorders/${id}`);
  }

  assignWorkOrder(id: number, assignedTo: string) {
    return this.request<any>(`/workorders/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ assigned_to: assignedTo }),
    });
  }

  completeWorkOrder(id: number, completedBy: string, notes?: string) {
    return this.request<any>(`/workorders/${id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ completed_by: completedBy, completion_notes: notes }),
    });
  }

  closeWorkOrder(id: number) {
    return this.request<any>(`/workorders/${id}/close`, {
      method: 'POST',
    });
  }

  cancelWorkOrder(id: number) {
    return this.request<any>(`/workorders/${id}/cancel`, {
      method: 'POST',
    });
  }

  // ── Alerts ──────────────────────────────────────────────────────────────────
  getAlerts(params?: { status?: string; severity?: string; vehicle_id?: number }) {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.severity) query.set('severity', params.severity);
    if (params?.vehicle_id) query.set('vehicle_id', String(params.vehicle_id));
    const q = query.toString();
    return this.request<any[]>(`/alerts${q ? '?' + q : ''}`);
  }

  acknowledgeAlert(id: number) {
    return this.request<any>(`/alerts/${id}/acknowledge`, { method: 'POST' });
  }

  resolveAlert(id: number) {
    return this.request<any>(`/alerts/${id}/resolve`, { method: 'POST' });
  }

  // ── Rules ────────────────────────────────────────────────────────────────────
  getRules(params?: { rule_type?: string; is_active?: boolean }) {
    const query = new URLSearchParams();
    if (params?.rule_type) query.set('rule_type', params.rule_type);
    if (params?.is_active !== undefined) query.set('is_active', String(params.is_active));
    const q = query.toString();
    return this.request<any[]>(`/rules${q ? '?' + q : ''}`);
  }

  getTemplates() {
    return this.request<any[]>('/rules/templates');
  }

  // ── System ───────────────────────────────────────────────────────────────────
  getShadowMode() {
    return this.request<{ shadow_mode: boolean }>('/system/shadow-mode');
  }

  setShadowMode(enabled: boolean) {
    return this.request<{ shadow_mode: boolean }>(
      `/system/shadow-mode?enabled=${enabled}`,
      { method: 'POST' }
    );
  }

  getMaintenanceHistory(vehicleId?: number) {
    const query = vehicleId ? `?vehicle_id=${vehicleId}` : '';
    return this.request<any[]>(`/system/history${query}`);
  }

  // ── Health ──────────────────────────────────────────────────────────────────
  getHealth() {
    return this.request<any>('/health');
  }
}

export const api = new ApiClient(API_URL);