/**
 * PREDICT — Assets Page
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Fleet, Vehicle, Component, Sensor } from '../types';
import Badge from '../components/ui/Badge';
import LoadingState from '../components/ui/LoadingState';
import PageHeader from '../components/ui/PageHeader';

const healthTone: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  green: 'success',
  yellow: 'warning',
  red: 'danger',
  grey: 'neutral',
};

export default function AssetsPage() {
  const [fleets, setFleets] = useState<Fleet[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [components, setComponents] = useState<Component[]>([]);
  const [selectedComponent, setSelectedComponent] = useState<Component | null>(null);
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchVehicles = useCallback(async () => {
    try {
      const v = await api.getVehicles();
      setVehicles(v);
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

  useEffect(() => {
    fetchFleets();
    fetchVehicles();
  }, [fetchFleets, fetchVehicles]);

  const selectVehicle = useCallback(async (v: Vehicle) => {
    setSelectedVehicle(v);
    setSelectedComponent(null);
    setSensors([]);
    try {
      const c = await api.getComponents(v.id);
      setComponents(c);
    } catch (e) {
      console.error('Failed to fetch components:', e);
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

  if (loading) {
    return <LoadingState message="Loading assets…" />;
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Assets"
        description="Browse fleet → vehicle → component → sensor"
      />

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
          <header className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900">Vehicles ({vehicles.length})</h2>
          </header>
          <div className="max-h-[420px] overflow-y-auto">
            {vehicles.map((v) => (
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
                    <p className="text-sm text-gray-600">{v.make} {v.model}</p>
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
            ))}
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
    </div>
  );
}
