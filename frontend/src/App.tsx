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
    <div className="flex h-screen bg-gray-100">
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col shrink-0">
        <div className="px-4 py-5 border-b border-gray-200">
          <h1 className="text-lg font-semibold text-gray-900">PREDICT</h1>
          <p className="text-xs text-gray-500 mt-0.5">Predictive Maintenance</p>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2.5 rounded-md text-sm font-medium ${
                  isActive
                    ? 'bg-predict-50 text-predict-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`
              }
            >
              <item.icon className="w-4 h-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-3 border-t border-gray-200">
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${connected ? 'bg-green-500' : 'bg-red-500'}`}
              aria-hidden
            />
            {connected ? 'Connected' : 'Disconnected'}
          </div>
        </div>
      </aside>

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
