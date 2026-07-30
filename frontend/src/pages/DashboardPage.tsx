/**
 * PREDICT — Dashboard Page
 * Fleet health overview, summary cards, live vehicle status.
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { DashboardSummary, VehicleHealthItem, WSMessage } from '../types';
import {
  Truck,
  AlertTriangle,
  ClipboardList,
  Activity,
  Eye,
  CheckCircle2,
  Clock,
} from 'lucide-react';

interface Props {
  wsMessages: WSMessage[];
}

export default function DashboardPage({ wsMessages }: Props) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [vehicles, setVehicles] = useState<VehicleHealthItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([
        api.getDashboardSummary(),
        api.getFleetHealth(),
      ]);
      setSummary(s);
      setVehicles(v);
    } catch (e) {
      console.error('Failed to fetch dashboard data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Update on WS messages
  useEffect(() => {
    if (wsMessages.length > 0) {
      fetchData();
    }
  }, [wsMessages, fetchData]);

  const healthColor = (health: string) => {
    switch (health) {
      case 'green': return 'bg-green-100 text-green-800 border-green-300';
      case 'yellow': return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'red': return 'bg-red-100 text-red-800 border-red-300';
      default: return 'bg-gray-100 text-gray-600 border-gray-300';
    }
  };

  const healthDot = (health: string) => {
    switch (health) {
      case 'green': return 'bg-green-500';
      case 'yellow': return 'bg-yellow-500';
      case 'red': return 'bg-red-500';
      default: return 'bg-gray-400';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-500 text-lg">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Fleet Dashboard</h1>
          <p className="text-sm text-gray-500">Real-time asset health and work order status</p>
        </div>
        {summary?.shadow_mode && (
          <div className="flex items-center gap-2 px-4 py-2 bg-purple-100 text-purple-800 rounded-lg border border-purple-300">
            <Eye className="w-4 h-4" />
            <span className="text-sm font-medium">Shadow Mode Active</span>
          </div>
        )}
      </div>

      {/* ── Summary Cards ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {/* Total Vehicles */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 bg-predict-50 rounded-lg">
              <Truck className="w-6 h-6 text-predict-600" />
            </div>
            <span className="text-3xl font-bold text-gray-900">{summary?.total_vehicles ?? 0}</span>
          </div>
          <p className="text-sm text-gray-500">Total Vehicles</p>
          <div className="flex gap-2 mt-2 text-xs">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              {summary?.green_count ?? 0}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-yellow-500" />
              {summary?.yellow_count ?? 0}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              {summary?.red_count ?? 0}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-gray-400" />
              {summary?.grey_count ?? 0}
            </span>
          </div>
        </div>

        {/* Active Alerts */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 bg-red-50 rounded-lg">
              <AlertTriangle className="w-6 h-6 text-red-600" />
            </div>
            <span className="text-3xl font-bold text-gray-900">{summary?.active_alerts ?? 0}</span>
          </div>
          <p className="text-sm text-gray-500">Active Alerts</p>
          <p className="text-xs text-red-600 mt-2">
            {summary?.critical_alerts ?? 0} critical
          </p>
        </div>

        {/* Open Work Orders */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <ClipboardList className="w-6 h-6 text-blue-600" />
            </div>
            <span className="text-3xl font-bold text-gray-900">{summary?.open_work_orders ?? 0}</span>
          </div>
          <p className="text-sm text-gray-500">Open Work Orders</p>
          <p className="text-xs text-blue-600 mt-2">
            {summary?.in_progress_work_orders ?? 0} in progress
          </p>
        </div>

        {/* Shadow Work Orders */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <Eye className="w-6 h-6 text-purple-600" />
            </div>
            <span className="text-3xl font-bold text-gray-900">{summary?.shadow_work_orders ?? 0}</span>
          </div>
          <p className="text-sm text-gray-500">Shadow Work Orders</p>
          <p className="text-xs text-purple-600 mt-2">Pending review</p>
        </div>
      </div>

      {/* ── Fleet Health Table ────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Fleet Health</h2>
          <p className="text-sm text-gray-500">Sorted by priority — at-risk vehicles first</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Vehicle</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Plate</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">IMEI</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Last Seen</th>
                <th className="px-5 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Alerts</th>
                <th className="px-5 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">Work Orders</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Latest Readings</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {vehicles.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-8 text-center text-gray-400">
                    No vehicles found. Ensure the simulator is running.
                  </td>
                </tr>
              ) : (
                vehicles.map((v) => (
                  <tr key={v.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3">
                      <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium border ${healthColor(v.health)}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${healthDot(v.health)}`} />
                        {v.health}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-sm font-medium text-gray-900">{v.name}</td>
                    <td className="px-5 py-3 text-sm text-gray-600">{v.license_plate || '—'}</td>
                    <td className="px-5 py-3 text-sm text-gray-500 font-mono">{v.imei}</td>
                    <td className="px-5 py-3 text-sm text-gray-500">
                      {v.last_seen ? new Date(v.last_seen).toLocaleTimeString() : '—'}
                    </td>
                    <td className="px-5 py-3 text-center">
                      {v.active_alert_count > 0 ? (
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-100 text-red-700 text-xs font-bold">
                          {v.active_alert_count}
                        </span>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-center">
                      {v.open_work_order_count > 0 ? (
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-xs font-bold">
                          {v.open_work_order_count}
                        </span>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {v.latest_readings && Object.keys(v.latest_readings).length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(v.latest_readings).slice(0, 4).map(([key, val]: [string, any]) => (
                            <span key={key} className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">
                              {key.replace(/_/g, ' ')}: {val.value}{val.unit || ''}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-gray-300 text-xs">No data</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}