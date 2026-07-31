/**
 * PREDICT — Work Orders Page
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { WorkOrder, WorkOrderStatus, WSMessage } from '../types';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import FilterBar from '../components/ui/FilterBar';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';

const statusTone: Record<string, 'purple' | 'info' | 'warning' | 'success' | 'neutral' | 'danger'> = {
  shadow: 'purple',
  open: 'info',
  in_progress: 'warning',
  completed: 'success',
  closed: 'neutral',
  cancelled: 'danger',
};

const priorityTone: Record<string, 'danger' | 'warning' | 'info' | 'neutral'> = {
  urgent: 'danger',
  high: 'warning',
  medium: 'info',
  low: 'neutral',
};

export default function WorkOrdersPage({ wsMessages }: { wsMessages: WSMessage[] }) {
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [selectedWO, setSelectedWO] = useState<WorkOrder | null>(null);
  const [showCompleteModal, setShowCompleteModal] = useState(false);
  const [completedBy, setCompletedBy] = useState('tech1');
  const [completionNotes, setCompletionNotes] = useState('');
  const lastWsIdx = useRef(0);
  const refreshTimer = useRef<number | null>(null);

  const fetchWorkOrders = useCallback(async () => {
    try {
      const params = filterStatus ? { status: filterStatus } : undefined;
      const wos = await api.getWorkOrders(params);
      setWorkOrders(wos);
    } catch (e) {
      console.error('Failed to fetch work orders:', e);
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchWorkOrders(), 1000);
  }, [fetchWorkOrders]);

  useEffect(() => {
    fetchWorkOrders();
    const interval = setInterval(fetchWorkOrders, 10_000);
    return () => clearInterval(interval);
  }, [fetchWorkOrders]);

  useEffect(() => {
    for (let i = lastWsIdx.current; i < wsMessages.length; i++) {
      if (wsMessages[i].channel === 'ws:workorders') {
        scheduleRefresh();
      }
    }
    lastWsIdx.current = wsMessages.length;
  }, [wsMessages, scheduleRefresh]);

  const handleAssign = async (id: number) => {
    try {
      await api.assignWorkOrder(id, 'tech1');
      fetchWorkOrders();
    } catch (e) {
      console.error('Failed to assign:', e);
    }
  };

  const handleComplete = async () => {
    if (!selectedWO) return;
    try {
      await api.completeWorkOrder(selectedWO.id, completedBy, completionNotes);
      setShowCompleteModal(false);
      setCompletionNotes('');
      setSelectedWO(null);
      fetchWorkOrders();
    } catch (e) {
      console.error('Failed to complete:', e);
    }
  };

  const handleCancel = async (id: number) => {
    try {
      await api.cancelWorkOrder(id);
      fetchWorkOrders();
    } catch (e) {
      console.error('Failed to cancel:', e);
    }
  };

  const statusFilters: (WorkOrderStatus | '')[] = ['', 'shadow', 'open', 'in_progress', 'completed', 'closed'];

  if (loading) {
    return <LoadingState message="Loading work orders…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Work Orders"
        description={`${workOrders.length} work order${workOrders.length === 1 ? '' : 's'} shown`}
      />

      <FilterBar
        filters={[
          {
            id: 'status',
            label: 'Status',
            value: filterStatus,
            onChange: setFilterStatus,
            options: statusFilters.map((s) => ({
              value: s,
              label: s ? s.replace('_', ' ') : 'All',
            })),
          },
        ]}
      />

      {workOrders.length === 0 ? (
        <EmptyState message="No work orders match your filter." />
      ) : (
        <div className="panel overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Vehicle</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Assigned</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {workOrders.map((wo) => (
                <tr key={wo.id}>
                  <td className="text-gray-500">#{wo.id}</td>
                  <td>
                    <p className="font-medium text-gray-900">{wo.title}</p>
                    {wo.is_shadow && <Badge tone="purple" className="mt-1">Shadow</Badge>}
                  </td>
                  <td>{wo.vehicle_name || `Vehicle #${wo.vehicle_id}`}</td>
                  <td>
                    <Badge tone={priorityTone[wo.priority] ?? 'neutral'}>{wo.priority}</Badge>
                  </td>
                  <td>
                    <Badge tone={statusTone[wo.status] ?? 'neutral'}>
                      {wo.status.replace('_', ' ')}
                    </Badge>
                  </td>
                  <td>{wo.assigned_to || '—'}</td>
                  <td className="text-gray-600">{new Date(wo.created_at).toLocaleString()}</td>
                  <td>
                    <div className="flex flex-wrap gap-2">
                      {(wo.status === 'open' || wo.status === 'shadow') && (
                        <button onClick={() => handleAssign(wo.id)} className="btn-secondary">
                          Assign
                        </button>
                      )}
                      {(wo.status === 'open' || wo.status === 'in_progress' || wo.status === 'shadow') && (
                        <>
                          <button
                            onClick={() => {
                              setSelectedWO(wo);
                              setShowCompleteModal(true);
                            }}
                            className="btn-success"
                          >
                            Complete
                          </button>
                          <button onClick={() => handleCancel(wo.id)} className="btn-danger">
                            Cancel
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCompleteModal && selectedWO && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="panel max-w-md w-full shadow-lg">
            <div className="px-5 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">Complete work order</h3>
              <p className="text-sm text-gray-600 mt-1">#{selectedWO.id}: {selectedWO.title}</p>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="filter-label">Completed by</label>
                <select
                  value={completedBy}
                  onChange={(e) => setCompletedBy(e.target.value)}
                  className="filter-select w-full mt-1"
                >
                  <option value="tech1">John Technician</option>
                  <option value="tech2">Sarah Technician</option>
                  <option value="manager">Fleet Manager</option>
                </select>
              </div>
              <div>
                <label className="filter-label">Notes</label>
                <textarea
                  value={completionNotes}
                  onChange={(e) => setCompletionNotes(e.target.value)}
                  rows={4}
                  placeholder="What was done, parts replaced, etc."
                  className="filter-select w-full mt-1 resize-y"
                />
              </div>
              {selectedWO.instructions && (
                <div className="rounded-md bg-gray-50 border border-gray-200 p-3">
                  <p className="text-xs font-medium text-gray-500 mb-1">Instructions</p>
                  <p className="text-sm text-gray-700 whitespace-pre-line">{selectedWO.instructions}</p>
                </div>
              )}
            </div>
            <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowCompleteModal(false);
                  setSelectedWO(null);
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
              <button onClick={handleComplete} className="btn-primary">
                Mark complete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
