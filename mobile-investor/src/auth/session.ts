/**
 * Investor sign-in: Keycloak's own login page in the system browser, with
 * PKCE, as the design asks (email and password, forgot-password for free).
 *
 * The return trip: Keycloak redirects to VITE_KEYCLOAK_REDIRECT_URI, a page
 * on the web app that hands `code` and `state` to this app through the
 * `cloud.agripulse.investor://callback` link. The code is useless without the
 * verifier, which never leaves this install.
 *
 * Token calls go through CapacitorHttp, the native HTTP stack: the web client
 * does not list this app's origin for CORS at Keycloak's token endpoint.
 *
 * `offline_access` keeps the investor signed in for weeks: they sign in once.
 */
import { Browser } from "@capacitor/browser";
import { CapacitorHttp } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

import { challengeFor, jwtClaims, randomString } from "./pkce";

const ISSUER = import.meta.env.VITE_KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/agripulse";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "agripulse-api";
const REDIRECT_URI =
  import.meta.env.VITE_KEYCLOAK_REDIRECT_URI ?? "http://localhost:5173/investor-app/callback";

export const APP_LINK_PREFIX = "cloud.agripulse.investor://callback";

const SESSION_KEY = "agripulse.investor.session";
const PENDING_KEY = "agripulse.investor.pending";

export interface Session {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms. */
  expiresAt: number;
}

interface Pending {
  verifier: string;
  state: string;
}

export class SignInError extends Error {}

let cached: Session | null = null;

async function write(session: Session | null): Promise<void> {
  cached = session;
  if (session) await Preferences.set({ key: SESSION_KEY, value: JSON.stringify(session) });
  else await Preferences.remove({ key: SESSION_KEY });
}

/** Read the stored session once at start; later calls use the cache. */
export async function loadSession(): Promise<Session | null> {
  const { value } = await Preferences.get({ key: SESSION_KEY });
  cached = value ? (JSON.parse(value) as Session) : null;
  return cached;
}

export function currentSession(): Session | null {
  return cached;
}

/** Claims the app reads for display and the role check. */
export function sessionClaims(): { role: string | null; name: string | null; email: string | null } {
  if (!cached) return { role: null, name: null, email: null };
  const c = jwtClaims(cached.accessToken);
  return {
    role: typeof c.tenant_role === "string" ? c.tenant_role : null,
    name: typeof c.name === "string" ? c.name : null,
    email: typeof c.email === "string" ? c.email : null,
  };
}

function toSession(payload: Record<string, unknown>): Session {
  return {
    accessToken: String(payload.access_token),
    refreshToken: String(payload.refresh_token),
    expiresAt: Date.now() + Number(payload.expires_in ?? 300) * 1000,
  };
}

async function postForm(path: string, form: Record<string, string>) {
  return CapacitorHttp.request({
    method: "POST",
    url: `${ISSUER}/protocol/openid-connect/${path}`,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    data: new URLSearchParams(form).toString(),
  });
}

/** Open Keycloak's login page. The app link brings the result back. */
export async function startSignIn(lang: string): Promise<void> {
  const pending: Pending = { verifier: randomString(48), state: randomString(16) };
  await Preferences.set({ key: PENDING_KEY, value: JSON.stringify(pending) });
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: "code",
    scope: "openid profile email offline_access",
    state: pending.state,
    code_challenge: await challengeFor(pending.verifier),
    code_challenge_method: "S256",
    ui_locales: lang,
  });
  await Browser.open({ url: `${ISSUER}/protocol/openid-connect/auth?${params.toString()}` });
}

/** Finish sign-in from the app link. Throws SignInError when it cannot. */
export async function completeSignIn(link: string): Promise<Session> {
  const query = new URL(link.replace(APP_LINK_PREFIX, "https://callback.invalid/")).searchParams;
  const { value } = await Preferences.get({ key: PENDING_KEY });
  await Preferences.remove({ key: PENDING_KEY });
  const pending = value ? (JSON.parse(value) as Pending) : null;
  const code = query.get("code");
  if (!pending || !code || query.get("state") !== pending.state) {
    throw new SignInError(query.get("error") ?? "state");
  }
  const resp = await postForm("token", {
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: pending.verifier,
  });
  if (resp.status !== 200) throw new SignInError(`token ${resp.status}`);
  const session = toSession(resp.data as Record<string, unknown>);
  await write(session);
  return session;
}

async function refresh(session: Session): Promise<Session | null> {
  const resp = await postForm("token", {
    grant_type: "refresh_token",
    client_id: CLIENT_ID,
    refresh_token: session.refreshToken,
  });
  if (resp.status === 400 || resp.status === 401) {
    // Revoked or expired for good: sign out rather than retry for ever.
    await write(null);
    return null;
  }
  if (resp.status !== 200) throw new Error(`refresh ${resp.status}`);
  const next = toSession(resp.data as Record<string, unknown>);
  await write(next);
  return next;
}

/** A valid access token, refreshed 30 s early. Null means signed out. */
export async function validAccessToken(): Promise<string | null> {
  const session = cached;
  if (!session) return null;
  if (Date.now() < session.expiresAt - 30_000) return session.accessToken;
  const next = await refresh(session);
  return next?.accessToken ?? null;
}

/** End the Keycloak session too, so the offline token stops working. */
export async function signOut(): Promise<void> {
  const session = cached;
  await write(null);
  if (session) {
    await postForm("logout", { client_id: CLIENT_ID, refresh_token: session.refreshToken }).catch(
      () => undefined,
    );
  }
}
