# Prompt 1 — Foundation

> **How to use this prompt**
> Paste the entire content below the `---` line into Claude Code as the first user message of a fresh session. Make sure Claude Code has the repository `msoliman1975/MissionAgre` available locally and that you have placed `docs/ARCHITECTURE.md` and `docs/data_model.md` in the repository's `docs/` directory before starting.

---

# Mission

You are building the foundation of MissionAgre, a multi-tenant satellite-driven farm management SaaS for Egypt. The repository is `msoliman1975/MissionAgre`. The repository is empty except for `docs/ARCHITECTURE.md` and `docs/data_model.md`. Your job is to deliver Prompt 1 — Foundation — exactly as scoped below.

# Mandatory first step

**Before writing any code:** read `docs/ARCHITECTURE.md` and `docs/data_model.md` end to end. These are binding constraints. If anything you are about to do contradicts them, stop and ask. Do not silently substitute your judgment.

Then read `prompts/roadmap.md` to understand where Prompt 1 sits in the larger six-prompt arc. You are building Prompt 1 only.

# Operating rules for this session

1. **Stay strictly within the "in scope" list.** If you find yourself wanting to build a feature that's not on the list, stop and confirm with me first.
2. **Do not invent architecture.** Every architectural choice — language, framework, library, pattern — is in `ARCHITECTURE.md`. If a choice you need to make isn't there, ask.
3. **Module boundaries are non-negotiable.** No cross-module imports of internals. No reading another module's tables in SQL. The `import-linter` config you create in this prompt enforces this from day one.
4. **Commits and PRs:** make small, focused commits with conventional-commit-style messages (`feat(iam): add JWT validation middleware`). Open a PR when each major chunk is ready (foundations / backend / frontend / infra / CI). Squash-merge into `main`.
5. **Tests are not optional.** Every Python module gets at least one unit test; the foundation tasks have integration tests that prove they work.
6. **When you're stuck or uncertain about a tradeoff, ask the human.** Do not make a 50/50 call alone.

# What you are building (in scope)

Reproduce here for clarity. Authoritative reference is `prompts/roadmap.md` § Prompt 1.

## Repository structure
Set up the monorepo exactly as described in `ARCHITECTURE.md` § 4. Create empty placeholder folders for modules you are not yet implementing (so the import-linter contract can be defined for the full module set up front).

## Backend (`backend/`)

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, Celery, Redis client, structlog, OpenTelemetry, prometheus-fastapi-instrumentator. Use `uv` as the package manager.
- App factory pattern in `app/core/app_factory.py` returning a configured `FastAPI()` instance.
- Configuration via `pydantic-settings` reading from environment variables; settings module in `app/core/settings.py`.
- Database session management:
  - Async SQLAlchemy engine with connection pooling sized appropriately for K8s (start with `pool_size=5`, `max_overflow=10`).
  - A FastAPI dependency `get_db_session` that opens a session, runs `SET LOCAL search_path TO tenant_<id>, public` based on the JWT's `tenant_id` claim, yields the session, commits or rolls back, closes.
  - For requests without a tenant context (admin endpoints, health), only `public` is in `search_path`.
- JWT validation middleware:
  - Validates against Keycloak's JWKS endpoint (configured by env).
  - Caches JWKS for 1 hour.
  - Extracts: `sub`, `tenant_id`, `tenant_role`, `platform_role`, `farm_scopes`, `preferred_language`, `preferred_unit`. Stores them on `request.state` as a typed `RequestContext` object.
  - 401 on missing/invalid token; 401 on expired token. Health endpoint excluded.
- RBAC:
  - `app/shared/rbac/capabilities.yaml` — list of all capabilities the platform recognizes (use the data model + module list to derive a complete-enough first version; mark "stub" capabilities for modules not yet built).
  - `app/shared/rbac/role_capabilities.yaml` — eight roles → capability lists.
  - `app/shared/rbac/check.py` — `requires_capability("alert.acknowledge", farm_id=...)` as a FastAPI dependency factory and a callable for non-route checks. Resolves the three-layer order: PlatformRole → TenantRole → FarmScope.
- In-process event bus:
  - `app/shared/eventbus/bus.py` — supports sync subscribers (run inline) and async subscribers (dispatched as Celery tasks).
  - Subscribers register at app startup via decorators or an explicit registry.
- Celery:
  - Two worker entrypoints: `workers/light/main.py`, `workers/heavy/main.py` — same codebase, different `Celery(...)` instances bound to different queues.
  - `workers/beat/main.py` for scheduling. No real schedules yet — just the scaffold.
- Observability:
  - structlog configured to emit JSON.
  - OpenTelemetry auto-instrumentation for FastAPI, SQLAlchemy, httpx, Celery.
  - Prometheus metrics endpoint `/metrics` on a separate port (not exposed via ingress).
  - Correlation ID middleware: reads `X-Correlation-ID` from the request, generates one if missing, attaches it to the context, propagates to logs and traces.
- Modules implemented in this prompt:
  - `tenancy`: full minimum — Tenant, TenantSubscription, TenantSettings tables; `POST /api/v1/admin/tenants` endpoint (PlatformAdmin only) that creates the tenant, runs the tenant-schema bootstrap (creates `tenant_<uuid>` schema, applies tenant migrations to it).
  - `iam`: full minimum — User, UserPreferences, TenantMembership, TenantRoleAssignment, FarmScope, PlatformRoleAssignment tables; `GET /api/v1/me` returns user profile + preferences + memberships + scopes.
  - `audit`: minimal — `audit_events` hypertable; `audit.record(event)` interface used by tenant creation. No frontend yet.
- Modules with placeholder folders only (so import-linter contracts can be set up):
  - `farms`, `imagery`, `indices`, `weather`, `signals`, `alerts`, `recommendations`, `analytics`, `notifications`. Each is a folder with an empty `__init__.py`, an empty `service.py`, an empty `events.py`, and a `# TODO: prompt 2-5` marker.
- Migrations:
  - `backend/migrations/public/` — Alembic init for shared schema.
  - `backend/migrations/tenant/` — separate Alembic env for the per-tenant schema; a runner script `scripts/migrate_tenants.py` that loops `public.tenants` and applies tenant migrations to each schema with checkpointing.
- import-linter config:
  - Layered architecture contract: shared → modules cannot import each other's internals.
  - One contract per module pair (forbidden cross-module-internal imports). The full set of modules is in scope here even though most are stubs — establish the contracts now so they cannot be violated as modules fill in.
- Tests:
  - `pytest` with `pytest-asyncio`, `pytest-postgresql` (or testcontainers), `httpx` async client.
  - Unit tests for: settings, RBAC capability resolver, event bus, JWT validator, correlation ID middleware.
  - Integration tests for: tenant creation flow (creates schema, applies migrations, audit event written), `/me` flow (real Keycloak token validation), search_path isolation (a request with tenant A's JWT cannot read tenant B's data even via raw SQL through the session).

## Frontend (`frontend/`)

- React 18 + TypeScript + Vite. `pnpm` as the package manager.
- Tailwind CSS with the RTL plugin (`tailwindcss-rtl` or equivalent that supports logical properties), configured with the design tokens from `ARCHITECTURE.md`.
- `react-i18next` set up with namespaces matching the backend modules. Empty `en/common.json` and `ar/common.json` for now plus `en/auth.json` and `ar/auth.json` with the strings needed for login and `/me`.
- OIDC client — use `oidc-client-ts` or `react-oidc-context` against Keycloak. Authorization Code flow with PKCE. Tokens stored in memory (not localStorage); refresh tokens via silent renew.
- Axios (or fetch wrapper) instance with interceptor that:
  - Attaches the Bearer token.
  - Handles 401 by triggering re-login.
  - Surfaces RFC 7807 errors as typed objects.
- App shell:
  - Header with logo, language toggle (en/ar — toggles `dir` on `<html>`), unit toggle (feddan/acre), user menu.
  - Side nav placeholder (modules will fill it later).
  - Routing via `react-router-dom` v6.
- Pages:
  - `/login` — redirects to Keycloak.
  - `/me` — fetches `/api/v1/me`, displays user info, language preference, unit preference, list of tenant memberships and farm scopes.
  - `/` — placeholder dashboard saying "Welcome — features coming soon."
- Logical CSS properties everywhere (`margin-inline-start`, etc.). No `margin-left`/`margin-right`. RTL must work end-to-end on the three pages above.
- Testing:
  - Vitest for unit tests; React Testing Library for component tests.
  - One test per page that renders correctly in both `en` (LTR) and `ar` (RTL).

## Tile server (`tile-server/`)

- A Dockerfile based on the official TiTiler image.
- Configuration override that exposes `/health` and `/tiles/...` endpoints.
- A small Helm chart in `infra/helm/tile-server/`.
- No real data integration yet — just verify the deployment is reachable from the cluster ingress and returns 200 on `/health`.

## Infrastructure (`infra/`)

- **Terraform** (`infra/terraform/`):
  - VPC with public + private subnets in `me-south-1`.
  - EKS cluster (start with 3 `t3.large` nodes; upsize later).
  - S3 buckets: one for `imagery-raw`, one for `imagery-cogs`, one for `exports`. Versioning enabled. Lifecycle rule placeholders.
  - KMS key for secrets.
  - IAM roles for EKS service accounts (IRSA) for: backend, workers, tile-server, external-secrets-operator, cloudnativepg.
- **Helm charts** (`infra/helm/`):
  - One chart per service: `api`, `workers`, `tile-server`, `frontend`, `keycloak`, plus a `shared` chart for cluster-wide ConfigMaps and Secrets templates.
  - All charts use logical CSS-equivalent values: structured `values.yaml`, no hardcoded image tags, `imageTag: "{{ .Chart.AppVersion }}"` pattern.
- **CloudNativePG** Postgres cluster manifest:
  - Primary + 1 standby.
  - 3 replicas of the streaming-replica config.
  - `postInitSQL` enables `postgis`, `timescaledb`, `pgstac`, `pgaudit`.
  - Backup configuration to S3 (PITR).
- **External Secrets Operator** Helm install + a sample ExternalSecret pulling from AWS Secrets Manager.
- **Observability stack**:
  - `kube-prometheus-stack` for Prometheus + Grafana.
  - `loki-stack` for Loki + Promtail.
  - `tempo` for traces.
  - GlitchTip via a community Helm chart or manifest.
  - Pre-provisioned Grafana dashboards for: API request rate/latency, Celery queue depth, Postgres connections, JVM/Python runtime metrics.
- **NGINX Ingress Controller** + cert-manager + a wildcard cert for `*.dev.missionagre.local` (or whatever placeholder domain you use for dev).
- **ArgoCD ApplicationSet** in `infra/argocd/` that points at `infra/helm/` and `infra/argocd/` for each environment. Auto-sync for `dev`, manual sync for `staging` and `production`.

## CI/CD (`.github/`)

- **Workflows** (`.github/workflows/`):
  - `ci.yml` — runs on every PR and push:
    - Backend job: `uv sync`, `ruff check`, `black --check`, `mypy`, `import-linter`, `pytest` (with Postgres + Redis service containers).
    - Frontend job: `pnpm install`, `eslint`, `tsc --noEmit`, `prettier --check`, `vitest`.
    - Helm job: `helm lint` for every chart in `infra/helm/`.
    - Container build job: build images for `api`, `workers`, `tile-server`, `frontend`. Push to GHCR only on merge to `main`, tagged with both `latest` and the commit SHA.
  - `argocd-sync.yml` — on merge to `main`, opens a PR in a separate `infra/argocd/` ApplicationSet config to bump image tags. Or use ArgoCD Image Updater — your choice; document it.
  - `dependabot.yml` — pip, npm, Docker, GitHub Actions, weekly.
- **Branch protection** on `main`: configure via the GitHub API (use `gh api`) at the end of the prompt:
  - Required reviewers: 1.
  - Required status checks: `ci / backend`, `ci / frontend`, `ci / helm`, `ci / containers`.
  - Linear history required.
  - Conversations resolved required.
  - No force-push, no direct push.
- **CODEOWNERS** at `.github/CODEOWNERS` — single line owning the whole repo (`* @msoliman1975`); we'll refine as the team grows.
- **Issue and PR templates** at `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md`.
- **Pre-commit hooks** via `pre-commit` config: `ruff`, `black`, `mypy`, `prettier`, `eslint --fix`. `pre-commit install` in the repo.

# What is explicitly out of scope (do NOT build)

If you find yourself building any of these, stop:

- Any farm, block, imagery, alert, recommendation, weather, signal feature beyond data-model-defined empty placeholder folders.
- Any real Sentinel Hub or Open-Meteo integration.
- Any real frontend feature beyond `/login` and `/me`.
- Production-grade backups (basic CloudNativePG config is enough; advanced PITR test is Prompt 6).
- SMS, mobile app, IoT, billing, forecasting.
- Performance tuning beyond reasonable defaults — Prompt 6 handles polish.
- Apache Superset, OpenFGA, Kafka, NATS, gRPC.

# Definition of done — your gate

You are done with Prompt 1 when **all** of the following are true. I will check each one before approving the gate. Provide evidence (logs, screenshots, command output) in the final PR description.

1. `git push` to `main` triggers CI; all CI jobs pass; container images appear in `ghcr.io/msoliman1975/missionagre/{api,workers,tile-server,frontend}` tagged with the commit SHA.
2. ArgoCD syncs the `dev` environment from the repo. After sync, every pod across every service reaches `Running` state. Provide the output of `kubectl get pods -A` showing this.
3. A `PlatformAdmin` user (you'll need to create one in Keycloak via a seed script) calls `POST /api/v1/admin/tenants` with a sample payload and receives 201 with the tenant payload back. The new tenant's schema exists in Postgres (`\dn` in psql shows `tenant_<uuid>`). The tenant has its tenant migrations applied.
4. A non-platform-admin user calling the same endpoint receives 403.
5. A test user can complete the OIDC login flow in the browser (against the dev Keycloak) and lands on `/me` showing their profile.
6. The language toggle on `/me` switches between `en` (LTR) and `ar` (RTL); the `<html dir>` attribute changes; RTL layout is correct (logical CSS verified).
7. A request to a protected endpoint:
   - With no JWT → 401.
   - With a valid JWT but lacking the required capability → 403.
   - With the right JWT and capability → 200.
8. Tracing: in Grafana Tempo, a single `/api/v1/me` request shows up with spans through middleware, route, repository, and DB. Provide a screenshot.
9. Metrics: Grafana shows `http_requests_total` and `http_request_duration_seconds` for `/api/v1/me`. Provide a screenshot.
10. Logs: the same request flows through Loki as structured JSON with a single `correlation_id` joining all log lines. Provide a query screenshot.
11. `import-linter` runs in CI and passes. The contracts file lists all 13 modules with cross-module-internal imports forbidden.
12. Tenant isolation test: an integration test exists that creates two tenants, two users (one in each), and proves that user A's request cannot read tenant B's data via:
    - The HTTP API (404/403).
    - Direct SQL through the request session (returns empty).

# Reporting back

When you finish, post in the final PR description:

- A link to each merged PR for this prompt.
- The output of `kubectl get pods -A` from the dev cluster.
- Screenshots for items 6, 8, 9, 10 above.
- A brief "what's next" note: any deviations from `ARCHITECTURE.md` or `data_model.md` you needed to make, with rationale, so I can update the docs before Prompt 2.

# When to stop and ask

Stop and ask the human in any of these cases:

- An architectural decision is missing from `ARCHITECTURE.md`.
- A library you'd reach for has known security or licensing issues.
- The data model has an ambiguity that affects implementation.
- A test is failing in a way that suggests a deeper problem.
- You catch yourself building something on the "out of scope" list.
- You'd be making a 50/50 call between two reasonable approaches.

I'd much rather answer five questions than rebuild a foundation.

Begin by reading the three referenced documents (`docs/ARCHITECTURE.md`, `docs/data_model.md`, `prompts/roadmap.md`) and confirming you understand the scope. Then propose a sequencing of the work (which PR first, what's in each) and wait for my approval before writing code.
