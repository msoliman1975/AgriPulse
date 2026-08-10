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
 * `/health` is one of the few unauthenticated paths (`_PUBLIC_PATHS` in the
 * auth middleware). `/healthz` is NOT — it sits behind the 401-on-every-path
 * middleware, so probing it reports a healthy server as unreachable.
 *
 * Derived from the API base rather than configured separately: two settings
 * that must agree is one more thing to get wrong per environment.
 */
function healthUrl(): string {
  const base = API_BASE.replace(/\/+$/, "");
  // "http://host:8000/api/v1" -> "http://host:8000/health"; a relative
  // "/api/v1" (the dev proxy) -> "/health".
  return `${base.replace(/\/api\/v\d+$/, "")}/health`;
}

async function reachable(url: string): Promise<boolean> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    // 2xx, not merely "something answered". Both probes hit endpoints that are
    // public and expected to return 200, so anything else means the host is
    // there but the service behind it is not the one we want — an ingress
    // serving a SPA or a 404 where the API should be. Treating that as
    // reachable is how a green dot ends up next to an app that cannot work:
    // https://api.agripulse.cloud/health currently answers 404, and the old
    // "any reply counts" rule would have called that connected.
    const resp = await fetch(url, { method: "GET", signal: abort.signal, cache: "no-store" });
    if (!resp.ok) {
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
    reachable(healthUrl()),
    // The discovery document is public and CORS-open, and it is the exact
    // origin the token request will use.
    reachable(`${ISSUER.replace(/\/+$/, "")}/.well-known/openid-configuration`),
  ]);
  return { api, auth };
}
