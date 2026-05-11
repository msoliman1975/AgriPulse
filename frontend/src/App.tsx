import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";

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
import { RecommendationsPage } from "@/modules/recommendations/pages/RecommendationsPage";
import { ReportsPage } from "@/modules/reports/pages/ReportsPage";
import { SignalsConfigPage } from "@/modules/signals/pages/SignalsConfigPage";
import { SignalsLogPage } from "@/modules/signals/pages/SignalsLogPage";
import { RulesConfigPage } from "@/modules/config/pages/RulesConfigPage";
import { ImageryWeatherConfigPage } from "@/modules/config/pages/ImageryWeatherConfigPage";
import { UsersConfigPage } from "@/modules/config/pages/UsersConfigPage";
import { DecisionTreeListPage } from "@/modules/decisionTrees/pages/DecisionTreeListPage";
import { DecisionTreeCreatePage } from "@/modules/decisionTrees/pages/DecisionTreeCreatePage";
import { DecisionTreeEditorPage } from "@/modules/decisionTrees/pages/DecisionTreeEditorPage";
import { MapExperiencePage } from "@/modules/labs/map/MapExperiencePage";
import { SettingsLayout } from "@/modules/settings/pages/SettingsLayout";
import { SettingsIndexPage } from "@/modules/settings/pages/SettingsIndexPage";
import { SettingsPlaceholderPage } from "@/modules/settings/pages/SettingsPlaceholderPage";
import { IntegrationsLayout } from "@/modules/settings/pages/IntegrationsLayout";
import { IntegrationsHealthPage } from "@/modules/settings/pages/IntegrationsHealthPage";
import { IntegrationsWeatherPage } from "@/modules/settings/pages/IntegrationsWeatherPage";
import { IntegrationsImageryPage } from "@/modules/settings/pages/IntegrationsImageryPage";
import { IntegrationsTenantOnlyPage } from "@/modules/settings/pages/IntegrationsTenantOnlyPage";
import { AgriPulseGuard } from "@/auth/AgriPulseGuard";
import { PlatformLayout } from "@/modules/admin/pages/PlatformLayout";
import { TenantListPage as AdminTenantListPage } from "@/modules/admin/pages/TenantListPage";
import { TenantCreatePage as AdminTenantCreatePage } from "@/modules/admin/pages/TenantCreatePage";
import { TenantAdminDetailPage } from "@/modules/admin/pages/TenantAdminDetailPage";
import { PlatformDefaultsPage } from "@/modules/admin/pages/PlatformDefaultsPage";
import { PlatformAdminsPage } from "@/modules/admin/pages/PlatformAdminsPage";
import { PlatformHealthPage } from "@/modules/admin/pages/PlatformHealthPage";
import { PlatformHealthTenantDrillPage } from "@/modules/admin/pages/PlatformHealthTenantDrillPage";
import { queryClient } from "@/queries/client";

function RedirectDecisionTreeDetail(): ReactNode {
  const { code = "" } = useParams<{ farmId: string; code: string }>();
  return <Navigate to={`/settings/decision-trees/${code}`} replace />;
}

function RedirectLegacyAdminTenant(): ReactNode {
  const { tenantId = "" } = useParams<{ tenantId: string }>();
  return <Navigate to={`/platform/tenants/${tenantId}`} replace />;
}

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
              {/* AgriPulseGuard bounces PlatformAdmin to /platform so
                  Platform staff don't see the Agri.Pulse tree at all
                  (persona-separation rule from the portal-restructure). */}
              <Route element={<AgriPulseGuard />}>
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
              {/* Labs: experimental map-first surface for live validation.
                  Complements the existing list/table flow — does not
                  replace it. See docs/proposals/map-first.md. */}
              <Route path="/labs/map/:farmId" element={<MapExperiencePage />} />
              <Route path="/insights/:farmId" element={<InsightsPage />} />
              <Route path="/plan/:farmId" element={<PlanPage />} />
              <Route path="/alerts/:farmId" element={<AlertsPage />} />
              <Route path="/recommendations/:farmId" element={<RecommendationsPage />} />
              <Route path="/signals/:farmId" element={<SignalsLogPage />} />
              <Route path="/reports/:farmId" element={<ReportsPage />} />
              <Route path="/config/signals/:farmId" element={<SignalsConfigPage />} />
              {/* Rules + Users are tenant-wide — redirect to the Settings hub. */}
              <Route
                path="/config/rules/:farmId"
                element={<Navigate to="/settings/rules" replace />}
              />
              <Route path="/config/imagery/:farmId" element={<ImageryWeatherConfigPage />} />
              <Route
                path="/config/users/:farmId"
                element={<Navigate to="/settings/users" replace />}
              />
              {/* Legacy /config/decision-trees/:farmId paths redirect to
                  /settings/decision-trees (settings are tenant-wide). */}
              <Route
                path="/config/decision-trees/:farmId"
                element={<Navigate to="/settings/decision-trees" replace />}
              />
              <Route
                path="/config/decision-trees/:farmId/new"
                element={<Navigate to="/settings/decision-trees/new" replace />}
              />
              {/* /config/decision-trees/:farmId/:code → /settings/decision-trees/:code */}
              <Route
                path="/config/decision-trees/:farmId/:code"
                element={<RedirectDecisionTreeDetail />}
              />
              {/* Tenant Settings Hub. Capability checks live on each
                  page so a deep link with the wrong role still 403s. */}
              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<SettingsIndexPage />} />
                <Route
                  path="org"
                  element={
                    <SettingsPlaceholderPage
                      i18nKey="org"
                      requires="tenant.manage_integrations"
                    />
                  }
                />
                <Route
                  path="notifications"
                  element={
                    <SettingsPlaceholderPage
                      i18nKey="notifications"
                      requires="tenant.manage_integrations"
                    />
                  }
                />
                <Route path="integrations" element={<IntegrationsLayout />}>
                  <Route
                    index
                    element={<Navigate to="health" replace />}
                  />
                  <Route path="health" element={<IntegrationsHealthPage />} />
                  <Route path="weather" element={<IntegrationsWeatherPage />} />
                  <Route path="imagery" element={<IntegrationsImageryPage />} />
                  <Route
                    path="email"
                    element={
                      <IntegrationsTenantOnlyPage
                        category="email"
                        i18nTitleKey="email.title"
                        i18nSubtitleKey="email.subtitle"
                      />
                    }
                  />
                  <Route
                    path="webhook"
                    element={
                      <IntegrationsTenantOnlyPage
                        category="webhook"
                        i18nTitleKey="webhook.title"
                        i18nSubtitleKey="webhook.subtitle"
                      />
                    }
                  />
                </Route>
                <Route path="users" element={<UsersConfigPage />} />
                <Route path="rules" element={<RulesConfigPage />} />
                <Route path="decision-trees" element={<DecisionTreeListPage />} />
                <Route
                  path="decision-trees/new"
                  element={<DecisionTreeCreatePage />}
                />
                <Route
                  path="decision-trees/:code"
                  element={<DecisionTreeEditorPage />}
                />
              </Route>
              </Route>
              {/* Platform Management Portal — capability gate sits
                  inside PlatformLayout (PR-Reorg2). PlatformAdmin
                  lands here post-login because AgriPulseGuard above
                  redirects them away from /. */}
              <Route path="/platform" element={<PlatformLayout />}>
                <Route index element={<Navigate to="tenants" replace />} />
                <Route path="tenants" element={<AdminTenantListPage />} />
                <Route path="tenants/new" element={<AdminTenantCreatePage />} />
                <Route path="tenants/:tenantId" element={<TenantAdminDetailPage />} />
                <Route path="defaults" element={<PlatformDefaultsPage />} />
                <Route path="admins" element={<PlatformAdminsPage />} />
                <Route path="integrations/health" element={<PlatformHealthPage />} />
                <Route
                  path="integrations/health/tenants/:tenantId"
                  element={<PlatformHealthTenantDrillPage />}
                />
              </Route>
              {/* Back-compat: old /admin/* paths redirect to /platform/*
                  so bookmarks keep working through the URL rename. */}
              <Route path="/admin" element={<Navigate to="/platform" replace />} />
              <Route
                path="/admin/tenants"
                element={<Navigate to="/platform/tenants" replace />}
              />
              <Route
                path="/admin/tenants/new"
                element={<Navigate to="/platform/tenants/new" replace />}
              />
              <Route
                path="/admin/tenants/:tenantId"
                element={<RedirectLegacyAdminTenant />}
              />
              <Route
                path="/admin/defaults"
                element={<Navigate to="/platform/defaults" replace />}
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PrefsProvider>
    </AuthProvider>
  );
}
