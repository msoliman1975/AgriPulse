import { beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();
const secure = {
  getItem: vi.fn(async (key: string) => store.get(key) ?? null),
  setItem: vi.fn(async (key: string, value: string) => void store.set(key, value)),
  removeItem: vi.fn(async (key: string) => void store.delete(key)),
};
vi.mock("@aparajita/capacitor-secure-storage", () => ({ SecureStorage: secure }));

const KEY = "agripulse.scout.session";
const SESSION = { accessToken: "a.b.c", refreshToken: "refresh-1", expiresAt: 4_000_000_000_000 };

/** A fresh module per test: the cached session is module state. */
async function load() {
  vi.resetModules();
  return import("./session");
}

beforeEach(() => {
  store.clear();
  vi.clearAllMocks();
  const local = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => local.get(k) ?? null,
    setItem: (k: string, v: string) => void local.set(k, v),
    removeItem: (k: string) => void local.delete(k),
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
});

describe("restoreSession", () => {
  it("moves a session out of localStorage, so an upgrade signs nobody out", async () => {
    localStorage.setItem(KEY, JSON.stringify(SESSION));
    const session = await load();

    await session.restoreSession();

    expect(session.currentSession()).toEqual(SESSION);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(store.get(KEY)).toBe(JSON.stringify(SESSION));
  });

  it("reads the Keystore copy when there is one", async () => {
    store.set(KEY, JSON.stringify(SESSION));
    const session = await load();

    await session.restoreSession();

    expect(session.currentSession()).toEqual(SESSION);
  });

  it("prefers the Keystore, and still deletes a stale localStorage copy", async () => {
    store.set(KEY, JSON.stringify(SESSION));
    localStorage.setItem(KEY, JSON.stringify({ ...SESSION, refreshToken: "old" }));
    const session = await load();

    await session.restoreSession();

    expect(session.currentSession()?.refreshToken).toBe("refresh-1");
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("treats an unreadable Keystore as signed out", async () => {
    secure.getItem.mockRejectedValueOnce(new Error("key invalidated"));
    const session = await load();

    await session.restoreSession();

    expect(session.currentSession()).toBeNull();
  });

  it("survives a corrupt stored session", async () => {
    store.set(KEY, "{not json");
    const session = await load();

    await session.restoreSession();

    expect(session.currentSession()).toBeNull();
  });
});

describe("signOut", () => {
  it("clears the phone and ends the session at Keycloak", async () => {
    store.set(KEY, JSON.stringify(SESSION));
    const session = await load();
    await session.restoreSession();

    await session.signOut();

    expect(session.currentSession()).toBeNull();
    expect(store.has(KEY)).toBe(false);
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/protocol\/openid-connect\/logout$/);
    expect(String(init.body)).toContain("refresh_token=refresh-1");
  });

  it("still signs out with no signal", async () => {
    store.set(KEY, JSON.stringify(SESSION));
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("offline"));
    const session = await load();
    await session.restoreSession();

    await expect(session.signOut()).resolves.toBeUndefined();

    expect(session.currentSession()).toBeNull();
    expect(store.has(KEY)).toBe(false);
  });
});

describe("sessionPhone", () => {
  it("reads the phone from the token", async () => {
    const payload = btoa(JSON.stringify({ preferred_username: "+201001234567" }));
    store.set(KEY, JSON.stringify({ ...SESSION, accessToken: `h.${payload}.s` }));
    const session = await load();
    await session.restoreSession();

    expect(session.sessionPhone()).toBe("+201001234567");
  });

  it("is null for a token it cannot read", async () => {
    store.set(KEY, JSON.stringify(SESSION));
    const session = await load();
    await session.restoreSession();

    expect(session.sessionPhone()).toBeNull();
  });
});
