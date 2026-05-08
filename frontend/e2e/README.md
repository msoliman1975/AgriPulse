# Playwright e2e suite

Golden-path smoke + deeper-flow tests that run against the Vite dev
server with backend / Keycloak fully mocked at the network layer. The
goal is "boots and renders" coverage you can run locally in seconds,
not full integration coverage — that lives in
`backend/tests/integration/`.

## Run

```sh
pnpm test:e2e          # headless
pnpm test:e2e:ui       # Playwright UI mode
```

Playwright launches the dev server itself (`webServer` block in
`playwright.config.ts`). On first run, install the browser binary:

```sh
npx playwright install chromium
```

## Auth bypass

`fixtures.ts` pre-seeds `sessionStorage` with an OIDC user record
matching the key `oidc.user:<authority>:<client_id>` that
`react-oidc-context`/`oidc-client-ts` looks for. The `access_token` is
a real-shaped JWT (header.payload.signature) whose payload includes
`tenant_role: "TenantAdmin"` so the frontend's capability gates open
without needing a Keycloak round-trip.

If `decodeJwt` in `src/rbac/jwt.ts` ever needs additional claims
(`platform_role`, `farm_scopes`), update `fakeOidcUser()` to include
them.

## API mocks

`installApiMocks()` registers a catch-all `page.route("**/api/v1/**")`:

- `/me` returns a fake user/tenant/preferences body matching
  `src/api/me.ts::Me`. Update both sides if the contract changes.
- `/config`, `/farms`, and any other GET return empty success bodies.
- Mutation endpoints (POST/PATCH/PUT/DELETE) fall through to **501**
  with a problem+json body — the test fails fast if a flow
  unexpectedly tries to write.

To exercise a specific flow (e.g. alert acknowledge), override the
catch-all in your spec with `authedPage.route("**/api/v1/alerts**", ...)`
returning the data the page needs and asserting on the request body
via `route.request().postDataJSON()`. See `specs/alerts.spec.ts` for
the pattern.

## Adding a new spec

1. Create `e2e/specs/<flow>.spec.ts`.
2. `import { test, expect } from "../fixtures"` — gets you the
   `authedPage` fixture with auth + base mocks installed.
3. Override routes for the resources your flow touches.
4. Drive the page with `getByRole` / `getByText` (i18n-aware via
   user-visible labels). Avoid CSS selectors except as last resort —
   they break when classnames get refactored.

## Known gaps

- No real backend / Keycloak path. Add a `e2e:integration` script if
  you want to gate merges on a real-stack run.
- No mobile viewport coverage. Default project is Desktop Chrome.
- Map-heavy pages (block detail with deck.gl) are not covered — they
  need WebGL setup and a non-trivial fixture body.
