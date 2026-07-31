/**
 * PREDICT — Alerts Page
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { Alert, WSMessage } from '../types';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import FilterBar from '../components/ui/FilterBar';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';

const severityTone: Record<string, 'danger' | 'warning' | 'info'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
};

const statusTone: Record<string, 'danger' | 'warning' | 'success' | 'neutral'> = {
  active: 'danger',
  acknowledged: 'warning',
  resolved: 'success',
  suppressed: 'neutral',
};

interface Props {
  wsMessages: WSMessage[];
}

export default function AlertsPage({ wsMessages }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('active');
  const [filterSeverity, setFilterSeverity] = useState('');
  const lastWsIdx = useRef(0);
  const refreshTimer = useRef<number | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const params: { status?: string; severity?: string } = {};
      if (filterStatus) params.status = filterStatus;
      if (filterSeverity) params.severity = filterSeverity;
      const a = await api.getAlerts(params);
      setAlerts(a);
    } catch (e) {
      console.error('Failed to fetch alerts:', e);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterSeverity]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchAlerts(), 1000);
  }, [fetchAlerts]);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 10_000);
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  useEffect(() => {
    for (let i = lastWsIdx.current; i < wsMessages.length; i++) {
      if (wsMessages[i].channel === 'ws:alerts') {
        scheduleRefresh();
      }
    }
    lastWsIdx.current = wsMessages.length;
  }, [wsMessages, scheduleRefresh]);

  const handleAcknowledge = async (id: number) => {
    try {
      await api.acknowledgeAlert(id);
      fetchAlerts();
    } catch (e) {
      console.error('Failed to acknowledge:', e);
    }
  };

  const handleResolve = async (id: number) => {
    try {
      await api.resolveAlert(id);
      fetchAlerts();
    } catch (e) {
      console.error('Failed to resolve:', e);
    }
  };

  if (loading) {
    return <LoadingState message="Loading alerts…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Alerts"
        description={`${alerts.length} alert${alerts.length === 1 ? '' : 's'} shown`}
      />

      <FilterBar
        filters={[
          {
            id: 'status',
            label: 'Status',
            value: filterStatus,
            onChange: setFilterStatus,
            options: [
              { value: 'active', label: 'Active' },
              { value: 'acknowledged', label: 'Acknowledged' },
              { value: 'resolved', label: 'Resolved' },
              { value: '', label: 'All' },
            ],
          },
          {
            id: 'severity',
            label: 'Severity',
            value: filterSeverity,
            onChange: setFilterSeverity,
            options: [
              { value: '', label: 'All' },
              { value: 'critical', label: 'Critical' },
              { value: 'warning', label: 'Warning' },
              { value: 'info', label: 'Info' },
            ],
          },
        ]}
      />

      {alerts.length === 0 ? (
        <EmptyState message="No alerts match your filters." />
      ) : (
        <div className="space-y-3">
          {alerts.map((a) => (
            <article key={a.id} className="panel p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <h3 className="text-base font-semibold text-gray-900">{a.title}</h3>
                    <Badge tone={severityTone[a.severity] ?? 'info'}>{a.severity}</Badge>
                    <Badge tone={statusTone[a.status] ?? 'neutral'}>{a.status}</Badge>
                  </div>
                  <p className="text-sm text-gray-700 mb-3">{a.message}</p>
                  <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-1 text-sm">
                    <div>
                      <dt className="text-gray-500">Vehicle</dt>
                      <dd className="font-medium text-gray-900">{a.vehicle_name || `#${a.vehicle_id}`}</dd>
                    </div>
                    {a.trigger_value != null && (
                      <div>
                        <dt className="text-gray-500">Trigger value</dt>
                        <dd className="font-medium text-gray-900 tabular-nums">{a.trigger_value}</dd>
                      </div>
                    )}
                    <div>
                      <dt className="text-gray-500">Created</dt>
                      <dd className="font-medium text-gray-900">{new Date(a.created_at).toLocaleString()}</dd>
                    </div>
                    {a.work_order_id && (
                      <div>
                        <dt className="text-gray-500">Work order</dt>
                        <dd className="font-medium text-gray-900">#{a.work_order_id}</dd>
                      </div>
                    )}
                  </dl>
                </div>

                <div className="flex flex-wrap gap-2 shrink-0">
                  {a.status === 'active' && (
                    <button
                      onClick={() => handleAcknowledge(a.id)}
                      className="btn-warning"
                    >
                      Acknowledge
                    </button>
                  )}
                  {a.status !== 'resolved' && (
                    <button
                      onClick={() => handleResolve(a.id)}
                      className="btn-success"
                    >
                      Resolve
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
