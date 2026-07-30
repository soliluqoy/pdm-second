/**
 * PREDICT — Rules Page
 * View and manage threshold/DTC rules and work order templates.
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Rule, WorkOrderTemplate } from '../types';
import { Settings, Eye, ToggleLeft, ToggleRight } from 'lucide-react';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-300',
  warning: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
};

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [templates, setTemplates] = useState<WorkOrderTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [shadowMode, setShadowMode] = useState(false);

  const fetchRules = useCallback(async () => {
    try {
      const [r, t] = await Promise.all([api.getRules(), api.getTemplates()]);
      setRules(r);
      setTemplates(t);
    } catch (e) {
      console.error('Failed to fetch rules:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchShadowMode = useCallback(async () => {
    try {
      const res = await api.getShadowMode();
      setShadowMode(res.shadow_mode);
    } catch (e) {
      console.error('Failed to fetch shadow mode:', e);
    }
  }, []);

  useEffect(() => {
    fetchRules();
    fetchShadowMode();
  }, [fetchRules, fetchShadowMode]);

  const toggleShadowMode = async () => {
    try {
      const res = await api.setShadowMode(!shadowMode);
      setShadowMode(res.shadow_mode);
    } catch (e) {
      console.error('Failed to toggle shadow mode:', e);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-500 text-lg">Loading rules...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Rules & Templates</h1>
          <p className="text-sm text-gray-500">Threshold and DTC rules for anomaly detection</p>
        </div>
        <button
          onClick={toggleShadowMode}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg border transition-colors ${
            shadowMode
              ? 'bg-purple-100 text-purple-800 border-purple-300'
              : 'bg-gray-100 text-gray-600 border-gray-300'
          }`}
        >
          {shadowMode ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
          <span className="text-sm font-medium">Shadow Mode: {shadowMode ? 'ON' : 'OFF'}</span>
        </button>
      </div>

      {/* ── Shadow Mode Banner ────────────────────────────────────── */}
      {shadowMode && (
        <div className="mb-4 p-3 bg-purple-50 border border-purple-200 rounded-lg flex items-center gap-2">
          <Eye className="w-4 h-4 text-purple-600" />
          <p className="text-sm text-purple-700">
            Shadow Mode is active. Work orders are generated in "shadow" status for review — they will not trigger real maintenance.
          </p>
        </div>
      )}

      {/* ── Rules Table ───────────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 mb-6">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900 flex items-center gap-2">
            <Settings className="w-4 h-4" /> Rules ({rules.length})
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Condition</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Severity</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Template</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {rules.map((r) => {
                const template = templates.find((t) => t.id === r.work_order_template_id);
                return (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-900">{r.name}</p>
                      <p className="text-xs text-gray-500">{r.description}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">
                        {r.rule_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {r.rule_type === 'threshold' && (
                        <span>
                          {r.sensor_type} {r.operator} {r.threshold_value}
                          {r.duration_seconds > 0 && ` for ${r.duration_seconds}s`}
                        </span>
                      )}
                      {r.rule_type === 'dtc' && (
                        <span>Code: {r.dtc_code}</span>
                      )}
                      {r.rule_type === 'scheduled' && (
                        <span>Every {r.interval_value}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[r.severity] || SEVERITY_COLORS.info}`}>
                        {r.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {template ? template.name : '—'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-block w-2 h-2 rounded-full ${r.is_active ? 'bg-green-500' : 'bg-gray-300'}`} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Templates ──────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">Work Order Templates ({templates.length})</h2>
        </div>
        <div className="divide-y divide-gray-200">
          {templates.map((t) => (
            <div key={t.id} className="px-5 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900">{t.name}</p>
                  <p className="text-xs text-gray-500">{t.description}</p>
                </div>
                <div className="text-right text-xs text-gray-500">
                  <p>Priority: {t.default_priority}</p>
                  <p>Est: {t.estimated_duration_minutes}min</p>
                </div>
              </div>
              {t.instructions && (
                <p className="text-xs text-gray-600 mt-1 whitespace-pre-line">{t.instructions}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}