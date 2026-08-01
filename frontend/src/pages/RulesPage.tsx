/**
 * PREDICT — Rules Page
 * Full CRUD for detection rules (threshold / DTC / scheduled / behavior)
 * plus shadow-mode toggle and work-order template list. Anomaly rules are
 * auto-generated (read-only badge).
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import type {
  AlertSeverity,
  Rule,
  RuleInput,
  RuleType,
} from '../types';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import { queryKeys } from '../queryClient';

const severityTone: Record<string, 'danger' | 'warning' | 'info'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
};

const OPERATORS = ['>', '>=', '<', '<=', '=='];
const SCHEDULED_SENSORS = ['odometer', 'engine_hours'];
const BEHAVIOR_EVENTS = [
  'harsh_accel',
  'harsh_brake',
  'harsh_corner',
  'speeding',
  'idling',
  'high_rpm',
];

interface RuleFormState {
  name: string;
  description: string;
  rule_type: RuleType;
  vehicle_id: string;          // '' = fleet-wide
  sensor_type: string;
  operator: string;
  threshold_value: string;
  duration_seconds: string;
  dtc_code: string;
  interval_value: string;
  severity: AlertSeverity;
  work_order_template_id: string;
  is_active: boolean;
}

const emptyForm: RuleFormState = {
  name: '',
  description: '',
  rule_type: 'threshold',
  vehicle_id: '',
  sensor_type: '',
  operator: '>',
  threshold_value: '',
  duration_seconds: '0',
  dtc_code: '',
  interval_value: '',
  severity: 'warning',
  work_order_template_id: '',
  is_active: true,
};

function ruleToForm(r: Rule): RuleFormState {
  return {
    name: r.name,
    description: r.description ?? '',
    rule_type: r.rule_type,
    vehicle_id: r.vehicle_id != null ? String(r.vehicle_id) : '',
    sensor_type: r.sensor_type ?? '',
    operator: r.operator ?? '>',
    threshold_value: r.threshold_value != null ? String(r.threshold_value) : '',
    duration_seconds: String(r.duration_seconds ?? 0),
    dtc_code: r.dtc_code ?? '',
    interval_value: r.interval_value != null ? String(r.interval_value) : '',
    severity: r.severity,
    work_order_template_id: r.work_order_template_id != null ? String(r.work_order_template_id) : '',
    is_active: r.is_active,
  };
}

export default function RulesPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Rule | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<RuleFormState>(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const rulesQuery = useQuery({
    queryKey: queryKeys.rules,
    queryFn: () => api.getRules(),
  });
  const templatesQuery = useQuery({
    queryKey: queryKeys.templates,
    queryFn: () => api.getTemplates(),
  });
  const vehiclesQuery = useQuery({
    queryKey: queryKeys.vehicles({ is_active: true }),
    queryFn: () => api.getVehicles({ is_active: true }),
  });
  const catalogQuery = useQuery({
    queryKey: queryKeys.telemetryCatalog,
    queryFn: () => api.getTelemetryCatalog(),
    staleTime: Infinity,
  });
  const shadowQuery = useQuery({
    queryKey: queryKeys.shadowMode,
    queryFn: () => api.getShadowMode(),
  });

  const rules = rulesQuery.data ?? [];
  const templates = templatesQuery.data ?? [];
  const vehicles = vehiclesQuery.data ?? [];
  const catalog = catalogQuery.data ?? null;
  const shadowMode = shadowQuery.data?.shadow_mode ?? false;
  const loading = rulesQuery.isLoading || templatesQuery.isLoading;

  const fetchAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.rules });
    void queryClient.invalidateQueries({ queryKey: queryKeys.templates });
  };

  // Known sensor types from the telemetry catalog (both device models)
  const sensorTypeOptions = useMemo(() => {
    const set = new Set<string>();
    catalog?.models.forEach((m) => m.sensors.forEach((s) => set.add(s.sensor_type)));
    return [...set].sort();
  }, [catalog]);

  const toggleShadowMode = async () => {
    try {
      const res = await api.setShadowMode(!shadowMode);
      queryClient.setQueryData(queryKeys.shadowMode, res);
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    } catch (e) {
      console.error('Failed to toggle shadow mode:', e);
    }
  };

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError(null);
    setShowForm(true);
  };

  const openEdit = (rule: Rule) => {
    setEditing(rule);
    setForm(ruleToForm(rule));
    setFormError(null);
    setShowForm(true);
  };

  const handleToggleActive = async (rule: Rule) => {
    try {
      await api.updateRule(rule.id, { is_active: !rule.is_active });
      fetchAll();
    } catch (e) {
      console.error('Failed to toggle rule:', e);
    }
  };

  const handleDelete = async (rule: Rule) => {
    if (!window.confirm(`Delete rule "${rule.name}"? Existing alerts are kept.`)) return;
    try {
      await api.deleteRule(rule.id);
      fetchAll();
    } catch (e) {
      console.error('Failed to delete rule:', e);
    }
  };

  const handleSave = async () => {
    setFormError(null);
    if (!form.name.trim()) {
      setFormError('Name is required.');
      return;
    }
    const payload: RuleInput = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      rule_type: form.rule_type,
      vehicle_id: form.vehicle_id ? Number(form.vehicle_id) : null,
      severity: form.severity,
      work_order_template_id: form.work_order_template_id
        ? Number(form.work_order_template_id)
        : null,
      is_active: form.is_active,
    };
    if (form.rule_type === 'threshold') {
      payload.sensor_type = form.sensor_type;
      payload.operator = form.operator;
      payload.threshold_value = form.threshold_value === '' ? undefined : Number(form.threshold_value);
      payload.duration_seconds = Number(form.duration_seconds) || 0;
      if (!payload.sensor_type) return setFormError('Sensor type is required for threshold rules.');
      if (payload.threshold_value == null || Number.isNaN(payload.threshold_value)) {
        return setFormError('Threshold value is required.');
      }
    } else if (form.rule_type === 'dtc') {
      payload.dtc_code = form.dtc_code.trim().toUpperCase();
      if (!payload.dtc_code) return setFormError('DTC code is required (e.g. P0300).');
    } else if (form.rule_type === 'behavior') {
      payload.sensor_type = form.sensor_type;
      payload.operator = form.operator || '>=';
      payload.threshold_value = form.threshold_value === '' ? undefined : Number(form.threshold_value);
      payload.duration_seconds = Number(form.duration_seconds) || 86400;
      if (!BEHAVIOR_EVENTS.includes(payload.sensor_type ?? '')) {
        return setFormError('Pick a driving event type (e.g. harsh_brake).');
      }
      if (payload.threshold_value == null || Number.isNaN(payload.threshold_value)) {
        return setFormError('Event count threshold is required.');
      }
    } else if (form.rule_type === 'anomaly') {
      return setFormError('Anomaly rules are auto-generated by the baselines job.');
    } else {
      payload.sensor_type = form.sensor_type;
      payload.interval_value = form.interval_value === '' ? undefined : Number(form.interval_value);
      if (!SCHEDULED_SENSORS.includes(payload.sensor_type ?? '')) {
        return setFormError('Scheduled rules track odometer or engine_hours.');
      }
      if (!payload.interval_value || payload.interval_value <= 0) {
        return setFormError('A positive interval is required (e.g. 10000 km).');
      }
    }

    setSaving(true);
    try {
      if (editing) await api.updateRule(editing.id, payload);
      else await api.createRule(payload);
      setShowForm(false);
      fetchAll();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Failed to save rule');
    } finally {
      setSaving(false);
    }
  };

  const vehicleName = (id?: number | null) =>
    id == null ? null : vehicles.find((v) => v.id === id)?.name ?? `#${id}`;

  if (loading) {
    return <LoadingState message="Loading rules…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Rules"
        description="Threshold, DTC, scheduled, and behavior rules that generate alerts and work orders"
        actions={
          <>
            <button onClick={openCreate} className="btn-primary flex items-center gap-1.5">
              <Plus className="w-4 h-4" /> New rule
            </button>
            <button
              onClick={toggleShadowMode}
              className={shadowMode ? 'btn-warning' : 'btn-secondary'}
            >
              Shadow mode: {shadowMode ? 'On' : 'Off'}
            </button>
          </>
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
              <th>Scope</th>
              <th>Severity</th>
              <th>Template</th>
              <th>Active</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => {
              const template = templates.find((t) => t.id === r.work_order_template_id);
              return (
                <tr key={r.id} className={r.is_active ? '' : 'opacity-60'}>
                  <td>
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-gray-900">{r.name}</p>
                      {r.dormant && (
                        <span
                          className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5"
                          title="No registered vehicle provisions this sensor type — the rule can never fire."
                        >
                          <AlertTriangle className="w-3 h-3" /> dormant
                        </span>
                      )}
                    </div>
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
                    {r.rule_type === 'scheduled' && (
                      <>Every {r.interval_value} {r.sensor_type === 'engine_hours' ? 'h' : 'km'} ({r.sensor_type})</>
                    )}
                    {r.rule_type === 'behavior' && (
                      <>
                        {r.sensor_type} {r.operator ?? '>='} {r.threshold_value}/day
                      </>
                    )}
                    {r.rule_type === 'anomaly' && (
                      <>Auto · {r.sensor_type || 'generic'}</>
                    )}
                  </td>
                  <td className="text-gray-700">
                    {vehicleName(r.vehicle_id) ?? <span className="text-gray-400">Fleet-wide</span>}
                  </td>
                  <td>
                    <Badge tone={severityTone[r.severity] ?? 'info'}>{r.severity}</Badge>
                  </td>
                  <td>{template ? template.name : '—'}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() => handleToggleActive(r)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                        r.is_active ? 'bg-predict-500' : 'bg-gray-300'
                      }`}
                      title={r.is_active ? 'Disable rule' : 'Enable rule'}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                          r.is_active ? 'translate-x-[18px]' : 'translate-x-[3px]'
                        }`}
                      />
                    </button>
                  </td>
                  <td>
                    <div className="flex gap-1">
                      <button onClick={() => openEdit(r)} className="btn-secondary px-2 py-1.5" title="Edit">
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => handleDelete(r)} className="btn-danger px-2 py-1.5" title="Delete">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
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

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="panel max-w-lg w-full shadow-lg max-h-[90vh] overflow-y-auto">
            <div className="px-5 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">
                {editing ? `Edit rule #${editing.id}` : 'New rule'}
              </h3>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="filter-label">Name *</label>
                <input
                  className="filter-select w-full mt-1"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="High Coolant Temperature"
                />
              </div>
              <div>
                <label className="filter-label">Description</label>
                <input
                  className="filter-select w-full mt-1"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="filter-label">Type</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.rule_type}
                    onChange={(e) => setForm((f) => ({ ...f, rule_type: e.target.value as RuleType }))}
                  >
                    <option value="threshold">Threshold</option>
                    <option value="dtc">DTC (fault code)</option>
                    <option value="scheduled">Scheduled (interval)</option>
                    <option value="behavior">Behavior (event count)</option>
                  </select>
                </div>
                <div>
                  <label className="filter-label">Scope</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.vehicle_id}
                    onChange={(e) => setForm((f) => ({ ...f, vehicle_id: e.target.value }))}
                  >
                    <option value="">Fleet-wide</option>
                    {vehicles.map((v) => (
                      <option key={v.id} value={v.id}>{v.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              {form.rule_type === 'threshold' && (
                <>
                  <div>
                    <label className="filter-label">Sensor type *</label>
                    <select
                      className="filter-select w-full mt-1"
                      value={form.sensor_type}
                      onChange={(e) => setForm((f) => ({ ...f, sensor_type: e.target.value }))}
                    >
                      <option value="">Select…</option>
                      {sensorTypeOptions.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="filter-label">Operator</label>
                      <select
                        className="filter-select w-full mt-1"
                        value={form.operator}
                        onChange={(e) => setForm((f) => ({ ...f, operator: e.target.value }))}
                      >
                        {OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="filter-label">Threshold *</label>
                      <input
                        type="number"
                        className="filter-select w-full mt-1"
                        value={form.threshold_value}
                        onChange={(e) => setForm((f) => ({ ...f, threshold_value: e.target.value }))}
                      />
                    </div>
                    <div>
                      <label className="filter-label">Sustained (s)</label>
                      <input
                        type="number"
                        min={0}
                        className="filter-select w-full mt-1"
                        value={form.duration_seconds}
                        onChange={(e) => setForm((f) => ({ ...f, duration_seconds: e.target.value }))}
                      />
                    </div>
                  </div>
                </>
              )}

              {form.rule_type === 'dtc' && (
                <div>
                  <label className="filter-label">DTC code *</label>
                  <input
                    className="filter-select w-full mt-1 font-mono"
                    value={form.dtc_code}
                    onChange={(e) => setForm((f) => ({ ...f, dtc_code: e.target.value }))}
                    placeholder="P0300"
                  />
                </div>
              )}

              {form.rule_type === 'scheduled' && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="filter-label">Counter *</label>
                    <select
                      className="filter-select w-full mt-1"
                      value={form.sensor_type}
                      onChange={(e) => setForm((f) => ({ ...f, sensor_type: e.target.value }))}
                    >
                      <option value="">Select…</option>
                      <option value="odometer">Odometer (km)</option>
                      <option value="engine_hours">Engine hours</option>
                    </select>
                  </div>
                  <div>
                    <label className="filter-label">Interval *</label>
                    <input
                      type="number"
                      min={1}
                      className="filter-select w-full mt-1"
                      value={form.interval_value}
                      onChange={(e) => setForm((f) => ({ ...f, interval_value: e.target.value }))}
                      placeholder="10000"
                    />
                  </div>
                </div>
              )}

              {form.rule_type === 'behavior' && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="filter-label">Event type *</label>
                    <select
                      className="filter-select w-full mt-1"
                      value={form.sensor_type}
                      onChange={(e) => setForm((f) => ({ ...f, sensor_type: e.target.value }))}
                    >
                      <option value="">Select…</option>
                      {BEHAVIOR_EVENTS.map((e) => (
                        <option key={e} value={e}>{e.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="filter-label">Count / day *</label>
                    <input
                      type="number"
                      min={1}
                      className="filter-select w-full mt-1"
                      value={form.threshold_value}
                      onChange={(e) => setForm((f) => ({
                        ...f,
                        threshold_value: e.target.value,
                        operator: '>=',
                        duration_seconds: '86400',
                      }))}
                      placeholder="5"
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="filter-label">Severity</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.severity}
                    onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value as AlertSeverity }))}
                  >
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div>
                  <label className="filter-label">Work order template</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.work_order_template_id}
                    onChange={(e) => setForm((f) => ({ ...f, work_order_template_id: e.target.value }))}
                  >
                    <option value="">None (alert only)</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
                Active
              </label>

              {formError && (
                <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                  {formError}
                </p>
              )}
            </div>
            <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => setShowForm(false)} disabled={saving}>
                Cancel
              </button>
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Create rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
