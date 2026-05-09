import { test as base, expect, type Page } from "@playwright/test";

/**
 * Shared e2e fixtures.
 *
 * `authedPage` returns a Page whose sessionStorage is pre-seeded with a
 * valid-looking OIDC user record (matching the key + shape that
 * react-oidc-context expects) AND whose API calls are intercepted so
 * the test does not need a real backend.
 *
 * Key + shape come from `oidc-client-ts`'s WebStorageStateStore +
 * UserManager. The key format is:
 *
 *     oidc.user:<authority>:<client_id>
 *
 * The body is a JSON-stringified `User` with at minimum:
 *   - access_token, id_token, refresh_token (any string is fine for
 *     the in-app code paths — the gate is `auth.isAuthenticated`)
 *   - profile (claims) including sub, email, preferred_username
 *   - expires_at (unix-seconds in the future)
 *
 * If the auth library evolves and rejects this shape the failure
 * surfaces as the app bouncing to /login.
 */

const AUTHORITY = "http://localhost:8080/realms/missionagre";
const CLIENT_ID = "missionagre-api";
const STORAGE_KEY = `oidc.user:${AUTHORITY}:${CLIENT_ID}`;

const FAKE_USER_ID = "11111111-1111-7111-8111-111111111111";
const FAKE_TENANT_ID = "22222222-2222-7222-8222-222222222222";
const FAKE_TENANT_SLUG = "e2e-tenant";

function base64Url(input: string): string {
  // Browser-context btoa exists in Node test runners as well via jsdom,
  // but Playwright's test runner runs on Node so we use Buffer here.
  return Buffer.from(input, "utf-8")
    .toString("base64")
    .replace(/=+$/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function fakeJwt(claims: Record<string, unknown>): string {
  // The frontend's `decodeJwt` only base64-decodes the payload; the
  // header + signature are opaque to it. The backend validates real
  // tokens — Playwright never reaches the backend.
  const header = base64Url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64Url(JSON.stringify(claims));
  return `${header}.${payload}.fake-signature`;
}

function fakeOidcUser(): string {
  // expires_at one hour from now.
  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  const claims = {
    sub: FAKE_USER_ID,
    tenant_id: FAKE_TENANT_ID,
    tenant_role: "TenantAdmin",
    platform_role: null,
    farm_scopes: [],
    preferred_language: "en",
    preferred_unit: "feddan",
    iat: Math.floor(Date.now() / 1000),
    exp: expiresAt,
  };
  const accessToken = fakeJwt(claims);
  return JSON.stringify({
    id_token: accessToken,
    access_token: accessToken,
    refresh_token: "fake.refresh.token",
    token_type: "Bearer",
    scope: "openid profile email",
    expires_at: expiresAt,
    profile: {
      sub: FAKE_USER_ID,
      email: "e2e@e2e.test",
      email_verified: true,
      preferred_username: "e2e@e2e.test",
      name: "E2E Tester",
    },
  });
}

// Mirrors src/api/me.ts::Me. If the contract there evolves, mirror here.
function fakeMeBody(): Record<string, unknown> {
  const now = new Date().toISOString();
  return {
    id: FAKE_USER_ID,
    email: "e2e@e2e.test",
    full_name: "E2E Tester",
    phone: null,
    avatar_url: null,
    status: "active",
    last_login_at: now,
    preferences: {
      language: "en",
      numerals: "western",
      unit_system: "feddan",
      timezone: "UTC",
      date_format: "YYYY-MM-DD",
      notification_channels: ["in_app"],
    },
    platform_roles: [],
    tenant_memberships: [
      {
        tenant_id: FAKE_TENANT_ID,
        tenant_slug: FAKE_TENANT_SLUG,
        tenant_name: "E2E Tenant",
        status: "active",
        joined_at: now,
        tenant_roles: [{ role: "TenantAdmin", granted_at: now }],
      },
    ],
    farm_scopes: [],
  };
}

async function installAuth(page: Page): Promise<void> {
  await page.addInitScript(
    ({ key, value }) => {
      window.sessionStorage.setItem(key, value);
    },
    { key: STORAGE_KEY, value: fakeOidcUser() },
  );
}

async function installApiMocks(page: Page): Promise<void> {
  // Catch-all for unmocked API calls so a missing route surfaces as a
  // visible 501 in the test rather than a hanging request.
  await page.route("**/api/v1/**", async (route, request) => {
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    if (path === "/me" || path === "/me/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(fakeMeBody()),
      });
      return;
    }
    if (path === "/config" || path === "/config/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          environment: "e2e",
          features: {},
          tenant: { id: FAKE_TENANT_ID, slug: FAKE_TENANT_SLUG },
        }),
      });
      return;
    }
    if (path === "/farms" || path === "/farms/") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
      return;
    }
    // Default empty success for any other GET — keeps the test
    // resilient to unrelated polling. Mutation endpoints fall through
    // to a 501 below so we don't accidentally pretend writes succeed.
    if (request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
      return;
    }
    await route.fulfill({
      status: 501,
      contentType: "application/problem+json",
      body: JSON.stringify({
        type: "about:blank",
        title: "Unmocked endpoint",
        status: 501,
        detail: `Add a route mock for ${request.method()} ${path} in fixtures.ts.`,
      }),
    });
  });
}

export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await installAuth(page);
    await installApiMocks(page);
    await use(page);
  },
});

export { expect };
