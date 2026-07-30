/**
 * PREDICT — Alerts Page
 * List, filter, acknowledge, and resolve alerts.
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Alert } from '../types';
import { Bell, CheckCircle, XCircle, Filter, AlertTriangle } from 'lucide-react';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-300',
  warning: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
};

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-red-50 text-red-700',
  acknowledged: 'bg-yellow-50 text-yellow-700',
  resolved: 'bg-green-50 text-green-700',
  suppressed: 'bg-gray-50 text-gray-600',
};

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('active');
  const [filterSeverity, setFilterSeverity] = useState('');

  const fetchAlerts = useCallback(async () => {
    try {
      const params: any = {};
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

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

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
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-500 text-lg">Loading alerts...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Alerts</h1>
          <p className="text-sm text-gray-500">Monitor and manage system alerts</p>
        </div>
      </div>

      {/* ── Filters ───────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-600">Status:</span>
          {['active', 'acknowledged', 'resolved', ''].map((s) => (
            <button
              key={s || 'all'}
              onClick={() => setFilterStatus(s)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                filterStatus === s ? 'bg-predict-600 text-white' : 'bg-white border border-gray-200 text-gray-600'
              }`}
            >
              {s || 'all'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Severity:</span>
          {['critical', 'warning', 'info', ''].map((s) => (
            <button
              key={s || 'all'}
              onClick={() => setFilterSeverity(s)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                filterSeverity === s ? 'bg-predict-600 text-white' : 'bg-white border border-gray-200 text-gray-600'
              }`}
            >
              {s || 'all'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Alerts List ──────────────────────────────────────────── */}
      <div className="space-y-2">
        {alerts.length === 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center text-gray-400">
            <Bell className="w-12 h-12 mx-auto mb-2 text-gray-300" />
            <p>No alerts found.</p>
          </div>
        ) : (
          alerts.map((a) => (
            <div
              key={a.id}
              className={`bg-white rounded-xl shadow-sm border-l-4 p-4 ${
                a.severity === 'critical' ? 'border-l-red-500' :
                a.severity === 'warning' ? 'border-l-yellow-500' :
                'border-l-blue-500'
              } border border-gray-200`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle className={`w-4 h-4 ${
                      a.severity === 'critical' ? 'text-red-500' :
                      a.severity === 'warning' ? 'text-yellow-500' : 'text-blue-500'
                    }`} />
                    <h3 className="font-semibold text-gray-900">{a.title}</h3>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.info}`}>
                      {a.severity}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[a.status] || STATUS_COLORS.suppressed}`}>
                      {a.status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 mb-2">{a.message}</p>
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>Vehicle: {a.vehicle_name || `#${a.vehicle_id}`}</span>
                    {a.trigger_value !== null && a.trigger_value !== undefined && (
                      <span>Trigger: {a.trigger_value}</span>
                    )}
                    <span>{new Date(a.created_at).toLocaleString()}</span>
                    {a.work_order_id && (
                      <span className="text-blue-600">WO: #{a.work_order_id}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 ml-4">
                  {a.status === 'active' && (
                    <button
                      onClick={() => handleAcknowledge(a.id)}
                      className="p-2 text-yellow-600 hover:bg-yellow-50 rounded-lg"
                      title="Acknowledge"
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                  )}
                  {a.status !== 'resolved' && (
                    <button
                      onClick={() => handleResolve(a.id)}
                      className="p-2 text-green-600 hover:bg-green-50 rounded-lg"
                      title="Resolve"
                    >
                      <XCircle className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}