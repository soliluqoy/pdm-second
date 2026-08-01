/**
 * PREDICT — Alerts Page
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import FilterBar from '../components/ui/FilterBar';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import { queryKeys } from '../queryClient';
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
  const queryClient = useQueryClient();
  const [filterStatus, setFilterStatus] = useState('active');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightId = Number(searchParams.get('highlight')) || null;
  const highlightRef = useRef<HTMLElement | null>(null);

  const filters = useMemo(
    () => ({
      status: filterStatus || undefined,
      severity: filterSeverity || undefined,
    }),
    [filterStatus, filterSeverity]
  );

  const alertsQuery = useInfiniteQuery({
    queryKey: queryKeys.alerts(filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.getAlerts({
        ...filters,
        skip: pageParam,
        limit: PAGE_SIZE,
      }),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === PAGE_SIZE ? allPages.reduce((n, p) => n + p.length, 0) : undefined,
    refetchInterval: 15_000,
  });

  const alerts = useMemo(
    () => alertsQuery.data?.pages.flat() ?? [],
    [alertsQuery.data]
  );

  useWsSubscription(['ws:alerts'], () => {
    void queryClient.invalidateQueries({ queryKey: ['alerts'] });
  });

  useEffect(() => {
    if (!highlightId || alertsQuery.isLoading) return;
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
  }, [highlightId, alerts, alertsQuery.isLoading, filterStatus, setSearchParams]);

  const handleAction = async (action: 'ack' | 'resolve' | 'suppress', id: number) => {
    try {
      if (action === 'ack') await api.acknowledgeAlert(id);
      else if (action === 'resolve') await api.resolveAlert(id);
      else await api.suppressAlert(id);
      void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    } catch (e) {
      console.error(`Failed to ${action}:`, e);
    }
  };

  if (alertsQuery.isLoading) {
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

          {alertsQuery.hasNextPage && (
            <div className="text-center pt-2">
              <button
                onClick={() => void alertsQuery.fetchNextPage()}
                disabled={alertsQuery.isFetchingNextPage}
                className="btn-secondary"
              >
                {alertsQuery.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
