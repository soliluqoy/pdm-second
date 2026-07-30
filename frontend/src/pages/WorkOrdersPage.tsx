/**
 * PREDICT — Work Orders Page
 * List, filter, assign, and complete work orders.
 * Includes the technician "Mark as Complete" feedback loop.
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { WorkOrder, WorkOrderStatus, WorkOrderPriority } from '../types';
import {
  ClipboardList,
  UserPlus,
  CheckCircle2,
  XCircle,
  Eye,
  Filter,
} from 'lucide-react';

const STATUS_COLORS: Record<string, string> = {
  shadow: 'bg-purple-100 text-purple-800 border-purple-300',
  open: 'bg-blue-100 text-blue-800 border-blue-300',
  in_progress: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  completed: 'bg-green-100 text-green-800 border-green-300',
  closed: 'bg-gray-100 text-gray-600 border-gray-300',
  cancelled: 'bg-red-100 text-red-800 border-red-300',
};

const PRIORITY_COLORS: Record<string, string> = {
  urgent: 'bg-red-600 text-white',
  high: 'bg-orange-500 text-white',
  medium: 'bg-blue-500 text-white',
  low: 'bg-gray-400 text-white',
};

export default function WorkOrdersPage() {
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [selectedWO, setSelectedWO] = useState<WorkOrder | null>(null);
  const [showCompleteModal, setShowCompleteModal] = useState(false);
  const [completedBy, setCompletedBy] = useState('tech1');
  const [completionNotes, setCompletionNotes] = useState('');

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

  useEffect(() => {
    fetchWorkOrders();
  }, [fetchWorkOrders]);

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
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-500 text-lg">Loading work orders...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Work Orders</h1>
          <p className="text-sm text-gray-500">Manage maintenance tasks and technician workflow</p>
        </div>
      </div>

      {/* ── Filter Bar ────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 mb-4">
        <Filter className="w-4 h-4 text-gray-400" />
        {statusFilters.map((s) => (
          <button
            key={s || 'all'}
            onClick={() => setFilterStatus(s)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filterStatus === s
                ? 'bg-predict-600 text-white'
                : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-50'
            }`}
          >
            {s ? s.replace('_', ' ') : 'all'}
          </button>
        ))}
      </div>

      {/* ── Work Orders Table ─────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Title</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Assigned</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {workOrders.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
                    No work orders found.
                  </td>
                </tr>
              ) : (
                workOrders.map((wo) => (
                  <tr key={wo.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-500">#{wo.id}</td>
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-900">{wo.title}</p>
                      {wo.is_shadow && (
                        <span className="text-xs text-purple-600 flex items-center gap-1">
                          <Eye className="w-3 h-3" /> Shadow
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{wo.vehicle_name || `Vehicle #${wo.vehicle_id}`}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-bold ${PRIORITY_COLORS[wo.priority] || PRIORITY_COLORS.low}`}>
                        {wo.priority}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium border ${STATUS_COLORS[wo.status] || STATUS_COLORS.closed}`}>
                        {wo.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{wo.assigned_to || '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(wo.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-center gap-1">
                        {(wo.status === 'open' || wo.status === 'shadow') && (
                          <button
                            onClick={() => handleAssign(wo.id)}
                            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded"
                            title="Assign to technician"
                          >
                            <UserPlus className="w-4 h-4" />
                          </button>
                        )}
                        {(wo.status === 'open' || wo.status === 'in_progress' || wo.status === 'shadow') && (
                          <>
                            <button
                              onClick={() => {
                                setSelectedWO(wo);
                                setShowCompleteModal(true);
                              }}
                              className="p-1.5 text-green-600 hover:bg-green-50 rounded"
                              title="Mark as complete"
                            >
                              <CheckCircle2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleCancel(wo.id)}
                              className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                              title="Cancel"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Complete Modal ────────────────────────────────────────── */}
      {showCompleteModal && selectedWO && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">Complete Work Order</h3>
              <p className="text-sm text-gray-500 mt-1">#{selectedWO.id}: {selectedWO.title}</p>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Completed By</label>
                <select
                  value={completedBy}
                  onChange={(e) => setCompletedBy(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                >
                  <option value="tech1">John Technician</option>
                  <option value="tech2">Sarah Technician</option>
                  <option value="manager">Fleet Manager</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Completion Notes</label>
                <textarea
                  value={completionNotes}
                  onChange={(e) => setCompletionNotes(e.target.value)}
                  rows={4}
                  placeholder="Describe what was done, parts replaced, etc."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                />
              </div>
              {selectedWO.instructions && (
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs font-medium text-gray-500 mb-1">Instructions:</p>
                  <p className="text-sm text-gray-700 whitespace-pre-line">{selectedWO.instructions}</p>
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowCompleteModal(false);
                  setSelectedWO(null);
                }}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleComplete}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4" />
                Mark Complete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}