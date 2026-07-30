/**
 * PREDICT — Assets Page
 * Fleet → Vehicle → Component → Sensor hierarchy browser.
 */
import { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { Fleet, Vehicle, Component, Sensor } from '../types';
import { ChevronRight, Truck, Cog, Gauge } from 'lucide-react';

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

  const healthColor = (health: string) => {
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
        <div className="text-gray-500 text-lg">Loading assets...</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Asset Registry</h1>
      <p className="text-sm text-gray-500 mb-6">Fleet → Vehicle → Component → Sensor hierarchy</p>

      {/* ── Fleets ───────────────────────────────────────────────── */}
      {fleets.length > 0 && (
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Fleets</h2>
          <div className="flex gap-2">
            {fleets.map((f) => (
              <div key={f.id} className="px-4 py-2 bg-predict-50 text-predict-700 rounded-lg border border-predict-200">
                <span className="font-medium">{f.name}</span>
                <span className="ml-2 text-xs text-predict-500">({f.vehicle_count} vehicles)</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* ── Vehicles ────────────────────────────────────────────── */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Truck className="w-4 h-4" /> Vehicles ({vehicles.length})
            </h2>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {vehicles.map((v) => (
              <button
                key={v.id}
                onClick={() => selectVehicle(v)}
                className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                  selectedVehicle?.id === v.id ? 'bg-predict-50 border-l-4 border-l-predict-500' : ''
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900 text-sm">{v.name}</p>
                    <p className="text-xs text-gray-500">{v.make} {v.model} · {v.license_plate || 'No plate'}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${healthColor(v.health)}`} />
                    {v.active_alert_count ? (
                      <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full font-bold">
                        {v.active_alert_count}
                      </span>
                    ) : null}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* ── Components ─────────────────────────────────────────── */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Cog className="w-4 h-4" /> Components
            </h2>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {selectedVehicle ? (
              components.length > 0 ? (
                components.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => selectComponent(c)}
                    className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                      selectedComponent?.id === c.id ? 'bg-predict-50 border-l-4 border-l-predict-500' : ''
                    }`}
                  >
                    <p className="font-medium text-gray-900 text-sm">{c.name}</p>
                    <p className="text-xs text-gray-500">{c.component_type} · {c.sensor_count} sensors</p>
                  </button>
                ))
              ) : (
                <p className="px-4 py-8 text-center text-gray-400 text-sm">No components</p>
              )
            ) : (
              <p className="px-4 py-8 text-center text-gray-400 text-sm">Select a vehicle</p>
            )}
          </div>
        </div>

        {/* ── Sensors ─────────────────────────────────────────────── */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Gauge className="w-4 h-4" /> Sensors
            </h2>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {selectedComponent ? (
              sensors.length > 0 ? (
                sensors.map((s) => (
                  <div key={s.id} className="px-4 py-3 border-b border-gray-100">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="font-medium text-gray-900 text-sm">{s.name}</p>
                        <p className="text-xs text-gray-500">{s.sensor_type} · {s.unit}</p>
                      </div>
                      <div className="text-right text-xs text-gray-500">
                        {s.io_element_id && <p>IO: {s.io_element_id}</p>}
                        {s.warning_threshold !== null && s.warning_threshold !== undefined && (
                          <p>Warn: {s.warning_threshold}{s.unit}</p>
                        )}
                        {s.critical_threshold !== null && s.critical_threshold !== undefined && (
                          <p className="text-red-600">Crit: {s.critical_threshold}{s.unit}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <p className="px-4 py-8 text-center text-gray-400 text-sm">No sensors</p>
              )
            ) : (
              <p className="px-4 py-8 text-center text-gray-400 text-sm">Select a component</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}