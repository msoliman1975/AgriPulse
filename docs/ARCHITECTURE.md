# MissionAgre — Architecture Decisions

**Repo:** `msoliman1975/MissionAgre`
**Status:** Binding — every Claude Code session reads this first.
**Last updated:** 2026-04-27

---

## Purpose of this document

This file is the canonical record of architecture decisions for the MissionAgre platform. It is **binding**: any code, configuration, or library choice that contradicts this file is wrong and must be reverted. New decisions are added here first, code follows.

When in doubt during a Claude Code session: re-read this file. Do not invent new patterns. Do not "improve" decisions. If something looks wrong or under-specified, stop and ask the human — do not silently substitute your own judgment.

---

## 1. What we are building

A multi-tenant, cloud-native SaaS for commercial agribusinesses in Egypt to monitor crop health, irrigation, and weather using satellite imagery, weather forecasts, and custom signals; with rules-based alerting and explainable agronomic recommendations.

**MVP target:** 1–3 paying tenants, 6-week build, single AWS region.
**Year 3 target:** 500 tenants, ~25K blocks, single Postgres+TimescaleDB instance.

## 2. Pillars (immutable)

- Multi-user, multi-tenant (bridge model: shared infrastructure, schema-per-tenant)
- Cloud-native, Kubernetes-based, cloud-portable (no vendor-locked managed services in the core)
- Fine-granular RBAC (capability-based, eight roles, three-layer resolution)
- Subscription-based (manual invoicing in MVP; Stripe/Paymob in P2)
- English + Arabic UI with RTL support; user-level language and unit preferences
- Egyptian context: feddan as primary unit, governorate as administrative geography, salinity-aware soil model, Nile/canal/well water-source distinction

## 3. Stack — committed

### 3.1 Languages and frameworks

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic
- **Workers:** Celery 5.x with Redis broker; Celery Beat for scheduling
- **Frontend:** React 18+, TypeScript 5+, Vite, react-i18next, MapLibre GL, deck.gl, Recharts
- **Tile server:** TiTiler (FastAPI-based COG → XYZ/WMTS)
- **Identity:** Keycloak (single realm, tenant_id as JWT claim)
- **Database:** PostgreSQL 16 with extensions: PostGIS 3.4, TimescaleDB 2.x, pgstac, pgaudit
- **Cache/queue/pub-sub:** Redis 7.x (single instance, three jobs: cache, Celery broker, SSE pub/sub)
- **Object storage:** S3-compatible, abstracted via `boto3` with configurable endpoint

### 3.2 Deployment

- **Cloud:** AWS me-south-1 (Bahrain) for MVP — co-located with Sentinel-2 Open Data on S3
- **Orchestration:** Kubernetes (EKS); 3 clusters (`dev`, `staging`, `production`)
- **Operator-managed Postgres:** CloudNativePG (primary + 1 standby, PITR to S3)
- **GitOps:** ArgoCD reading from Helm charts in the same repo
- **Secrets:** External Secrets Operator → AWS Secrets Manager
- **Ingress:** NGINX Ingress Controller; cert-manager for Let's Encrypt
- **Edge protection:** AWS WAF + Shield Standard; NGINX rate limiting per tenant token

### 3.3 Observability

- **Metrics:** Prometheus + `prometheus-fastapi-instrumentator`
- **Logs:** Structured JSON → Loki
- **Traces:** OpenTelemetry → Tempo
- **Dashboards:** Grafana (single pane for all three)
- **Errors:** GlitchTip (open-source Sentry alternative)
- **Correlation:** request IDs propagated through Celery tasks and external calls

### 3.4 What we deliberately *did not* choose

These were considered and rejected — do not reintroduce without an explicit decision:

- Django, Flask (we use FastAPI)
- Mapbox GL JS (we use MapLibre GL — no proprietary licensing)
- Mongo, DynamoDB, ClickHouse for primary storage (Postgres handles it at our scale)
- gRPC between services (REST for everything; SSE for live updates)
- Kafka, NATS for events (in-process bus + Celery is sufficient for MVP)
- OpenFGA, Cerbos, OPA (in-process capability-based RBAC for MVP)
- Auth0, AWS Cognito (Keycloak)
- Apache Superset in MVP (native React dashboards in MVP, Superset in Phase 2)
- Helm umbrella chart of charts (one chart per service is simpler)

## 4. Repository layout (monorepo)

```
MissionAgre/
├── backend/
│   ├── app/
│   │   ├── modules/         # one folder per module (see § 6)
│   │   ├── shared/          # _shared/conditions, _shared/db, _shared/auth_utils
│   │   ├── core/            # config, logging, observability, FastAPI app factory
│   │   └── main.py          # entry point
│   ├── workers/
│   │   ├── light/           # Celery worker entrypoint for light queue
│   │   ├── heavy/           # Celery worker entrypoint for heavy queue
│   │   └── beat/            # Celery beat schedules
│   ├── migrations/
│   │   ├── public/          # Alembic migrations for shared schema
│   │   └── tenant/          # Migrations applied per-tenant by custom runner
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── e2e/
│   ├── pyproject.toml       # uv or poetry; we use uv
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── modules/         # mirrors backend modules
│   │   ├── shared/
│   │   ├── i18n/            # en/ar locale files per namespace
│   │   └── main.tsx
│   ├── tests/
│   ├── package.json
│   └── Dockerfile
├── tile-server/
│   ├── Dockerfile           # TiTiler image with our config overrides
│   └── config/
├── infra/
│   ├── helm/
│   │   ├── api/
│   │   ├── workers/
│   │   ├── tile-server/
│   │   ├── frontend/
│   │   └── shared/          # ConfigMaps, Secrets templates, ServiceAccounts
│   ├── argocd/              # ApplicationSet manifests
│   └── terraform/           # AWS bootstrap (VPC, EKS, RDS-if-used, S3, KMS)
├── docs/
│   ├── ARCHITECTURE.md      # this file
│   ├── data_model.md        # the data model document
│   ├── runbooks/
│   └── decisions/           # ADR-style records for new decisions
├── prompts/                 # Claude Code session prompts
├── .github/
│   ├── workflows/           # CI pipelines
│   ├── CODEOWNERS
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── scripts/
└── README.md
```

**Rules:**
- Monorepo, single `main` branch, trunk-based development.
- Feature branches live <2 days; squash-merge into `main`.
- No long-lived branches except `main`.
- Each top-level folder (`backend`, `frontend`, `tile-server`, `infra`) has its own Dockerfile and CI job.

## 5. Tenancy model — committed

- **Schema-per-tenant** within a single Postgres instance.
- Two schema namespaces:
  - `public` — shared catalogs (crops, indices, decision trees, imagery providers, notification templates), tenants table, users table, RBAC tables.
  - `tenant_<uuid>` — all tenant-owned data (farms, blocks, indices aggregates, alerts, etc.).
- Tenant resolution from JWT claim only — never from URL path or query parameter.
- FastAPI middleware reads `tenant_id` from JWT and runs `SET LOCAL search_path TO tenant_<id>, public` for the duration of the request transaction.
- RLS policies on shared tables that contain tenant FKs as defense-in-depth.
- Cross-schema FKs are *logical*, not declarative — application enforces them; a periodic consistency-check job logs orphans.

## 6. Module map — committed

The backend is a modular monolith with thirteen modules. Each module is a folder under `backend/app/modules/`.

| # | Module | Purpose | Schema |
|---|---|---|---|
| 1 | `iam` | Auth integration, RBAC enforcement, user CRUD | `public` |
| 2 | `tenancy` | Tenant context, schema routing, subscription | `public` |
| 3 | `farms` | Farms, blocks, AOI, crop assignments | tenant |
| 4 | `imagery` | Provider abstraction, STAC catalog, raster ops | mixed |
| 5 | `indices` | Index computation, aggregation jobs | tenant |
| 6 | `weather` | Provider integration, derived signals | tenant |
| 7 | `signals` | Custom user-defined signals | tenant |
| 8 | `alerts` | Rule engine, alert lifecycle | tenant |
| 9 | `recommendations` | Decision tree engine, lifecycle | mixed |
| 10 | `analytics` | Aggregations, dashboard data endpoints | tenant (views) |
| 11 | `notifications` | Email, in-app, webhook dispatch | tenant |
| 12 | `audit` | Domain events, sensitive-data audit | tenant |

`forecasting` is **out of scope** for MVP and is not built.

### 6.1 Module boundaries — enforced

Each module exposes exactly two things to the outside world:

- `service.py` — public Protocol(s) and concrete implementation. Consumers depend on the Protocol; concrete impls wired via dependency injection.
- `events.py` — public event types as Pydantic models. Versioned (`FarmCreatedV1`).

Forbidden:
- Importing across module internals (`module_a/repository`, `module_a/domain`)
- Reading or writing another module's tables in SQL
- Direct function calls into another module's internal helpers

Enforced by:
- `import-linter` in CI with explicit contracts
- Code review

The single allowed exception is `app/shared/` — leaf utilities used everywhere (DB session helpers, auth utilities, the conditions library used by `alerts` and `recommendations`).

### 6.2 Inter-module communication

- **Cross-module commands** (give me X, do Y) → call the target module's service Protocol via DI.
- **Cross-module reactions** (X happened, multiple modules want to know) → publish via in-process event bus; subscribers register handlers at app startup; sync handlers run in-request, async handlers go through Celery.

## 7. RBAC — committed

### 7.1 Eight roles

| Role | Scope | Description |
|---|---|---|
| `PlatformAdmin` | Platform | Anthropic-equivalent: our team |
| `TenantOwner` | Tenant | Customer super-admin, exactly one per tenant |
| `TenantAdmin` | Tenant | Customer admin |
| `FarmManager` | Farm-scoped | Manages farm + blocks |
| `Agronomist` | Farm-scoped | Agronomic actions, no geometry edit |
| `FieldOperator` | Farm-scoped | Operational records (irrigation, fertilization) |
| `Scout` | Farm-scoped | Observations + photos only |
| `Viewer` | Farm-scoped | Read-only |

### 7.2 Capabilities, not role checks

- Capabilities defined in `backend/app/shared/rbac/capabilities.yaml`.
- Roles map to capabilities in `backend/app/shared/rbac/role_capabilities.yaml`.
- Code uses `@requires_capability("alert.acknowledge", farm_id=...)` decorators or `Depends()` patterns — never `if role == "..."`.

### 7.3 JWT claim shape

```json
{
  "sub": "<user-uuid>",
  "tenant_id": "<tenant-uuid>",
  "tenant_role": "TenantAdmin | null",
  "platform_role": "PlatformAdmin | null",
  "farm_scopes": [
    {"farm_id": "<uuid>", "role": "FarmManager"}
  ],
  "preferred_language": "en | ar",
  "preferred_unit": "feddan | acre | hectare"
}
```

Resolution order: PlatformRole → TenantRole → FarmScope (first match wins).

`farm_scopes` are embedded in the JWT for MVP; revocation latency = token TTL (15 minutes). Cached lookup with Redis is a P2 upgrade.

## 8. API conventions — committed

- REST, OpenAPI 3.x first.
- All endpoints under `/api/v1/...`.
- No tenant in the URL path — always resolved from JWT.
- Server-Sent Events (SSE) for live alerts: `GET /api/v1/me/alerts/stream`.
- Tile endpoints (separate service): `/tiles/{collection}/{z}/{x}/{y}.png?...`.
- Snake_case for JSON keys.
- Timestamps as RFC 3339 strings.
- Areas in `m2` (square meters) on the wire; client converts to feddan/acre/hectare for display.
- Pagination: `?limit=50&cursor=<opaque>` (cursor-based, not offset).
- Errors: RFC 7807 `application/problem+json`.
- Idempotency for state-changing endpoints: optional `Idempotency-Key` header, stored in Redis for 24h.

## 9. Imagery pipeline — committed

- **MVP provider:** Sentinel Hub Process API behind `SentinelHubProvider` adapter.
- **Adapter pattern:** per-product adapters (`SentinelHubProvider`, future `Sentinel2OpenDataProvider`, future `PlanetScopeProvider`).
- **Index computation:** hybrid — six standard indices (NDVI, NDWI, EVI, SAVI, NDRE, GNDVI) pre-computed and stored as COGs + aggregated to TimescaleDB; custom indices on-demand.
- **Storage:** COGs in object storage in UTM 36N (EPSG:32636); web tiles served in Web Mercator (EPSG:3857) by TiTiler reprojecting on the fly.
- **STAC catalog:** pgstac inside the same Postgres instance.
- **Cloud cover thresholds:** 60% for visualization, 20% for index aggregation; per-tenant overrides.
- **Retention:** 90 days hot in S3 Standard; lifecycle rule moves to S3 Glacier Instant Retrieval after.
- **Idempotency:** deterministic asset IDs `{provider}/{product}/{scene_id}/{aoi_hash}/{index_or_band}.tif`.
- **Triggers:** Celery Beat scheduled polling + on-demand refresh button. No webhooks in MVP.

## 10. Alerts and recommendations — committed

### 10.1 Alerts
- **Tier 2 compound rules** (AND/OR groups, time windows, deltas, trends) — *not* arbitrary scripted rules.
- **Pull-based evaluation** every 15 minutes by Celery Beat.
- **Lifecycle:** `open → acknowledged → resolved` (or `→ snoozed → open`, or `→ auto_resolved`).
- **Channels in MVP:** in-app (SSE), email (SMTP), webhook (signed HMAC). No SMS until P2.
- **Cooldown** enforced structurally by uniqueness constraint on open alerts per `(rule, farm, block)`.

### 10.2 Recommendations
- **Hand-authored YAML decision trees** per crop type, versioned and immutable once published.
- **Daily per-block evaluation** (not every 15 min — recommendations are slower-moving).
- **Explainability is mandatory:** every recommendation carries the `tree_path` array of node IDs traversed and a human-readable text in `text_en` and `text_ar`.
- **Lifecycle:** `open → applied | dismissed | deferred | expired`.

### 10.3 Shared condition evaluator
- Located at `backend/app/shared/conditions/`.
- Used by both `alerts` and `recommendations` modules — never reimplement.
- Provides: data sources (indices, weather, signals), operators, aggregations, evaluator, Pydantic models for `Condition` and `ConditionGroup`.

## 11. Internationalization — committed

- **Languages:** English and Arabic at MVP launch.
- **RTL handling:** root `dir="rtl"` toggle, logical CSS properties everywhere (`margin-inline-start` not `margin-left`), Tailwind RTL plugin.
- **Frontend:** react-i18next, JSON namespaces per module, lazy-loaded.
- **Backend:** Babel/pybabel for error messages, email templates, alert/recommendation text.
- **User preferences:** language and unit on `user_preferences` table; defaults inherited from tenant.
- **Numerals in Arabic UI:** Western (0–9) by default.
- **Calendar:** Gregorian only.
- **Database stores stable English enum keys** (`drip`, `sandy_loam`); UI translates them.
- **Crop catalog has `name_en` and `name_ar` columns** as data, not as translations.

## 12. Areas and units — committed

- **Internal storage:** square meters (`NUMERIC(14, 2)`), always.
- **Display primary:** feddan (1 feddan = 4,200.83 m²).
- **Display secondary:** acre (toggle in user preferences).
- **API contract:** numeric area fields returned in m². Frontend converts to user's preferred unit at the presentation layer.
- **Never store** `area_feddan`, `area_acre`, or `area_ha` columns. No exceptions.

## 13. CI/CD — committed

- **CI:** GitHub Actions on every push and PR.
- **Required checks before merge to `main`:**
  - Backend: `ruff`, `black --check`, `mypy`, `pytest` (unit + integration)
  - Frontend: `eslint`, `tsc --noEmit`, `vitest`, `prettier --check`
  - Helm: `helm lint` for every chart
  - Container builds: backend, frontend, tile-server, workers
  - import-linter: enforces module boundary contracts
- **Artifact registry:** GitHub Container Registry (`ghcr.io/msoliman1975/missionagre/*`).
- **CD:** ArgoCD pulls from `infra/argocd/` and syncs to clusters automatically (auto-sync for `dev`, manual for `staging`/`production`).
- **GitHub Environments:** `dev` (auto), `staging` (auto with smoke tests), `production` (requires approval).
- **Branch protection on `main`:**
  - Require PR with at least one review
  - Require status checks: all CI jobs above
  - Require linear history (squash-merge only)
  - Require conversations resolved before merge
  - No force-push, no direct push

## 14. Observability conventions — committed

- **Logs:** structured JSON via `structlog`. Required fields: `timestamp`, `level`, `service`, `correlation_id`, `tenant_id`, `user_id` (when known), `message`. No PII in logs.
- **Metrics:** Prometheus naming conventions (`<namespace>_<subsystem>_<name>_<unit>_total|seconds|bytes|...`). RED metrics on every endpoint and worker task.
- **Traces:** OpenTelemetry; auto-instrumentation for FastAPI, SQLAlchemy, Celery, requests, httpx. Custom spans around index computation and alert evaluation.
- **Correlation ID:** generated at NGINX ingress (`X-Correlation-ID`), propagated through every internal call and into Celery task headers.
- **Log retention:** 30 days hot in Loki, 90 days warm in S3, 1 year cold archive.

## 15. Out of scope for MVP

These are deferred and **must not** be added during MVP development without an explicit decision:

- Yield/harvest forecasting
- Mobile offline-first app
- IoT sensor ingestion (only manual signals in MVP)
- ExternalAdvisor cross-tenant role
- Equipment, inventory, financial modules
- Real billing engine (Stripe / Paymob)
- Compliance reports (GlobalGAP, FSMA)
- ML-based field auto-detection (only grid-based auto-blocking)
- Higher-resolution imagery (Planet, Airbus)
- SMS notifications
- Apache Superset (Phase 2)
- Self-managed Sentinel-2 pipeline (only Sentinel Hub API in MVP)

## 16. New decisions process

When a new architectural decision is needed during development:

1. **Stop coding.** Do not invent and proceed.
2. Open an ADR (Architecture Decision Record) under `docs/decisions/NNNN-short-title.md` using the standard template (context, decision, consequences).
3. Get human approval on the ADR.
4. Update this document if it changes any binding constraint.
5. Then implement.

This process exists because every silent re-decision costs more to undo later than a 30-minute discussion costs now.

---

*Read this file at the start of every Claude Code session.*
