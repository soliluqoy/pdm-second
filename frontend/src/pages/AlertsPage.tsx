/**
 * PREDICT — Alerts Page
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { Alert } from '../types';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import FilterBar from '../components/ui/FilterBar';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import { useWsSubscription } from '../ws/WsContext';

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

const PAGE_SIZE = 50;

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('active');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightId = Number(searchParams.get('highlight')) || null;
  const highlightRef = useRef<HTMLElement | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const params: { status?: string; severity?: string; limit: number } = { limit: PAGE_SIZE };
      if (filterStatus) params.status = filterStatus;
      if (filterSeverity) params.severity = filterSeverity;
      const a = await api.getAlerts(params);
      setAlerts(a);
      setHasMore(a.length === PAGE_SIZE);
    } catch (e) {
      console.error('Failed to fetch alerts:', e);
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterSeverity]);

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const params: { status?: string; severity?: string; skip: number; limit: number } = {
        skip: alerts.length,
        limit: PAGE_SIZE,
      };
      if (filterStatus) params.status = filterStatus;
      if (filterSeverity) params.severity = filterSeverity;
      const more = await api.getAlerts(params);
      setAlerts((prev) => [...prev, ...more]);
      setHasMore(more.length === PAGE_SIZE);
    } catch (e) {
      console.error('Failed to load more alerts:', e);
    } finally {
      setLoadingMore(false);
    }
  }, [alerts.length, filterStatus, filterSeverity]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchAlerts(), 1000);
  }, [fetchAlerts]);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 15_000);
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  useWsSubscription(['ws:alerts'], () => scheduleRefresh());

  // Deep link: /alerts?highlight=<id> — show it regardless of the status
  // filter, scroll to it, and clear the param once seen.
  useEffect(() => {
    if (!highlightId || loading) return;
    const present = alerts.some((a) => a.id === highlightId);
    if (!present && filterStatus !== '') {
      setFilterStatus('');
      return;
    }
    const el = highlightRef.current;
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      const t = setTimeout(() => setSearchParams({}, { replace: true }), 4000);
      return () => clearTimeout(t);
    }
  }, [highlightId, alerts, loading, filterStatus, setSearchParams]);

  const handleAction = async (action: 'ack' | 'resolve' | 'suppress', id: number) => {
    try {
      if (action === 'ack') await api.acknowledgeAlert(id);
      else if (action === 'resolve') await api.resolveAlert(id);
      else await api.suppressAlert(id);
      fetchAlerts();
    } catch (e) {
      console.error(`Failed to ${action}:`, e);
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
              { value: 'suppressed', label: 'Suppressed' },
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
            <article
              key={a.id}
              ref={a.id === highlightId ? (el) => { highlightRef.current = el; } : undefined}
              className={`panel p-4 transition-shadow ${
                a.id === highlightId ? 'ring-2 ring-predict-400 shadow-md' : ''
              }`}
            >
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
                      onClick={() => handleAction('ack', a.id)}
                      className="btn-warning"
                    >
                      Acknowledge
                    </button>
                  )}
                  {(a.status === 'active' || a.status === 'acknowledged') && (
                    <button
                      onClick={() => handleAction('suppress', a.id)}
                      className="btn-secondary"
                      title="Mute this alert without resolving it"
                    >
                      Suppress
                    </button>
                  )}
                  {a.status !== 'resolved' && (
                    <button
                      onClick={() => handleAction('resolve', a.id)}
                      className="btn-success"
                    >
                      Resolve
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}

          {hasMore && (
            <div className="text-center pt-2">
              <button onClick={loadMore} disabled={loadingMore} className="btn-secondary">
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
