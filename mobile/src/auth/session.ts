/**
 * Phone + PIN sign-in against the `agripulse-mobile` Keycloak client.
 *
 * Direct grant rather than a browser redirect: the credential is a phone
 * number and a six-digit PIN typed on a number pad. Sending this persona out
 * to a Custom Tab to fill a web form is slower, harder to read in sunlight,
 * and for a low-literacy user meaningfully worse.
 *
 * `offline_access` is requested so the refresh token survives a scout being
 * out of signal for weeks. That token is the sign-in for up to 90 days, so it
 * lives in the Android Keystore, not in the WebView's `localStorage`. See
 * `storage` below and ADR 0003.
 */

import { SecureStorage } from "@aparajita/capacitor-secure-storage";

const ISSUER = import.meta.env.VITE_KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/agripulse";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "agripulse-mobile";

const TOKEN_URL = `${ISSUER}/protocol/openid-connect/token`;
const LOGOUT_URL = `${ISSUER}/protocol/openid-connect/logout`;
const STORAGE_KEY = "agripulse.scout.session";

export interface Session {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms. Refresh slightly early rather than on a 401 — a scout in a
   *  field should not pay a failed round trip to discover an expiry. */
  expiresAt: number;
}

export class SignInError extends Error {}

/**
 * The Keystore is asynchronous and React's first render is not, so the session
 * is read once at start-up by `restoreSession` and held here. Everything after
 * that reads this copy and writes through to the Keystore.
 */
let cached: Session | null = null;

const storage = {
  read(): Session | null {
    return cached;
  },
  async write(session: Session | null): Promise<void> {
    cached = session;
    try {
      if (session) await SecureStorage.setItem(STORAGE_KEY, JSON.stringify(session));
      else await SecureStorage.removeItem(STORAGE_KEY);
    } catch {
      // Worst case the scout signs in again next launch. Falling back to
      // plain storage would quietly undo the point of this.
    }
  },
};

function parseSession(raw: string | null): Session | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

/**
 * Load the session. Call once, before the first render.
 *
 * Earlier builds kept it in `localStorage`, so this moves that copy across and
 * deletes it. Nobody already in the field is signed out by the upgrade, and no
 * token is left behind in the old place.
 *
 * A Keystore that cannot be read, which happens after some device restores,
 * simply means signed out.
 */
export async function restoreSession(): Promise<void> {
  try {
    cached = parseSession(await SecureStorage.getItem(STORAGE_KEY));
  } catch {
    cached = null;
  }
  const legacy = localStorage.getItem(STORAGE_KEY);
  if (legacy === null) return;
  localStorage.removeItem(STORAGE_KEY);
  const moved = parseSession(legacy);
  if (!cached && moved) await storage.write(moved);
}

function toSession(payload: Record<string, unknown>): Session {
  return {
    accessToken: String(payload.access_token),
    refreshToken: String(payload.refresh_token),
    expiresAt: Date.now() + Number(payload.expires_in ?? 300) * 1000,
  };
}

export async function signIn(phone: string, pin: string): Promise<Session> {
  const body = new URLSearchParams({
    grant_type: "password",
    client_id: CLIENT_ID,
    username: phone,
    password: pin,
    scope: "openid profile email offline_access",
  });
  const resp = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) {
    // Keycloak says "invalid_grant" for both a wrong PIN and an unknown
    // number. Not distinguishing them is deliberate — it avoids confirming
    // which phone numbers are enrolled.
    throw new SignInError("signIn.invalidCredentials");
  }
  const session = toSession(await resp.json());
  await storage.write(session);
  return session;
}

export async function refresh(session: Session): Promise<Session | null> {
  const resp = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: CLIENT_ID,
      refresh_token: session.refreshToken,
    }),
  });
  if (!resp.ok) {
    // The offline token was revoked (offboarding) or finally expired. Sign the
    // scout out rather than looping — a device whose access was withdrawn must
    // stop working, not retry forever.
    await storage.write(null);
    return null;
  }
  const next = toSession(await resp.json());
  await storage.write(next);
  return next;
}

export function currentSession(): Session | null {
  return storage.read();
}

/**
 * Forget the session here and end it at Keycloak.
 *
 * Clearing the phone alone left the offline token valid on the server, so a
 * copy taken from the handset kept working after "sign out". Best effort: with
 * no signal the server cannot be told, and the scout must still get out.
 */
export async function signOut(): Promise<void> {
  const session = cached;
  await storage.write(null);
  if (!session) return;
  try {
    await fetch(LOGOUT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: CLIENT_ID, refresh_token: session.refreshToken }),
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    // Offline. The phone has already forgotten it.
  }
}

/** The phone this session belongs to: Keycloak's username is the phone. */
export function sessionPhone(): string | null {
  const payload = cached?.accessToken.split(".")[1];
  if (!payload) return null;
  try {
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return (JSON.parse(json) as { preferred_username?: string }).preferred_username ?? null;
  } catch {
    return null;
  }
}

/** A valid access token, refreshing 30s before expiry. Null = signed out. */
export async function validAccessToken(): Promise<string | null> {
  const session = currentSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt - 30_000) return session.accessToken;
  const next = await refresh(session);
  return next?.accessToken ?? null;
}
