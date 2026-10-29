import { StrictMode } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { hasSession } from './lib/api';
import { AuthPage } from './pages/Auth';
import { AvailabilityPage } from './pages/Availability';
import { DashboardPage } from './pages/Dashboard';
import { IntegrationsPage } from './pages/Integrations';
import { JobsPage } from './pages/Jobs';
import { PayoutsOnboarding } from './pages/Payouts';
import { SettingsPage } from './pages/Settings';
import { TechniciansPage } from './pages/Technicians';
import './styles.css';

function RequireSession({ children }: { children: ReactNode }) {
  return hasSession() ? children : <Navigate to="/login" replace />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<AuthPage />} />
        <Route element={<RequireSession><Layout /></RequireSession>}>
          <Route index element={<DashboardPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="technicians" element={<TechniciansPage />} />
          <Route path="availability" element={<AvailabilityPage />} />
          <Route path="integrations" element={<IntegrationsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="onboarding/payouts" element={<PayoutsOnboarding />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
