import { matchRoutes, type RouteObject } from "react-router-dom";

/**
 * Route TEMPLATES for telemetry.
 *
 * `route` in the event stream is always a template — `/insights/:farmId`, never
 * `/insights/8f3a-…`. A resolved path smuggles an id into a text column and
 * makes grouping impossible; the id belongs in the typed `farm_id` column.
 *
 * This app mounts `<BrowserRouter><Routes>`, not a data router, so `useMatches()`
 * is unavailable and the patterns cannot be read back at runtime. Hence a
 * manifest — path-only, no elements, so it costs nothing to keep.
 *
 * It duplicates `App.tsx`, and duplication rots. `routes.test.ts` reads
 * `App.tsx` and asserts the two path sets are equal in both directions, so a
 * new page cannot ship reporting as `unknown` and a deleted one cannot linger.
 */
export const ROUTE_MANIFEST: RouteObject[] = [
  { path: "/login" },
  { path: "/auth/callback" },
  { path: "/" },
  { path: "/tenants/:tenantId" },
  { path: "/farms" },
  { path: "/farms/new" },
  { path: "/farms/:farmId" },
  { path: "/farms/:farmId/edit" },
  { path: "/farms/:farmId/members" },
  { path: "/farms/:farmId/blocks/new" },
  { path: "/farms/:farmId/blocks/auto-grid" },
  { path: "/farms/:farmId/blocks/:blockId" },
  { path: "/farms/:farmId/blocks/:blockId/edit" },
  { path: "/labs/map" },
  { path: "/labs/map/:farmId" },
  { path: "/labs/map-next" },
  { path: "/labs/map-next/:farmId" },
  { path: "/labs/map-legacy" },
  { path: "/labs/map-legacy/:farmId" },
  { path: "/labs/map-v2" },
  { path: "/labs/map-v2/:farmId" },
  { path: "/labs/patterns" },
  { path: "/insights/:farmId" },
  { path: "/plan/:farmId" },
  { path: "/board/:farmId" },
  { path: "/timeline/:farmId" },
  { path: "/farm-health/:farmId" },
  { path: "/action-center/:farmId" },
  { path: "/alerts/:farmId" },
  { path: "/recommendations/:farmId" },
  { path: "/signals/:farmId" },
  { path: "/reports/:farmId" },
  { path: "/config/signals/:farmId" },
  { path: "/config/rules/:farmId" },
  { path: "/config/imagery/:farmId" },
  { path: "/config/users/:farmId" },
  { path: "/config/decision-trees/:farmId" },
  { path: "/config/decision-trees/:farmId/new" },
  { path: "/config/decision-trees/:farmId/:code" },
  { path: "/decision-trees" },
  { path: "/decision-trees/new" },
  { path: "/decision-trees/:code" },
  { path: "/decision-tree-traces" },
  { path: "/account/notifications" },
  {
    path: "/settings",
    children: [
      { path: "org" },
      { path: "notifications" },
      {
        path: "integrations",
        children: [
          { path: "health" },
          { path: "weather" },
          { path: "imagery" },
          { path: "email" },
          { path: "webhook" },
          { path: "detection" },
        ],
      },
      { path: "users" },
      { path: "bulk" },
      { path: "workers" },
      { path: "field-access" },
      { path: "equipment" },
      { path: "rules" },
      { path: "decision-trees" },
      { path: "decision-trees/new" },
      { path: "decision-trees/:code" },
      { path: "decision-trees/:code/view" },
    ],
  },
  {
    path: "/platform",
    children: [
      { path: "tenants" },
      { path: "tenants/new" },
      { path: "tenants/:tenantId" },
      { path: "defaults" },
      { path: "crops" },
      { path: "catalog" },
      { path: "signals" },
      { path: "crops/:cropId/attributes" },
      { path: "plan-templates" },
      { path: "plan-templates/new" },
      { path: "plan-templates/:id" },
      { path: "backfill" },
      { path: "observer" },
      { path: "observer/scenes/:jobId" },
      { path: "admins" },
      { path: "roles" },
      { path: "usage" },
      { path: "integrations/health" },
      { path: "integrations/health/tenants/:tenantId" },
      { path: "alerts" },
    ],
  },
  { path: "/admin" },
  { path: "/admin/tenants" },
  { path: "/admin/tenants/new" },
  { path: "/admin/tenants/:tenantId" },
  { path: "/admin/defaults" },
  { path: "*" },
];

export interface RouteMatchInfo {
  /** Route TEMPLATE, or "unknown" when nothing in the manifest matched. */
  template: string;
  /** The `:farmId` param, when the matched route has one. */
  farmId?: string;
}

/**
 * Resolve a pathname to its template and its farm id in one pass.
 *
 * Both come from the same `matchRoutes` call on purpose. The obvious
 * alternative — `useParams()` in the shell — returns an EMPTY object, because
 * the shell is an ancestor layout route and React Router only hands a
 * component the params of routes at or above it. Reading params there would
 * have compiled, run, and recorded `farm_id: undefined` on every event.
 */
export function matchRouteInfo(pathname: string): RouteMatchInfo {
  let matches: ReturnType<typeof matchRoutes> = null;
  try {
    matches = matchRoutes(ROUTE_MANIFEST, pathname);
  } catch {
    // A malformed pathname must not take the page down for a telemetry call.
    return { template: "unknown" };
  }
  if (matches === null || matches.length === 0) return { template: "unknown" };

  const joined = matches
    .map((m) => (m.route as RouteObject).path ?? "")
    .filter((p) => p !== "")
    .join("/")
    .replace(/\/{2,}/g, "/");
  const trimmed = joined.length > 1 && joined.endsWith("/") ? joined.slice(0, -1) : joined;
  const template = trimmed === "" || trimmed === "*" ? "unknown" : trimmed;

  const farmId = matches[matches.length - 1]?.params?.farmId;
  return { template, farmId: farmId || undefined };
}

/** The template for a resolved pathname, or "unknown" if nothing matches. */
export function routeTemplate(pathname: string): string {
  return matchRouteInfo(pathname).template;
}
