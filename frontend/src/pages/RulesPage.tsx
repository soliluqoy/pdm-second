/**
 * PREDICT — Rules Page
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Rule, WorkOrderTemplate } from '../types';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';

const severityTone: Record<string, 'danger' | 'warning' | 'info'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
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
    return <LoadingState message="Loading rules…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Rules"
        description="Threshold and DTC rules that generate alerts and work orders"
        actions={
          <button
            onClick={toggleShadowMode}
            className={shadowMode ? 'btn-warning' : 'btn-secondary'}
          >
            Shadow mode: {shadowMode ? 'On' : 'Off'}
          </button>
        }
      />

      {shadowMode && (
        <div className="mb-6 panel px-4 py-3 text-sm text-purple-800 bg-purple-50 border-purple-200">
          Shadow mode is on. Work orders are created for review only — they will not trigger real maintenance.
        </div>
      )}

      <h2 className="section-title">Detection rules ({rules.length})</h2>
      <div className="panel overflow-x-auto mb-8">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Condition</th>
              <th>Severity</th>
              <th>Template</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => {
              const template = templates.find((t) => t.id === r.work_order_template_id);
              return (
                <tr key={r.id}>
                  <td>
                    <p className="font-medium text-gray-900">{r.name}</p>
                    {r.description && <p className="text-sm text-gray-600 mt-0.5">{r.description}</p>}
                  </td>
                  <td>
                    <Badge tone="neutral">{r.rule_type}</Badge>
                  </td>
                  <td className="text-gray-700">
                    {r.rule_type === 'threshold' && (
                      <>
                        {r.sensor_type} {r.operator} {r.threshold_value}
                        {r.duration_seconds > 0 && ` for ${r.duration_seconds}s`}
                      </>
                    )}
                    {r.rule_type === 'dtc' && <>Code: {r.dtc_code}</>}
                    {r.rule_type === 'scheduled' && <>Every {r.interval_value}</>}
                  </td>
                  <td>
                    <Badge tone={severityTone[r.severity] ?? 'info'}>{r.severity}</Badge>
                  </td>
                  <td>{template ? template.name : '—'}</td>
                  <td>{r.is_active ? 'Yes' : 'No'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2 className="section-title">Work order templates ({templates.length})</h2>
      <div className="panel divide-y divide-gray-100">
        {templates.map((t) => (
          <div key={t.id} className="px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium text-gray-900">{t.name}</p>
                {t.description && <p className="text-sm text-gray-600 mt-0.5">{t.description}</p>}
              </div>
              <div className="text-sm text-gray-600 text-right">
                <p>Priority: {t.default_priority}</p>
                <p>Est. {t.estimated_duration_minutes} min</p>
              </div>
            </div>
            {t.instructions && (
              <p className="text-sm text-gray-700 mt-2 whitespace-pre-line">{t.instructions}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
