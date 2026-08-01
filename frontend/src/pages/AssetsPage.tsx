/**
 * PREDICT — Assets Page
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type {
  Fleet,
  Vehicle,
  Component,
  Sensor,
  MaintenanceHistory,
  AssetHealth,
  WSMessage,
  DeviceType,
} from '../types';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';
import {
  HOST_PLACEHOLDER,
  TRACKER_PORT,
  smsGuidance,
  smsTemplates,
  templateHost,
  trackerServerHost,
} from '../utils/smsConfig';

const healthTone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  green: 'success',
  yellow: 'warning',
  red: 'danger',
  grey: 'neutral',
};

const healthOrder: Record<AssetHealth, number> = {
  red: 0,
  yellow: 1,
  green: 2,
  grey: 3,
};

const emptyForm = {
  name: '',
  license_plate: '',
  imei: '',
  device_type: 'fmc001' as DeviceType,
  sim_phone: '',
  make: '',
  model: '',
  year: '',
  vin: '',
  fleet_id: '',
};

export default function AssetsPage({ wsMessages }: { wsMessages: WSMessage[] }) {
  const [fleets, setFleets] = useState<Fleet[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [selectedComponent, setSelectedComponent] = useState<Component | null>(null);
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [history, setHistory] = useState<MaintenanceHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [smsVehicle, setSmsVehicle] = useState<Vehicle | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const lastWsIdx = useRef(0);
  const refreshTimer = useRef<number | null>(null);

  const sortVehicles = (list: Vehicle[]) =>
    [...list].sort((a, b) => {
      const healthDiff = healthOrder[a.health] - healthOrder[b.health];
      if (healthDiff !== 0) return healthDiff;
      return (b.active_alert_count ?? 0) - (a.active_alert_count ?? 0);
    });

  const fetchVehicles = useCallback(async () => {
    try {
      const v = await api.getVehicles();
      setVehicles(sortVehicles(v));
      setSelectedVehicle((prev) => {
        if (!prev) return prev;
        const updated = v.find((x) => x.id === prev.id);
        return updated ? { ...prev, ...updated } : prev;
      });
    } catch (e) {
      console.error('Failed to fetch vehicles:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchFleets = useCallback(async () => {
    try {
      const f = await api.getFleets();
      setFleets(f);
    } catch (e) {
      console.error('Failed to fetch fleets:', e);
    }
  }, []);

  const fetchHistory = useCallback(async (vehicleId: number) => {
    try {
      const h = await api.getVehicleHistory(vehicleId);
      setHistory(h);
    } catch (e) {
      console.error('Failed to fetch maintenance history:', e);
      setHistory([]);
    }
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => fetchVehicles(), 1500);
  }, [fetchVehicles]);

  useEffect(() => {
    fetchFleets();
    fetchVehicles();
    const interval = setInterval(fetchVehicles, 15_000);
    return () => clearInterval(interval);
  }, [fetchFleets, fetchVehicles]);

  useEffect(() => {
    for (let i = lastWsIdx.current; i < wsMessages.length; i++) {
      const msg = wsMessages[i];
      if (msg.channel === 'ws:health') {
        const vehicleId = msg.data?.vehicle_id;
        const health = msg.data?.health;
        if (vehicleId && health) {
          setVehicles((prev) =>
            sortVehicles(
              prev.map((v) =>
                v.id === vehicleId ? { ...v, health: health as AssetHealth } : v
              )
            )
          );
          setSelectedVehicle((prev) => {
            if (!prev || prev.id !== vehicleId) return prev;
            return { ...prev, health: health as AssetHealth };
          });
        }
      } else if (msg.channel === 'ws:alerts' || msg.channel === 'ws:workorders') {
        scheduleRefresh();
        if (selectedVehicle && msg.channel === 'ws:workorders') {
          const vehicleId = msg.data?.vehicle_id;
          if (vehicleId === selectedVehicle.id) {
            fetchHistory(selectedVehicle.id);
          }
        }
      }
    }
    lastWsIdx.current = wsMessages.length;
  }, [wsMessages, scheduleRefresh, selectedVehicle, fetchHistory]);

  const selectVehicle = useCallback(async (v: Vehicle) => {
    setSelectedVehicle(v);
    setSelectedComponent(null);
    setSensors([]);
    setHistory([]);
    try {
      const [c, h] = await Promise.all([
        api.getComponents(v.id),
        api.getVehicleHistory(v.id),
      ]);
      setComponents(c);
      setHistory(h);
    } catch (e) {
      console.error('Failed to fetch vehicle details:', e);
    }
  }, []);

  const selectComponent = useCallback(async (c: Component) => {
    setSelectedComponent(c);
    try {
      const s = await api.getSensors(c.id);
      setSensors(s);
    } catch (e) {
      console.error('Failed to fetch sensors:', e);
    }
  }, []);

  const openRegister = () => {
    setForm(emptyForm);
    setRegisterError(null);
    setShowRegister(true);
  };

  const handleRegister = async () => {
    const name = form.name.trim();
    const imei = form.imei.trim();
    if (!name || !imei) {
      setRegisterError('Name and IMEI are required.');
      return;
    }
    if (!/^\d{15}$/.test(imei)) {
      setRegisterError('IMEI must be exactly 15 digits.');
      return;
    }
    setRegistering(true);
    setRegisterError(null);
    try {
      const yearNum = form.year.trim() ? Number(form.year) : undefined;
      const fleetNum = form.fleet_id ? Number(form.fleet_id) : undefined;
      const created = await api.registerVehicle({
        name,
        imei,
        device_type: form.device_type,
        license_plate: form.license_plate.trim() || undefined,
        sim_phone: form.sim_phone.trim() || undefined,
        make: form.make.trim() || undefined,
        model: form.model.trim() || undefined,
        year: Number.isFinite(yearNum) ? yearNum : undefined,
        vin: form.vin.trim() || undefined,
        fleet_id: Number.isFinite(fleetNum) ? fleetNum : undefined,
      });
      setShowRegister(false);
      setForm(emptyForm);
      await fetchVehicles();
      await selectVehicle(created);
      setSmsVehicle(created);
      setCopyStatus(null);
    } catch (e) {
      setRegisterError(e instanceof Error ? e.message : 'Registration failed');
    } finally {
      setRegistering(false);
    }
  };

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus(`Copied ${label}`);
    } catch {
      setCopyStatus('Copy failed — select the text manually');
    }
  };

  if (loading) {
    return <LoadingState message="Loading assets…" />;
  }

  const sms = smsVehicle
    ? smsGuidance(smsVehicle.device_type ?? 'fmc001', templateHost())
    : null;
  const host = templateHost();
  const hostConfigured = Boolean(trackerServerHost());
  const templates = smsTemplates(host);

  return (
    <div className="page-content">
      <PageHeader
        title="Assets"
        description="Register vehicles, then configure the tracker via SMS from your phone"
        actions={
          <button type="button" onClick={openRegister} className="btn-primary">
            Register vehicle
          </button>
        }
      />

      <section className="panel mb-6">
        <header className="px-4 py-3 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">SMS config templates</h2>
          <p className="text-sm text-gray-600 mt-1">
            Send from your phone to the device SIM — PREDICT does not send SMS.
            Target server:{' '}
            <span className="font-mono text-gray-900">
              {host}:{TRACKER_PORT}
            </span>
            {!hostConfigured && (
              <span className="text-amber-700">
                {' '}
                (set <span className="font-mono">VITE_TRACKER_SERVER</span> in{' '}
                <span className="font-mono">.env</span> to replace {HOST_PLACEHOLDER})
              </span>
            )}
          </p>
        </header>
        <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {templates.map((t) => (
            <div key={t.id} className="rounded-md border border-gray-200 bg-gray-50 p-3">
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="text-sm font-medium text-gray-900">{t.title}</h3>
                <button
                  type="button"
                  className="btn-secondary text-xs shrink-0"
                  onClick={() => copyText(t.body, t.title)}
                >
                  Copy
                </button>
              </div>
              <pre className="text-xs font-mono whitespace-pre-wrap break-all text-gray-800 bg-white border border-gray-200 rounded-md p-3">
                {t.body}
              </pre>
              <p className="text-xs text-gray-600 mt-2">{t.hint}</p>
            </div>
          ))}
        </div>
        {copyStatus && !smsVehicle && (
          <p className="px-4 pb-3 text-xs text-green-700">{copyStatus}</p>
        )}
      </section>

      {fleets.length > 0 && (
        <div className="mb-6">
          <h2 className="section-title">Fleets</h2>
          <div className="flex flex-wrap gap-2">
            {fleets.map((f) => (
              <div key={f.id} className="panel px-4 py-2 text-sm">
                <span className="font-medium text-gray-900">{f.name}</span>
                <span className="text-gray-500 ml-2">({f.vehicle_count} vehicles)</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <section className="panel">
          <header className="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
            <h2 className="font-semibold text-gray-900">Vehicles ({vehicles.length})</h2>
            <button type="button" onClick={openRegister} className="btn-secondary text-xs">
              Register
            </button>
          </header>
          <div className="max-h-[420px] overflow-y-auto">
            {vehicles.length === 0 ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">
                No vehicles yet. Register a Teltonika-equipped car to get started.
              </p>
            ) : (
              vehicles.map((v) => (
                <button
                  key={v.id}
                  onClick={() => selectVehicle(v)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 ${
                    selectedVehicle?.id === v.id ? 'bg-predict-50 border-l-4 border-l-predict-500' : ''
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium text-gray-900">{v.name}</p>
                      <p className="text-sm text-gray-600">
                        {(v.device_type || 'fmc001').toUpperCase()}
                        {v.sim_phone ? ` · ${v.sim_phone}` : ''}
                      </p>
                      <p className="text-sm text-gray-500">{v.license_plate || 'No plate'}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <Badge tone={healthTone[v.health] ?? 'neutral'}>{v.health}</Badge>
                      {!!v.active_alert_count && (
                        <span className="text-xs text-red-700">{v.active_alert_count} alert(s)</span>
                      )}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="panel">
          <header className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900">Components</h2>
          </header>
          <div className="max-h-[420px] overflow-y-auto">
            {!selectedVehicle ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">Select a vehicle</p>
            ) : components.length === 0 ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">No components</p>
            ) : (
              components.map((c) => (
                <button
                  key={c.id}
                  onClick={() => selectComponent(c)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 ${
                    selectedComponent?.id === c.id ? 'bg-predict-50 border-l-4 border-l-predict-500' : ''
                  }`}
                >
                  <p className="font-medium text-gray-900">{c.name}</p>
                  <p className="text-sm text-gray-600">{c.component_type} · {c.sensor_count} sensors</p>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="panel">
          <header className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900">Sensors</h2>
          </header>
          <div className="max-h-[420px] overflow-y-auto">
            {!selectedComponent ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">Select a component</p>
            ) : sensors.length === 0 ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">No sensors</p>
            ) : (
              sensors.map((s) => (
                <div key={s.id} className="px-4 py-3 border-b border-gray-100">
                  <p className="font-medium text-gray-900">{s.name}</p>
                  <p className="text-sm text-gray-600">{s.sensor_type} · {s.unit}</p>
                  <dl className="mt-2 text-sm space-y-1">
                    {s.io_element_id && (
                      <div className="flex justify-between gap-4">
                        <dt className="text-gray-500">IO element</dt>
                        <dd className="text-gray-900">{s.io_element_id}</dd>
                      </div>
                    )}
                    {s.warning_threshold != null && (
                      <div className="flex justify-between gap-4">
                        <dt className="text-gray-500">Warning</dt>
                        <dd className="text-amber-700 tabular-nums">{s.warning_threshold}{s.unit}</dd>
                      </div>
                    )}
                    {s.critical_threshold != null && (
                      <div className="flex justify-between gap-4">
                        <dt className="text-gray-500">Critical</dt>
                        <dd className="text-red-700 tabular-nums">{s.critical_threshold}{s.unit}</dd>
                      </div>
                    )}
                  </dl>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {selectedVehicle && (
        <section className="panel mt-4">
          <header className="px-4 py-3 border-b border-gray-200 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-semibold text-gray-900">{selectedVehicle.name}</h2>
              <p className="text-sm text-gray-600 mt-0.5">
                IMEI {selectedVehicle.imei}
                {' · '}
                {(selectedVehicle.device_type || 'fmc001').toUpperCase()}
                {selectedVehicle.sim_phone ? ` · SIM ${selectedVehicle.sim_phone}` : ''}
                {selectedVehicle.license_plate ? ` · ${selectedVehicle.license_plate}` : ''}
              </p>
            </div>
            <button
              type="button"
              className="btn-secondary text-sm"
              onClick={() => {
                setSmsVehicle(selectedVehicle);
                setCopyStatus(null);
              }}
            >
              SMS config helper
            </button>
          </header>
          <header className="px-4 py-2 border-b border-gray-100">
            <h3 className="text-sm font-medium text-gray-700">Maintenance history</h3>
          </header>
          <div className="max-h-[320px] overflow-y-auto">
            {history.length === 0 ? (
              <p className="px-4 py-8 text-sm text-gray-500 text-center">
                No maintenance events recorded yet.
              </p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {history.map((entry) => (
                  <li key={entry.id} className="px-4 py-3">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="font-medium text-gray-900">{entry.title}</p>
                        {entry.description && (
                          <p className="text-sm text-gray-600 mt-0.5">{entry.description}</p>
                        )}
                        {entry.performed_by && (
                          <p className="text-xs text-gray-500 mt-1">By {entry.performed_by}</p>
                        )}
                      </div>
                      <div className="text-right shrink-0">
                        <Badge tone="neutral">{entry.event_type.replace('_', ' ')}</Badge>
                        <p className="text-xs text-gray-500 mt-1">
                          {new Date(entry.event_date).toLocaleString()}
                        </p>
                        {entry.work_order_id && (
                          <p className="text-xs text-gray-400">WO #{entry.work_order_id}</p>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {showRegister && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="panel max-w-lg w-full shadow-lg max-h-[90vh] overflow-y-auto">
            <div className="px-5 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">Register vehicle</h3>
              <p className="text-sm text-gray-600 mt-1">
                Saves the module in PREDICT. Configure the tracker separately via SMS.
              </p>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="filter-label">Name *</label>
                <input
                  className="filter-select w-full mt-1"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="My Car"
                />
              </div>
              <div>
                <label className="filter-label">IMEI * (15 digits)</label>
                <input
                  className="filter-select w-full mt-1 font-mono"
                  value={form.imei}
                  onChange={(e) => setForm((f) => ({ ...f, imei: e.target.value.replace(/\D/g, '').slice(0, 15) }))}
                  placeholder="867648042983435"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="filter-label">Device type</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.device_type}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, device_type: e.target.value as DeviceType }))
                    }
                  >
                    <option value="fmc001">FMC001 (OBD-II)</option>
                    <option value="fmc150">FMC150 (CAN)</option>
                  </select>
                </div>
                <div>
                  <label className="filter-label">License plate</label>
                  <input
                    className="filter-select w-full mt-1"
                    value={form.license_plate}
                    onChange={(e) => setForm((f) => ({ ...f, license_plate: e.target.value }))}
                  />
                </div>
              </div>
              <div>
                <label className="filter-label">SIM phone (for SMS config)</label>
                <input
                  className="filter-select w-full mt-1"
                  value={form.sim_phone}
                  onChange={(e) => setForm((f) => ({ ...f, sim_phone: e.target.value }))}
                  placeholder="+60123456789"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="filter-label">Make</label>
                  <input
                    className="filter-select w-full mt-1"
                    value={form.make}
                    onChange={(e) => setForm((f) => ({ ...f, make: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="filter-label">Model</label>
                  <input
                    className="filter-select w-full mt-1"
                    value={form.model}
                    onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="filter-label">Year</label>
                  <input
                    className="filter-select w-full mt-1"
                    value={form.year}
                    onChange={(e) => setForm((f) => ({ ...f, year: e.target.value.replace(/\D/g, '').slice(0, 4) }))}
                  />
                </div>
                <div>
                  <label className="filter-label">Fleet</label>
                  <select
                    className="filter-select w-full mt-1"
                    value={form.fleet_id}
                    onChange={(e) => setForm((f) => ({ ...f, fleet_id: e.target.value }))}
                  >
                    <option value="">None</option>
                    {fleets.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="filter-label">VIN</label>
                <input
                  className="filter-select w-full mt-1 font-mono"
                  value={form.vin}
                  onChange={(e) => setForm((f) => ({ ...f, vin: e.target.value }))}
                />
              </div>
              {registerError && (
                <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                  {registerError}
                </p>
              )}
            </div>
            <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowRegister(false)}
                disabled={registering}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={handleRegister}
                disabled={registering}
              >
                {registering ? 'Registering…' : 'Register'}
              </button>
            </div>
          </div>
        </div>
      )}

      {smsVehicle && sms && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="panel max-w-lg w-full shadow-lg">
            <div className="px-5 py-4 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">Configure via SMS</h3>
              <p className="text-sm text-gray-600 mt-1">
                {smsVehicle.name}
                {smsVehicle.sim_phone ? ` · send to ${smsVehicle.sim_phone}` : ' · add a SIM phone on the vehicle if needed'}
              </p>
            </div>
            <div className="p-5 space-y-3">
              <p className="text-sm text-gray-700">
                Send this SMS from your phone — PREDICT does not send it.
              </p>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">{sms.title}</p>
                {sms.body ? (
                  <pre className="text-xs bg-gray-50 border border-gray-200 rounded-md p-3 whitespace-pre-wrap break-all font-mono">
                    {sms.body}
                  </pre>
                ) : (
                  <p className="text-sm text-amber-800 bg-amber-50 border border-amber-100 rounded-md p-3">
                    {sms.note}
                  </p>
                )}
              </div>
              {sms.body && (
                <p className="text-xs text-gray-600">{sms.note}</p>
              )}
              {copyStatus && <p className="text-xs text-green-700">{copyStatus}</p>}
            </div>
            <div className="px-5 py-4 border-t border-gray-200 flex flex-wrap justify-end gap-2">
              {smsVehicle.sim_phone && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => copyText(smsVehicle.sim_phone!, 'SIM number')}
                >
                  Copy SIM
                </button>
              )}
              {sms.body && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => copyText(sms.body, 'SMS body')}
                >
                  Copy SMS
                </button>
              )}
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  setSmsVehicle(null);
                  setCopyStatus(null);
                }}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
