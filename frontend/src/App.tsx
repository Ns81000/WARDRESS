import { Navigate, Route, Routes } from "react-router"

import { AppShell } from "@/components/app-shell"
import { Toaster } from "@/components/ui/sonner"
import { useAuth } from "@/lib/auth"
import { AlertsPage } from "@/pages/alerts"
import { AuditPage } from "@/pages/audit"
import { HealthPage } from "@/pages/health"
import { LoginPage } from "@/pages/login"
import { RemediationPage } from "@/pages/remediation"
import { ScanDetailPage } from "@/pages/scan-detail"
import { SettingsPage } from "@/pages/settings"
import { SiteDetailPage } from "@/pages/site-detail"
import { SitesPage } from "@/pages/sites"

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <p className="text-body-sm text-mute">Loading…</p>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  // Client-side gate is UX only — the API enforces the role server-side.
  if (user?.role !== "admin") return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<SitesPage />} />
          <Route path="/sites/:siteId" element={<SiteDetailPage />} />
          <Route path="/sites/:siteId/scans/:scanId" element={<ScanDetailPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/remediation" element={<RemediationPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route
            path="/audit"
            element={
              <RequireAdmin>
                <AuditPage />
              </RequireAdmin>
            }
          />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </>
  )
}
