/**
 * PREDICT — TelemetryCatalogPanel
 * Preview of parameters the stack decodes per Teltonika device model.
 */
import { useMemo, useState } from 'react';
import type { DeviceTelemetryCatalog, TelemetryCatalogSensorItem } from '../../types';
import Badge from '../ui/Badge';

interface Props {
  catalog: DeviceTelemetryCatalog[];
  note: string;
}

const sourceTone: Record<string, 'neutral' | 'info' | 'purple'> = {
  standard: 'neutral',
  obd: 'info',
  can: 'purple',
};

const sourceLabel: Record<string, string> = {
  standard: 'Standard',
  obd: 'OBD-II',
  can: 'CAN',
};

function groupByComponent(sensors: TelemetryCatalogSensorItem[]) {
  const groups = new Map<string, TelemetryCatalogSensorItem[]>();
  for (const s of sensors) {
    const list = groups.get(s.component) ?? [];
    list.push(s);
    groups.set(s.component, list);
  }
  return groups;
}

export default function TelemetryCatalogPanel({ catalog, note }: Props) {
  const [activeTab, setActiveTab] = useState(catalog[0]?.device_type ?? 'fmc001');
  const model = catalog.find((m) => m.device_type === activeTab) ?? catalog[0];
  const grouped = useMemo(
    () => (model ? groupByComponent(model.sensors) : new Map<string, TelemetryCatalogSensorItem[]>()),
    [model]
  );

  if (!model) return null;

  return (
    <div className="panel mt-6 text-left overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <h3 className="text-base font-semibold text-gray-900">Telemetry we will read</h3>
        <p className="text-sm text-gray-600 mt-1">
          Parameters decoded from Teltonika AVL records — shown here before any vehicle connects.
        </p>
      </div>

      <div className="px-4 pt-4 border-b border-gray-200">
        <div className="flex gap-2">
          {catalog.map((m) => (
            <button
              key={m.device_type}
              type="button"
              onClick={() => setActiveTab(m.device_type)}
              className={`px-3 py-1.5 text-sm font-medium rounded-t-md border-b-2 -mb-px transition-colors ${
                activeTab === m.device_type
                  ? 'border-predict-500 text-predict-700 bg-white'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4 space-y-6">
        <p className="text-sm text-gray-600">{model.description}</p>

        <section>
          <h4 className="text-sm font-semibold text-gray-900 mb-2">Dashboard sensors</h4>
          <div className="space-y-4">
            {[...grouped.entries()].map(([component, sensors]) => (
              <div key={component}>
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-2">
                  {component}
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 border-b border-gray-100">
                        <th className="py-2 pr-4 font-medium">Parameter</th>
                        <th className="py-2 pr-4 font-medium">AVL ID</th>
                        <th className="py-2 pr-4 font-medium">Unit</th>
                        <th className="py-2 font-medium">Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sensors.map((s) => (
                        <tr key={s.sensor_type} className="border-b border-gray-50">
                          <td className="py-2 pr-4 text-gray-900">{s.name}</td>
                          <td className="py-2 pr-4 tabular-nums text-gray-600">
                            {s.io_element_id ?? '—'}
                          </td>
                          <td className="py-2 pr-4 text-gray-600">{s.unit || '—'}</td>
                          <td className="py-2">
                            <Badge tone={sourceTone[s.source] ?? 'neutral'}>
                              {sourceLabel[s.source] ?? s.source}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h4 className="text-sm font-semibold text-gray-900 mb-2">Meta &amp; diagnostics</h4>
          <ul className="text-sm space-y-2">
            {model.meta.map((m) => (
              <li key={m.field} className="flex flex-wrap gap-x-2 gap-y-1">
                <span className="font-medium text-gray-900">{m.name}</span>
                {m.io_element_id != null && (
                  <span className="text-gray-500 tabular-nums">AVL {m.io_element_id}</span>
                )}
                {m.note && <span className="text-gray-600">— {m.note}</span>}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4 className="text-sm font-semibold text-gray-900 mb-2">GNSS (every record)</h4>
          <p className="text-sm text-gray-600">
            {model.gps.map((g) => `${g.name}${g.unit ? ` (${g.unit})` : ''}`).join(' · ')}
          </p>
        </section>

        <p className="text-xs text-gray-500 border-t border-gray-100 pt-4">{note}</p>
      </div>
    </div>
  );
}
