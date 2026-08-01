/**
 * PREDICT — Main App Component
 * Routing + Layout. The WebSocket connection lives in WsProvider; pages
 * subscribe to the channels they need instead of receiving a message array.
 */
import { Routes, Route, NavLink, Link } from 'react-router-dom';
import {
  LayoutDashboard,
  Truck,
  ClipboardList,
  Bell,
  SlidersHorizontal,
  Gauge,
} from 'lucide-react';
import { WsProvider, useWsConnected } from './ws/WsContext';
import DashboardPage from './pages/DashboardPage';
import AssetsPage from './pages/AssetsPage';
import WorkOrdersPage from './pages/WorkOrdersPage';
import AlertsPage from './pages/AlertsPage';
import RulesPage from './pages/RulesPage';
import VehicleDetailPage from './pages/VehicleDetailPage';
import DrivingPage from './pages/DrivingPage';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/assets', label: 'Assets', icon: Truck },
  { to: '/driving', label: 'Driving', icon: Gauge },
  { to: '/workorders', label: 'Work Orders', icon: ClipboardList },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/rules', label: 'Rules', icon: SlidersHorizontal },
];

function ConnectionStatus() {
  const connected = useWsConnected();
  return (
    <div className="flex items-center gap-2 text-sm text-gray-600">
      <span
        className={`w-2 h-2 rounded-full shrink-0 ${connected ? 'bg-green-500' : 'bg-red-500'}`}
        aria-hidden
      />
      {connected ? 'Connected' : 'Disconnected'}
    </div>
  );
}

function NotFound() {
  return (
    <div className="page-content flex flex-col items-center justify-center py-24 text-center">
      <p className="text-5xl font-semibold text-gray-300">404</p>
      <p className="mt-3 text-gray-600">This page doesn't exist.</p>
      <Link to="/" className="btn-primary mt-6">Back to dashboard</Link>
    </div>
  );
}

function App() {
  return (
    <WsProvider>
      <div className="flex h-screen bg-gray-100">
        <aside className="w-56 bg-white border-r border-gray-200 flex-col shrink-0 hidden md:flex">
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
            <ConnectionStatus />
          </div>
        </aside>

        <div className="flex-1 flex flex-col min-w-0">
          {/* Compact top bar on small screens where the sidebar is hidden */}
          <div className="md:hidden bg-white border-b border-gray-200 px-3 py-2 flex items-center gap-1 overflow-x-auto">
            <span className="text-sm font-semibold text-gray-900 mr-2 shrink-0">PREDICT</span>
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `px-2.5 py-1.5 rounded-md text-xs font-medium shrink-0 ${
                    isActive ? 'bg-predict-50 text-predict-700' : 'text-gray-600'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>

          <main className="flex-1 overflow-auto">
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/assets" element={<AssetsPage />} />
              <Route path="/vehicles/:vehicleId" element={<VehicleDetailPage />} />
              <Route path="/driving" element={<DrivingPage />} />
              <Route path="/workorders" element={<WorkOrdersPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/rules" element={<RulesPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </main>
        </div>
      </div>
    </WsProvider>
  );
}

export default App;
