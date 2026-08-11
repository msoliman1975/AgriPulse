import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";

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
import { FarmDetailPage } from "@/modules/farms/pages/FarmDetailPage";
import { FarmEditPage } from "@/modules/farms/pages/FarmEditPage";
import { FarmMembersPage } from "@/modules/farms/pages/FarmMembersPage";
import { BlockCreatePage } from "@/modules/farms/pages/BlockCreatePage";
import { BlockAutoGridPage } from "@/modules/farms/pages/BlockAutoGridPage";
import { BlockDetailPage } from "@/modules/farms/pages/BlockDetailPage";
import { BlockEditPage } from "@/modules/farms/pages/BlockEditPage";
import { InsightsPage } from "@/modules/insights/pages/InsightsPage";
import { BoardPage } from "@/modules/board/pages/BoardPage";
import { ActionCenterPage } from "@/modules/actionCenter/pages/ActionCenterPage";
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
import { DecisionTreeViewerPage } from "@/modules/decisionTrees/pages/DecisionTreeViewerPage";
import { DecisionTreeTracesPage } from "@/modules/decisionTrees/pages/DecisionTreeTracesPage";
import { MapExperiencePage } from "@/modules/labs/map/MapExperiencePage";
import { FarmConsolePage } from "@/modules/labs/mapnext/FarmConsolePage";
import { PatternsPage } from "@/modules/labs/patterns/PatternsPage";
import { BulkUpdatesPage } from "@/modules/settings/pages/BulkUpdatesPage";
import { SettingsLayout } from "@/modules/settings/pages/SettingsLayout";
import { SettingsIndexPage } from "@/modules/settings/pages/SettingsIndexPage";
import { SettingsPlaceholderPage } from "@/modules/settings/pages/SettingsPlaceholderPage";
import { ResourcesWorkersPage } from "@/modules/settings/pages/ResourcesWorkersPage";
import { ResourcesEquipmentPage } from "@/modules/settings/pages/ResourcesEquipmentPage";
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
import { PlatformCropAttributesPage } from "@/modules/admin/pages/PlatformCropAttributesPage";
import { PlatformCatalogPage } from "@/modules/admin/pages/PlatformCatalogPage";
import { PlatformCropsPage } from "@/modules/admin/pages/PlatformCropsPage";
import { PlatformSignalsPage } from "@/modules/admin/pages/PlatformSignalsPage";
import { PlatformDefaultsPage } from "@/modules/admin/pages/PlatformDefaultsPage";
import { PlatformBackfillPage } from "@/modules/admin/pages/PlatformBackfillPage";
import { ObserverSceneDetailPage } from "@/modules/admin/pages/ObserverSceneDetailPage";
import { PlatformObserverPage } from "@/modules/admin/pages/PlatformObserverPage";
import { PlatformPlanTemplatesPage } from "@/modules/admin/pages/PlatformPlanTemplatesPage";
import { PlanTemplateEditorPage } from "@/modules/admin/pages/PlanTemplateEditorPage";
import { PlatformAdminsPage } from "@/modules/admin/pages/PlatformAdminsPage";
import { PlatformHealthPage } from "@/modules/admin/pages/PlatformHealthPage";
import { PlatformHealthTenantDrillPage } from "@/modules/admin/pages/PlatformHealthTenantDrillPage";
import { queryClient } from "@/queries/client";

function RedirectDecisionTreeDetail(): ReactNode {
  const { code = "" } = useParams<{ farmId: string; code: string }>();
  return <Navigate to={`/decision-trees/${code}`} replace />;
}

// Decision Trees were promoted out of the Settings hub to a top-level
// /decision-trees surface (experience redesign). Old /settings/decision-trees
// deep links (incl. the legacy /view suffix) collapse onto the single
// workspace entry.
function RedirectSettingsDecisionTree(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  return <Navigate to={`/decision-trees/${code}`} replace />;
}

function RedirectLegacyAdminTenant(): ReactNode {
  const { tenantId = "" } = useParams<{ tenantId: string }>();
  return <Navigate to={`/platform/tenants/${tenantId}`} replace />;
}

function RedirectPlanToBoard(): ReactNode {
  const { farmId = "" } = useParams<{ farmId: string }>();
  // Preserve the query string (?activity=&lane=) so deep-links from Alerts and
  // the Insights "Upcoming activities" card keep focusing the right activity
  // after the /plan -> /board cutover redirect.
  const { search } = useLocation();
  return <Navigate to={`/board/${farmId}${search}`} replace />;
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
                back to /auth/callback â€” a redirect loop. */}
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
                  Platform staff don't see the AgriPulse tree at all
                  (persona-separation rule from the portal-restructure). */}
              <Route element={<AgriPulseGuard />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
                <Route path="/farms" element={<FarmListPage />} />
                {/* Farm creation moved into the Farm Console; the old form
                    route redirects so existing links and bookmarks survive. */}
                <Route
                  path="/farms/new"
                  element={<Navigate to="/labs/map?create=farm" replace />}
                />
                <Route path="/farms/:farmId" element={<FarmDetailPage />} />
                <Route path="/farms/:farmId/edit" element={<FarmEditPage />} />
                <Route path="/farms/:farmId/members" element={<FarmMembersPage />} />
                <Route path="/farms/:farmId/blocks/new" element={<BlockCreatePage />} />
                <Route path="/farms/:farmId/blocks/auto-grid" element={<BlockAutoGridPage />} />
                <Route path="/farms/:farmId/blocks/:blockId" element={<BlockDetailPage />} />
                <Route path="/farms/:farmId/blocks/:blockId/edit" element={<BlockEditPage />} />
                {/* AgriPulse new IA â€” farm-scoped routes (UX_SPEC Â§3 +
                  IMPLEMENTATION_PLAN Â§3). */}
                {/* Labs: experimental map-first surface for live validation.
                  Complements the existing list/table flow â€” does not
                  replace it. See docs/proposals/map-first.md. */}
                {/* /labs/map is now the redesigned Farm Console (progressive
                  disclosure). The previous map is kept as Legacy at
                  /labs/map-legacy. /labs/map-next stays as an alias for old
                  links. See docs/proposals/farm-management-redesign.md. */}
                <Route path="/labs/map" element={<FarmConsolePage />} />
                <Route path="/labs/map/:farmId" element={<FarmConsolePage />} />
                <Route path="/labs/map-next" element={<FarmConsolePage />} />
                <Route path="/labs/map-next/:farmId" element={<FarmConsolePage />} />
                <Route path="/labs/map-legacy" element={<MapExperiencePage />} />
                <Route path="/labs/map-legacy/:farmId" element={<MapExperiencePage />} />
                {/* Page-template gallery. Every standard template in every
                  state — the reference for "what does an index page look
                  like" in code review. See
                  docs/proposals/ui-standard-implementation-plan.md. */}
                <Route path="/labs/patterns" element={<PatternsPage />} />
                <Route path="/insights/:farmId" element={<InsightsPage />} />
                {/* Board PR-7 cutover: /plan/:farmId redirects to /board/:farmId.
                  The legacy PlanPage (modules/plan/*) was removed once the
                  farm-scoped Gantt was folded into the board grid; this
                  redirect keeps old deep-links working. */}
                <Route path="/plan/:farmId" element={<RedirectPlanToBoard />} />
                <Route path="/board/:farmId" element={<BoardPage />} />
                {/* The unified queue. /alerts and /recommendations stay routed
                    until this screen is signed off. */}
                <Route path="/action-center/:farmId" element={<ActionCenterPage />} />
                <Route path="/alerts/:farmId" element={<AlertsPage />} />
                <Route path="/recommendations/:farmId" element={<RecommendationsPage />} />
                <Route path="/signals/:farmId" element={<SignalsLogPage />} />
                <Route path="/reports/:farmId" element={<ReportsPage />} />
                <Route path="/config/signals/:farmId" element={<SignalsConfigPage />} />
                {/* Rules + Users are tenant-wide â€” redirect to the Settings hub. */}
                <Route
                  path="/config/rules/:farmId"
                  element={<Navigate to="/settings/rules" replace />}
                />
                <Route path="/config/imagery/:farmId" element={<ImageryWeatherConfigPage />} />
                <Route
                  path="/config/users/:farmId"
                  element={<Navigate to="/settings/users" replace />}
                />
                {/* Legacy /config/decision-trees/:farmId paths redirect to the
                  top-level /decision-trees surface (tenant-wide). */}
                <Route
                  path="/config/decision-trees/:farmId"
                  element={<Navigate to="/decision-trees" replace />}
                />
                <Route
                  path="/config/decision-trees/:farmId/new"
                  element={<Navigate to="/decision-trees/new" replace />}
                />
                {/* /config/decision-trees/:farmId/:code â†’ /decision-trees/:code */}
                <Route
                  path="/config/decision-trees/:farmId/:code"
                  element={<RedirectDecisionTreeDetail />}
                />
                {/* Decision Trees — top-level tenant surface (promoted out of
                  the Settings hub). Single entry per tree: the visual
                  workspace, with an in-page YAML toggle. Capability checks
                  live on each page so deep links with the wrong role 403. */}
                <Route path="/decision-trees" element={<DecisionTreeListPage />} />
                <Route path="/decision-trees/new" element={<DecisionTreeCreatePage />} />
                <Route path="/decision-trees/:code" element={<DecisionTreeViewerPage />} />
                {/* Evaluation traces sit outside /decision-trees/ on purpose:
                  a literal segment there would shadow a tree whose code
                  happened to be "traces", and the API paths match this. */}
                <Route path="/decision-tree-traces" element={<DecisionTreeTracesPage />} />
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
                    <Route index element={<Navigate to="health" replace />} />
                    <Route path="health" element={<IntegrationsHealthPage />} />
                    <Route path="weather" element={<IntegrationsWeatherPage />} />
                    <Route path="imagery" element={<IntegrationsImageryPage />} />
                    {/* email + webhook removed with public migration 0048 —
                        their keys were inert; bounce old links to health. */}
                    <Route path="email" element={<Navigate to="../health" replace />} />
                    <Route path="webhook" element={<Navigate to="../health" replace />} />
                    <Route
                      path="detection"
                      element={
                        <IntegrationsTenantOnlyPage
                          category="detection"
                          i18nTitleKey="detection.title"
                          i18nSubtitleKey="detection.subtitle"
                        />
                      }
                    />
                  </Route>
                  <Route path="users" element={<UsersConfigPage />} />
                  <Route path="bulk" element={<BulkUpdatesPage />} />
                  <Route path="workers" element={<ResourcesWorkersPage />} />
                  <Route path="equipment" element={<ResourcesEquipmentPage />} />
                  <Route path="rules" element={<RulesConfigPage />} />
                  {/* Decision Trees moved to the top-level /decision-trees
                      surface — keep old Settings deep links working. */}
                  <Route
                    path="decision-trees"
                    element={<Navigate to="/decision-trees" replace />}
                  />
                  <Route
                    path="decision-trees/new"
                    element={<Navigate to="/decision-trees/new" replace />}
                  />
                  <Route path="decision-trees/:code" element={<RedirectSettingsDecisionTree />} />
                  <Route
                    path="decision-trees/:code/view"
                    element={<RedirectSettingsDecisionTree />}
                  />
                </Route>
              </Route>
              {/* Platform Management Portal â€” capability gate sits
                  inside PlatformLayout (PR-Reorg2). PlatformAdmin
                  lands here post-login because AgriPulseGuard above
                  redirects them away from /. */}
              <Route path="/platform" element={<PlatformLayout />}>
                <Route index element={<Navigate to="tenants" replace />} />
                <Route path="tenants" element={<AdminTenantListPage />} />
                <Route path="tenants/new" element={<AdminTenantCreatePage />} />
                <Route path="tenants/:tenantId" element={<TenantAdminDetailPage />} />
                <Route path="defaults" element={<PlatformDefaultsPage />} />
                <Route path="crops" element={<PlatformCropsPage />} />
                <Route path="catalog" element={<PlatformCatalogPage />} />
                <Route path="signals" element={<PlatformSignalsPage />} />
                <Route path="crops/:cropId/attributes" element={<PlatformCropAttributesPage />} />
                <Route path="plan-templates" element={<PlatformPlanTemplatesPage />} />
                <Route path="backfill" element={<PlatformBackfillPage />} />
                <Route path="observer" element={<PlatformObserverPage />} />
                <Route path="observer/scenes/:jobId" element={<ObserverSceneDetailPage />} />
                <Route path="plan-templates/new" element={<PlanTemplateEditorPage />} />
                <Route path="plan-templates/:id" element={<PlanTemplateEditorPage />} />
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
              <Route path="/admin/tenants" element={<Navigate to="/platform/tenants" replace />} />
              <Route
                path="/admin/tenants/new"
                element={<Navigate to="/platform/tenants/new" replace />}
              />
              <Route path="/admin/tenants/:tenantId" element={<RedirectLegacyAdminTenant />} />
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
