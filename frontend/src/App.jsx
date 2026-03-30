import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import Dashboard from './views/Dashboard';
import Prompts from './views/Prompts';
import RunDetail from './views/RunDetail';
import Experiments from './views/Experiments';
import ExperimentDetail from './views/ExperimentDetail';
import PromptDetail from './views/PromptDetail';
import Research from './views/Research';
import SessionReport from './views/SessionReport';
import Settings from './views/Settings';
import Costs from './views/Costs';

const navItems = [
  { to: '/',            label: 'Dashboard'    },
  { to: '/prompts',     label: 'Prompts'      },
  { to: '/research',    label: 'Research'     },
  { to: '/experiments', label: 'Experiments'  },
  { to: '/costs',       label: 'Costs'        },
  { to: '/settings',    label: 'Settings'     },
];

function NavBar() {
  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
      <span className="font-bold text-lg text-indigo-600">AEO Insights</span>
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          className={({ isActive }) =>
            `text-sm font-medium ${isActive ? 'text-indigo-600' : 'text-gray-500 hover:text-gray-700'}`
          }
        >
          {item.label}
        </NavLink>
      ))}
      <div className="ml-auto">
        <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
          Local
        </span>
      </div>
    </nav>
  );
}

function AppRoutes() {
  return (
    <>
      <NavBar />
      <main className="max-w-7xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/"                              element={<Dashboard />} />
          <Route path="/prompts"                       element={<Prompts />} />
          <Route path="/prompts/:id"                   element={<PromptDetail />} />
          <Route path="/runs/:id"                      element={<RunDetail />} />
          <Route path="/experiments"                   element={<Experiments />} />
          <Route path="/experiments/:id"               element={<ExperimentDetail />} />
          <Route path="/research"                      element={<Research />} />
          <Route path="/research/session/:sessionId"   element={<SessionReport />} />
          <Route path="/costs"                         element={<Costs />} />
          <Route path="/settings"                      element={<Settings />} />
        </Routes>
      </main>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="min-h-screen">
          <AppRoutes />
        </div>
      </AuthProvider>
    </BrowserRouter>
  );
}
