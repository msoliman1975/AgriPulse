# MissionAgre frontend

React 18 + TypeScript + Vite SPA. Tailwind with `tailwindcss-rtl` for
bilingual (en + ar) support. OIDC against Keycloak via `react-oidc-context`.

## Local setup

The backend services (Postgres, Redis, Keycloak, MinIO) run in containers;
see [`backend/README.md`](../backend/README.md) for `docker compose -f
infra/dev/compose.yaml up -d`.

```bash
# 1. Use Node 20+ and enable corepack for pnpm.
corepack enable

# 2. Install deps.
pnpm install

# 3. Configure env.
cp .env.example .env.local       # edit only if defaults don't match
                                  # infra/dev/compose.yaml

# 4. Run the dev server (proxies /api/* to the backend on :8000).
pnpm dev                          # http://localhost:5173
```

Sign in with `dev@missionagre.local` / `dev` (the seed user from the
imported Keycloak realm).

## Scripts

| Command             | What it does                                 |
| ------------------- | -------------------------------------------- |
| `pnpm dev`          | Vite dev server with HMR + `/api` proxy.     |
| `pnpm build`        | Type-check then build to `dist/`.            |
| `pnpm preview`      | Serve the production build locally.          |
| `pnpm lint`         | ESLint flat-config over `src/` and `tests/`. |
| `pnpm typecheck`    | `tsc -b --noEmit`.                           |
| `pnpm format`       | Prettier write.                              |
| `pnpm format:check` | Prettier check (used by CI).                 |
| `pnpm test`         | Vitest run.                                  |
| `pnpm test:watch`   | Vitest in watch mode.                        |

## Layout

```
src/
  api/        Axios client + RFC 7807 typed errors + endpoint modules.
  auth/       OIDC config + provider + ProtectedRoute + token registry.
  i18n/       react-i18next bootstrap + locale JSON (en, ar).
  pages/      Route components: HomePage, LoginPage, MePage.
  prefs/      User preferences context (area unit toggle).
  shell/      Header, SideNav, AppShell.
  styles/     Tailwind entry + design tokens.
tests/        Test setup (jest-dom, cleanup).
```

`tailwindcss-rtl` mirrors directional utilities for `dir="rtl"`. Components
prefer logical properties (`ms-`, `me-`, `border-e`, `start-`) where
Tailwind ships them so the same class works in both directions.
