import { StrictMode } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { hasSession } from './lib/api';
import { AdminPage } from './pages/Admin';
import { AuthPage } from './pages/Auth';
import { AvailabilityPage } from './pages/Availability';
import { ComplaintsPage } from './pages/Complaints';
import { CustomersPage } from './pages/Customers';
import { DashboardPage } from './pages/Dashboard';
import { IntegrationsPage } from './pages/Integrations';
import { JobsPage } from './pages/Jobs';
import { PayoutsOnboarding } from './pages/Payouts';
import { SettingsPage } from './pages/Settings';
import { StartPage } from './pages/Start';
import { TechniciansPage } from './pages/Technicians';
import { VerifyEmailPage } from './pages/VerifyEmail';
import './styles.css';

function RequireSession({ children }: { children: ReactNode }) {
  return hasSession() ? children : <Navigate to="/start" replace />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/start" element={<StartPage />} />
        <Route path="/login" element={<AuthPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route element={<RequireSession><Layout /></RequireSession>}>
          <Route index element={<DashboardPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="technicians" element={<TechniciansPage />} />
          <Route path="customers" element={<CustomersPage />} />
          <Route path="complaints" element={<ComplaintsPage />} />
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
