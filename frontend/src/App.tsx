/**
 * PREDICT — Main App Component
 * Routing + Layout + WebSocket connection
 */
import { Routes, Route, NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Truck,
  ClipboardList,
  Bell,
  Settings,
  Activity,
} from 'lucide-react';
import { useWebSocket } from './hooks/useWebSocket';
import DashboardPage from './pages/DashboardPage';
import AssetsPage from './pages/AssetsPage';
import WorkOrdersPage from './pages/WorkOrdersPage';
import AlertsPage from './pages/AlertsPage';
import RulesPage from './pages/RulesPage';
import { useState, useCallback } from 'react';
import type { WSMessage } from './types';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/assets', label: 'Assets', icon: Truck },
  { to: '/workorders', label: 'Work Orders', icon: ClipboardList },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/rules', label: 'Rules', icon: Settings },
];

function App() {
  const [wsMessages, setWsMessages] = useState<WSMessage[]>([]);

  const handleWsMessage = useCallback((msg: WSMessage) => {
    setWsMessages((prev) => [...prev.slice(-99), msg]);
  }, []);

  const { connected } = useWebSocket(handleWsMessage);

  return (
    <div className="flex h-screen bg-gray-50">
      {/* ── Sidebar ─────────────────────────────────────────────── */}
      <aside className="w-64 bg-predict-900 text-white flex flex-col">
        <div className="p-4 border-b border-predict-800">
          <div className="flex items-center gap-2">
            <Activity className="w-8 h-8 text-predict-400" />
            <div>
              <h1 className="text-lg font-bold">PREDICT</h1>
              <p className="text-xs text-predict-300">Predictive Maintenance</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg mb-1 transition-colors ${
                  isActive
                    ? 'bg-predict-700 text-white'
                    : 'text-predict-200 hover:bg-predict-800 hover:text-white'
                }`
              }
            >
              <item.icon className="w-5 h-5" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-predict-800">
          <div className="flex items-center gap-2 text-sm">
            <div
              className={`w-2 h-2 rounded-full ${
                connected ? 'bg-green-400 animate-pulse' : 'bg-red-400'
              }`}
            />
            <span className="text-predict-300">
              {connected ? 'Live' : 'Disconnected'}
            </span>
          </div>
        </div>
      </aside>

      {/* ── Main Content ────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<DashboardPage wsMessages={wsMessages} />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/workorders" element={<WorkOrdersPage wsMessages={wsMessages} />} />
          <Route path="/alerts" element={<AlertsPage wsMessages={wsMessages} />} />
          <Route path="/rules" element={<RulesPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;