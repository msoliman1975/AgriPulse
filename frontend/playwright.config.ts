import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config â€” golden-path smoke suite.
 *
 * The dev server is launched by Playwright (`webServer` block). All API
 * calls are mocked at the network layer via `page.route()` so e2e
 * doesn't need a running backend or Keycloak; the auth state is
 * pre-seeded into sessionStorage so the OIDC redirect never fires.
 *
 * To run a real backend-backed flow later, copy a spec under
 * `e2e/specs/` and replace the route mocks with calls against the real
 * dev API. The `webServer.env` block here mirrors `.env.example` â€”
 * adjust if you point at a non-default backend.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      // The OIDC config requires these at module-import time. The values
      // are not exercised because Playwright pre-seeds an authenticated
      // sessionStorage entry before the page boots.
      VITE_API_BASE_URL: "/api",
      VITE_OIDC_AUTHORITY: "http://localhost:8080/realms/agripulse",
      VITE_OIDC_CLIENT_ID: "agripulse-api",
      VITE_OIDC_REDIRECT_URI: "http://127.0.0.1:5173/auth/callback",
      VITE_OIDC_POST_LOGOUT_REDIRECT_URI: "http://127.0.0.1:5173/",
      VITE_OIDC_SCOPE: "openid profile email",
    },
  },
});
