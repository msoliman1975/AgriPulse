/**
 * Phone + PIN sign-in against the `agripulse-mobile` Keycloak client.
 *
 * Direct grant rather than a browser redirect: the credential is a phone
 * number and a six-digit PIN typed on a number pad. Sending this persona out
 * to a Custom Tab to fill a web form is slower, harder to read in sunlight,
 * and for a low-literacy user meaningfully worse.
 *
 * `offline_access` is requested so the refresh token survives a scout being
 * out of signal for weeks. Storage here is `localStorage` for the browser
 * build; the Capacitor build swaps in `@capacitor/preferences`, which is
 * backed by the Android Keystore — see `storage` below.
 */

const ISSUER = import.meta.env.VITE_KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/agripulse";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "agripulse-mobile";

const TOKEN_URL = `${ISSUER}/protocol/openid-connect/token`;
const STORAGE_KEY = "agripulse.scout.session";

export interface Session {
  accessToken: string;
  refreshToken: string;
  /** Epoch ms. Refresh slightly early rather than on a 401 — a scout in a
   *  field should not pay a failed round trip to discover an expiry. */
  expiresAt: number;
}

export class SignInError extends Error {}

/** Swap-point for Capacitor Preferences on device. */
const storage = {
  read(): Session | null {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  },
  write(session: Session | null): void {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  },
};

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
  storage.write(session);
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
    storage.write(null);
    return null;
  }
  const next = toSession(await resp.json());
  storage.write(next);
  return next;
}

export function currentSession(): Session | null {
  return storage.read();
}

export function signOut(): void {
  storage.write(null);
}

/** A valid access token, refreshing 30s before expiry. Null = signed out. */
export async function validAccessToken(): Promise<string | null> {
  const session = currentSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt - 30_000) return session.accessToken;
  const next = await refresh(session);
  return next?.accessToken ?? null;
}
