/**
 * Shared TanStack Query client + cache keys.
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export const queryKeys = {
  dashboardSummary: ['dashboard-summary'] as const,
  fleetLive: ['fleet-live'] as const,
  telemetryCatalog: ['telemetry-catalog'] as const,
  alerts: (filters: { status?: string; severity?: string }) =>
    ['alerts', filters] as const,
  workOrders: (filters: { status?: string; priority?: string }) =>
    ['workorders', filters] as const,
  users: ['users'] as const,
  shadowMode: ['shadow-mode'] as const,
  fleets: ['fleets'] as const,
  vehicles: (filters?: { is_active?: boolean }) =>
    ['vehicles', filters ?? {}] as const,
  vehicle: (id: number) => ['vehicle', id] as const,
  components: (vehicleId: number) => ['components', vehicleId] as const,
  sensors: (componentId: number) => ['sensors', componentId] as const,
  vehicleHistory: (vehicleId: number) => ['vehicle-maint-history', vehicleId] as const,
  rules: ['rules'] as const,
  templates: ['templates'] as const,
  sensorHistory: (
    vehicleId: number,
    sensorType: string,
    hours: number,
    from?: string,
    to?: string,
  ) => ['sensor-history', vehicleId, sensorType, hours, from ?? null, to ?? null] as const,
  timeline: (vehicleId: number) => ['timeline', vehicleId] as const,
};
