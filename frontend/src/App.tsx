import { Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/layout/AppShell';
import { Dashboard } from '@/pages/Dashboard';
import { DataPage } from '@/pages/DataPage';
import { LogsPage } from '@/pages/LogsPage';
import { ModelsPage } from '@/pages/ModelsPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { SignalsPage } from '@/pages/SignalsPage';
import { SystemPage } from '@/pages/SystemPage';
import { PENDING_PAGES, PendingPage, type PendingPageKey } from '@/pages/pending';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="signals" element={<SignalsPage />} />
        <Route path="models" element={<ModelsPage />} />
        {(Object.keys(PENDING_PAGES) as PendingPageKey[]).map((name) => (
          <Route key={name} path={name} element={<PendingPage name={name} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
