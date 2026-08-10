/**
 * Is the backend actually there?
 *
 * Shown on the sign-in screen, before anyone has typed anything, because from
 * that screen "wrong PIN", "the API is down", "the emulator has no route to the
 * host" and "you built against the wrong environment" all look identical: one
 * red line under the button. On a handset installed from a file, with no
 * devtools attached, that ambiguity is expensive.
 *
 * Two services are probed because sign-in needs both and they fail separately:
 * Keycloak issues the token, the API answers with it. Reporting "no connection"
 * when only one is down would send someone debugging the wrong box.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const ISSUER = import.meta.env.VITE_KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/agripulse";

const TIMEOUT_MS = 4000;

export interface Reachability {
  api: boolean;
  auth: boolean;
}

/**
 * Probed under the API base, not at `/health`.
 *
 * `/health` is unauthenticated and works locally, but production's ingress
 * routes only `/api/*` to the API — `https://api.agripulse.cloud/health` is a
 * 404 from the ingress, so a build pointed at prod would report a perfectly
 * healthy API as unreachable.
 *
 * `/me` exists in every environment and needs no token to prove the point: an
 * unauthenticated call returns 401 from the auth middleware, and a 401 is the
 * API answering. What we are ruling out is 404 (nothing routed there — wrong
 * host, wrong base path, API not deployed) and 5xx.
 */
function apiProbeUrl(): string {
  return `${API_BASE.replace(/\/+$/, "")}/me`;
}

/** Statuses that prove the API itself replied. */
const API_ALIVE = new Set([200, 401, 403]);

async function reachable(url: string, accept: (status: number) => boolean): Promise<boolean> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    // Not "anything answered" — an ingress serving a SPA or a 404 where the API
    // should be would pass that, and a green dot next to an app that cannot
    // work is worse than no dot. Each probe says which statuses prove *its*
    // service replied.
    const resp = await fetch(url, { method: "GET", signal: abort.signal, cache: "no-store" });
    if (!accept(resp.status)) {
      console.warn(`health: ${url} answered ${resp.status}`);
      return false;
    }
    return true;
  } catch (err) {
    // Logged, not swallowed. "Cannot reach the server" is the right thing to
    // show a scout, but whoever is debugging the build needs to know whether it
    // was DNS, a refused connection, a CORS rejection or a timeout — and those
    // are indistinguishable from the pill alone.
    console.warn(`health: ${url} unreachable`, err);
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function checkReachability(): Promise<Reachability> {
  const [api, auth] = await Promise.all([
    reachable(apiProbeUrl(), (s) => API_ALIVE.has(s)),
    // The discovery document is public and CORS-open, and it is the exact
    // origin the token request will use. A 200 is the only acceptable answer:
    // anything else means this is not a realm.
    reachable(`${ISSUER.replace(/\/+$/, "")}/.well-known/openid-configuration`, (s) => s === 200),
  ]);
  return { api, auth };
}
