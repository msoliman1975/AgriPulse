import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthCallback } from "@/auth/AuthCallback";
import { AuthProvider } from "@/auth/AuthProvider";
import { AuthSync } from "@/auth/AuthSync";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { ConfigProvider } from "@/config/ConfigContext";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { AppShell } from "@/shell/AppShell";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { TenantDetailPage } from "@/pages/TenantDetailPage";
import { FarmListPage } from "@/modules/farms/pages/FarmListPage";
import { FarmCreatePage } from "@/modules/farms/pages/FarmCreatePage";
import { FarmDetailPage } from "@/modules/farms/pages/FarmDetailPage";
import { FarmEditPage } from "@/modules/farms/pages/FarmEditPage";
import { FarmMembersPage } from "@/modules/farms/pages/FarmMembersPage";
import { BlockCreatePage } from "@/modules/farms/pages/BlockCreatePage";
import { BlockAutoGridPage } from "@/modules/farms/pages/BlockAutoGridPage";
import { BlockDetailPage } from "@/modules/farms/pages/BlockDetailPage";
import { BlockEditPage } from "@/modules/farms/pages/BlockEditPage";
import { InsightsPage } from "@/modules/insights/pages/InsightsPage";
import { PlanPage } from "@/modules/plan/pages/PlanPage";
import { AlertsPage } from "@/modules/alerts/pages/AlertsPage";
import { ReportsPage } from "@/modules/reports/pages/ReportsPage";
import { RulesConfigPage } from "@/modules/config/pages/RulesConfigPage";
import { ImageryWeatherConfigPage } from "@/modules/config/pages/ImageryWeatherConfigPage";
import { UsersConfigPage } from "@/modules/config/pages/UsersConfigPage";
import { queryClient } from "@/queries/client";

export function App(): ReactNode {
  return (
    <AuthProvider>
      <AuthSync />
      <PrefsProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* /auth/callback MUST live outside ProtectedRoute. The
                user lands here unauthenticated (with `?code=...` in
                the URL); react-oidc-context exchanges the code for
                tokens asynchronously. If ProtectedRoute saw the
                unauth-yet state and bounced to /login, /login would
                signinRedirect to Keycloak, Keycloak would round-trip
                back to /auth/callback — a redirect loop. */}
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route
              element={
                <ProtectedRoute>
                  {/* ConfigProvider is mounted INSIDE ProtectedRoute so
                      `getConfig()` doesn't fire on the first commit (when
                      auth.user is still null on hard refresh). That race
                      surfaced as 401 "Missing bearer token" on the very
                      first /api/v1/config call.
                      QueryClientProvider lives here too so the cache is
                      shared across every farm-scoped page. */}
                  <ConfigProvider>
                    <QueryClientProvider client={queryClient}>
                      <AppShell />
                    </QueryClientProvider>
                  </ConfigProvider>
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<HomePage />} />
              <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
              <Route path="/farms" element={<FarmListPage />} />
              <Route path="/farms/new" element={<FarmCreatePage />} />
              <Route path="/farms/:farmId" element={<FarmDetailPage />} />
              <Route path="/farms/:farmId/edit" element={<FarmEditPage />} />
              <Route path="/farms/:farmId/members" element={<FarmMembersPage />} />
              <Route path="/farms/:farmId/blocks/new" element={<BlockCreatePage />} />
              <Route path="/farms/:farmId/blocks/auto-grid" element={<BlockAutoGridPage />} />
              <Route path="/farms/:farmId/blocks/:blockId" element={<BlockDetailPage />} />
              <Route path="/farms/:farmId/blocks/:blockId/edit" element={<BlockEditPage />} />
              {/* AgriPulse new IA — farm-scoped routes (UX_SPEC §3 +
                  IMPLEMENTATION_PLAN §3). */}
              <Route path="/insights/:farmId" element={<InsightsPage />} />
              <Route path="/plan/:farmId" element={<PlanPage />} />
              <Route path="/alerts/:farmId" element={<AlertsPage />} />
              <Route path="/reports/:farmId" element={<ReportsPage />} />
              <Route path="/config/rules/:farmId" element={<RulesConfigPage />} />
              <Route path="/config/imagery/:farmId" element={<ImageryWeatherConfigPage />} />
              <Route path="/config/users/:farmId" element={<UsersConfigPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PrefsProvider>
    </AuthProvider>
  );
}
