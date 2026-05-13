# AgriPulse â€” Build Roadmap (Six Prompts)

This roadmap shows the full six-prompt arc for building AgriPulse with Claude Code. Each prompt is a single Claude Code session that ends in a hard human-reviewed gate before the next prompt starts.

**Approach:** vertical slices through a horizontal foundation.
**Repo:** `msoliman1975/AgriPulse`
**Reference docs:** `docs/ARCHITECTURE.md` and `docs/data_model.md` are read at the start of every session.

---

## Overview

| # | Prompt | Goal | Duration | Gate signal |
|---|---|---|---|---|
| 1 | Foundation | Repo, infra, CI, auth, tenancy, observability | 3â€“5 days | Healthcheck endpoint authenticated; tenant created; CI green |
| 2 | Slice 1 â€” farm management | Farms, blocks, AOIs, crop assignments, basic frontend shell | 4â€“6 days | A user can create a farm and a block from the UI |
| 3 | Slice 2 â€” imagery and indices | Sentinel Hub adapter, ingestion pipeline, NDVI displayed on map | 5â€“7 days | A block shows real NDVI from a real Sentinel Hub fetch |
| 4 | Slice 3 â€” alerts and recommendations | Rule engine, decision trees, notifications | 5â€“7 days | A real alert fires from real data and emails a real user |
| 5 | Slice 4 â€” weather, signals, dashboards | Open-Meteo integration, custom signal entry, native dashboards | 4â€“6 days | The dashboard shows index trend, weather forecast, custom signals |
| 6 | Polish | i18n, RTL, audit, performance, hardening, runbooks | 4â€“6 days | Bilingual UI works end-to-end; security checklist complete |

**Total wall-clock:** ~5â€“7 weeks at single-engineer pace. The 6-week MVP target is achievable with disciplined scoping and parallel work on frontend/backend within prompts.

---

## Prompt 1 â€” Foundation

**Goal:** stand up the repository, the cluster bootstrap, the CI pipeline, the auth path, the tenant context, and the observability stack. **No business features yet.**

### In scope
- GitHub repo structure (`backend/`, `frontend/`, `tile-server/`, `infra/`, `docs/`, `prompts/`, `.github/`)
- Backend: FastAPI app skeleton with health endpoint, structured logging, OpenTelemetry, Prometheus metrics, error handling middleware, correlation-ID middleware
- Backend: SQLAlchemy + Alembic + tenant-aware session middleware (`SET LOCAL search_path`)
- Backend: Keycloak integration â€” JWT validation against JWKS, claim extraction, RBAC dependency
- Backend: capability-based RBAC (`capabilities.yaml`, `role_capabilities.yaml`, `@requires_capability` decorator)
- Backend: in-process event bus + Celery worker scaffolding (light + heavy queues, beat scheduler)
- Backend: `_shared/` skeleton (db, auth_utils, conditions stub, eventbus)
- Backend: `import-linter` config enforcing module-boundary contracts
- Backend: `tenancy` module â€” Tenant entity, TenantSubscription, TenantSettings, tenant-creation admin endpoint, tenant-schema bootstrap
- Backend: `iam` module â€” User entity, UserPreferences, TenantMembership, role-assignment tables, `/me` endpoint
- Backend: `audit` module â€” minimal `audit.record(event)` interface, `audit_events` hypertable
- Frontend: Vite + React + TypeScript scaffold, MapLibre, Recharts, Tailwind with RTL plugin
- Frontend: react-i18next setup with empty `en` and `ar` namespaces
- Frontend: OIDC login flow against Keycloak, JWT storage, axios interceptor
- Frontend: app shell with header, navigation stub, language toggle, unit toggle
- Frontend: `/me` page showing user info from backend
- Tile server: Dockerfile and minimal config (no real data yet â€” verify deployment topology)
- Infra: Helm charts for `api`, `workers`, `tile-server`, `frontend`, `keycloak`, plus a `shared` chart for ConfigMaps and Secrets
- Infra: ArgoCD ApplicationSet manifests for the three environments
- Infra: Terraform for VPC, EKS, KMS, S3 buckets, ECR (or Docker Hub) â€” minimal viable setup
- Infra: CloudNativePG operator + a single Postgres cluster manifest with PostGIS, TimescaleDB, pgstac, pgaudit
- Infra: Prometheus + Loki + Tempo + Grafana + GlitchTip via kube-prometheus-stack and Grafana Loki/Tempo charts
- CI: lint, typecheck, test, container build, Helm lint, import-linter for backend; eslint, tsc, vitest, prettier for frontend
- CI: branch protection rules, CODEOWNERS, issue templates, PR template
- CI: Dependabot config for npm, pip, Docker, GitHub Actions
- Pre-commit hooks (ruff, black, mypy, prettier)

### Out of scope (must not build)
- Any farm, block, imagery, alert, recommendation feature
- Real Sentinel Hub or Open-Meteo integration
- Real frontend features beyond `/me`
- Production-grade backups (basic config only)
- Multi-region anything

### Definition of done (the gate)
1. `git push` to `main` triggers CI; all checks pass; container images appear in GHCR.
2. ArgoCD syncs the dev environment from the repo; all pods reach `Running`.
3. A `PlatformAdmin` can call `POST /api/v1/admin/tenants` and receive a created tenant with a fresh schema.
4. A test user can complete the OIDC login flow in the browser and the `/me` page renders their info.
5. A request to a protected endpoint without a JWT returns 401; with a valid JWT but wrong role returns 403; with the right role returns 200.
6. Tracing: a single request shows up in Grafana Tempo with spans through middleware, route, repository, and DB.
7. Metrics: Grafana dashboard shows request count and p95 latency for `/me`.
8. Logs: structured JSON with `correlation_id` flow through Loki for the same request.
9. The language toggle on the frontend switches `dir` attribute and re-renders.
10. `import-linter` runs in CI and passes (no cross-module imports yet, so this is trivial â€” but the contract is in place).

This is a **lot** for one prompt. It is intentional. Everything here is foundation that every subsequent prompt assumes works. We pay the upfront cost once.

---

## Prompt 2 â€” Slice 1: farm management

**Goal:** end-to-end farm and block management. By the end, a user can sign in, create a farm, draw block boundaries on a map, assign a crop, and see the list of their farms and blocks.

### In scope
- Backend: `farms` module â€” full implementation per data model
  - `farms`, `blocks`, `block_crops`, `farm_attachments`, `block_attachments` tables
  - PostGIS triggers for `boundary_utm`, `centroid`, `area_m2`, `aoi_hash`
  - REST endpoints: CRUD farm, CRUD block (including geometry), assign crop, list
  - Service Protocols and event definitions (`FarmCreated`, `BlockBoundaryUpdated`, etc.)
  - Grid-based auto-blocking (manual editing supported)
  - File upload to S3 for attachments (presigned URL pattern)
- Backend: `public.crops` and `public.crop_varieties` seeded with the ~20 Egyptian crops
- Backend: `farm_scopes` table activation â€” assigning users to farms with roles
- Frontend: farm list, farm detail, farm create/edit pages
- Frontend: block list within a farm, block detail, block create/edit pages with MapLibre + draw control
- Frontend: AOI upload (GeoJSON, Shapefile, KML) â€” using `shp-write` / `shpjs` for shapefile parsing
- Frontend: crop assignment form
- Frontend: i18n strings for the `farms` namespace in `en` and `ar`
- Frontend: unit display (feddan / acre) consistently applied
- Backend: integration tests for the cross-schema FK consistency-check job

### Out of scope (must not build)
- Imagery, indices, alerts, recommendations (only the data model placeholders)
- Activity log entry forms (basic only â€” store free text + type + date + optional quantity)
- ML-based field detection
- Mobile offline app
- GPS perimeter walk for AOI definition

### Definition of done
1. A user with `TenantAdmin` role can create a farm via the UI; the farm appears on the list with correct area in feddan.
2. A user with `FarmManager` role on that farm can create a block by drawing on the map; the block stores correct WGS84 + UTM 36N geometries; area is computed correctly.
3. Crop assignment shows the Arabic crop name when language is set to `ar`.
4. RBAC is enforced: a `Viewer` cannot edit a block; a `FarmManager` on Farm A cannot edit blocks of Farm B.
5. `FarmCreated` event triggers an audit row.
6. Cross-tenant access is impossible: a SQL query attempted with the wrong `tenant_id` in JWT returns nothing.

---

## Prompt 3 â€” Slice 2: imagery and indices

**Goal:** real Sentinel Hub fetches, real NDVI computed for a real block, real time-series stored, real tiles displayed on the map.

### In scope
- Backend: `imagery` module â€” full implementation
  - `imagery_providers`, `imagery_products`, `imagery_aoi_subscriptions`, `imagery_ingestion_jobs` tables
  - `SentinelHubProvider` adapter implementing the `ImageryProvider` Protocol
  - pgstac integration: collection per tenantÃ—product, item registration on success
  - Celery tasks: discovery, acquisition, preprocessing, storage, index computation, aggregation
  - Idempotency via deterministic asset IDs
  - On-demand refresh endpoint
  - Scheduled polling via Celery Beat
- Backend: `indices` module â€” full implementation
  - `block_index_aggregates` hypertable with continuous aggregates (daily, weekly)
  - Index catalog (`indices_catalog`) seeded with the six standard indices
  - Aggregation logic (mean, p10, p90, std, valid_pixel_pct) implemented in Python with `rasterio` + `numpy`
- Tile server: real configuration to serve COGs from S3 by collection/item ID
- Frontend: NDVI/NDWI/EVI overlay on the block map via deck.gl raster layer
- Frontend: per-block index trend chart (Recharts) using the daily continuous aggregate
- Frontend: scene selector (date picker showing available scenes for a block)
- Frontend: i18n strings for the `imagery` and `indices` namespaces

### Out of scope (must not build)
- Self-managed Sentinel-2 pipeline (Sentinel Hub only)
- Planet, Airbus, premium imagery
- On-demand custom indices (only the six standard)
- Cloud-mask soft-mode
- Reprocessing of historical scenes

### Definition of done
1. A new block triggers an imagery ingestion within the next Celery Beat cycle (or via manual refresh button).
2. A real Sentinel Hub fetch produces a NDVI COG in S3 and a row in `block_index_aggregates`.
3. The frontend shows the NDVI overlay on the block map.
4. The trend chart shows the NDVI value over the last available scenes.
5. Re-running the same job produces no duplicates (idempotency works).
6. A scene above the cloud-cover threshold is correctly skipped with status `skipped_cloud`.

---

## Prompt 4 â€” Slice 3: alerts and recommendations

**Goal:** the reasoning engine works end-to-end. A real rule fires on real data, sends a real email and an in-app SSE update.

### In scope
- Backend: `_shared/conditions/` â€” full implementation of the condition language (data sources, operators, aggregations, evaluator)
- Backend: `alerts` module â€” full implementation
  - `alert_rules`, `alert_rule_scopes`, `alerts`, `alerts_history` tables
  - Pull-based evaluation every 15 minutes via Celery Beat
  - Lifecycle: open / acknowledged / snoozed / resolved / auto-resolved
  - Cooldown enforced by uniqueness constraint
- Backend: `recommendations` module â€” full implementation
  - `public.decision_trees`, `public.decision_tree_versions`, `recommendations`, `recommendations_history` tables
  - YAML loader for decision trees
  - Daily per-block evaluation
  - Tree path captured for explainability
- Backend: `notifications` module â€” full implementation
  - `public.notification_templates`, `notification_dispatches`, `in_app_inbox` tables
  - Email dispatch via SMTP
  - Webhook dispatch with HMAC signing
  - SSE channel for in-app delivery
- Backend: seed at least one decision tree YAML for citrus irrigation
- Frontend: alert rules list and editor (Tier 2 condition tree builder)
- Frontend: active alerts page with acknowledge / snooze / resolve actions
- Frontend: recommendations page with apply / dismiss / defer actions and tree-path display
- Frontend: in-app inbox (bell icon) backed by SSE + REST fallback
- Frontend: i18n strings for the `alerts`, `recommendations`, `notifications` namespaces

### Out of scope (must not build)
- SMS notifications
- ML-driven recommendations
- Tier 3 scripted rules
- Multi-step workflow recommendations (e.g., "if applied, schedule follow-up")
- Webhook retry queue with exponential backoff (basic single-attempt only)

### Definition of done
1. A user creates an alert rule for "NDVI below 0.4 for 7 days" on a specific farm.
2. Within 15 minutes after a real Sentinel Hub fetch produces a low NDVI value, the alert fires.
3. The user receives an email; the in-app inbox shows the alert in real-time via SSE.
4. The user acknowledges the alert; state transitions to `acknowledged`; an audit row is written.
5. A daily recommendation evaluation produces an irrigation recommendation for a block whose NDVI is dropping; the tree path is shown in the UI in both en and ar.
6. The cooldown constraint prevents a second open alert on the same scope while the first is still open.

---

## Prompt 5 â€” Slice 4: weather, signals, dashboards

**Goal:** the platform's full data picture comes together â€” weather forecasts feed alerts, custom signals fill gaps, and the native dashboard ties everything together.

### In scope
- Backend: `weather` module â€” full implementation
  - `weather_observations`, `weather_forecasts`, `weather_derived_daily` tables (hypertables for the first two)
  - `OpenMeteoProvider` adapter
  - Celery Beat schedules: hourly current, 6-hourly forecast, nightly derived signals
  - GDD, ETâ‚€, cumulative rainfall computation
- Backend: `signals` module â€” full implementation
  - `signal_definitions`, `signal_assignments`, `signal_observations` (hypertable) tables
  - REST endpoints for definition CRUD, observation entry, observation list
  - Photo attachment via S3 presigned URL
- Backend: extend `_shared/conditions/` data sources to include weather and signals (alerts and recs gain access automatically)
- Backend: `analytics` module â€” views and continuous aggregates per data model Â§ 14
- Frontend: weather forecast widget on farm and block pages
- Frontend: custom signal definition UI for tenant admins
- Frontend: signal observation entry form (with photo)
- Frontend: native dashboard per farm â€” combines NDVI trend, weather, alert count, recommendations, signal latest values
- Frontend: native dashboard per block â€” same but block-scoped
- Frontend: i18n strings for `weather`, `signals`, `analytics` namespaces

### Out of scope (must not build)
- IoT signal ingestion (machine-to-machine auth) â€” manual entry only
- Apache Superset
- Forecast accuracy retroactive analysis
- Chill hours derived signal

### Definition of done
1. Weather forecast for the next 5 days appears on every farm page and updates every 6 hours.
2. A tenant admin defines a custom "soil moisture" signal; a field operator logs an observation with a photo.
3. An alert rule using a combination of NDVI + weather forecast + soil moisture signal evaluates correctly and fires when all conditions are met.
4. The block dashboard shows: current crop, latest NDVI with trend, current weather, 5-day forecast, last 3 signal observations, count of open alerts.
5. The continuous aggregates (`block_index_daily`, `block_index_weekly`) populate correctly and the dashboard uses them (not the raw hypertable).

---

## Prompt 6 â€” Polish

**Goal:** make the platform shippable. This prompt is the cleanup and hardening pass.

### In scope
- **Internationalization completeness:** every user-visible string in en and ar; RTL bugs fixed across every page; numeral formatting per locale; date formatting per locale.
- **Performance:** N+1 query audit; index review; slow-query log review; frontend bundle size review; image optimization; tile-server caching headers.
- **Security:** OWASP Top 10 review; secret scanning; dependency vulnerability fix pass; rate-limiting verification; CORS verification; HTTPS-only cookie verification; CSP headers; input validation audit (especially geometry uploads).
- **Audit completeness:** every state-changing endpoint emits an audit event with proper subject_kind, subject_id, before/after where relevant.
- **Error handling:** every endpoint returns RFC 7807 problem+json with translated detail messages.
- **Backup/DR:** verify CloudNativePG PITR works; document restore procedure.
- **Runbooks:** `docs/runbooks/` for: tenant onboarding, tenant offboarding, imagery pipeline failure, alert evaluator stuck, Postgres failover, Keycloak reset.
- **End-to-end Playwright tests** covering: login, create farm, create block, upload AOI, create alert rule, acknowledge alert, apply recommendation, log signal â€” in both `en` and `ar`.
- **Visual regression tests** on the key dashboard screens in both locales.
- **README.md and onboarding docs** for new engineers.
- **Cost-control guardrails:** S3 lifecycle policies verified, Sentinel Hub usage alarms configured, CloudWatch budgets set.

### Out of scope (must not build)
- New features
- Refactoring of architecture
- Phase 2 items (still parked: forecasting, mobile, IoT, billing, etc.)

### Definition of done
1. Every page in the app works correctly in both `en` and `ar` with proper RTL.
2. Playwright suite passes in CI for both locales.
3. Security checklist signed off (OWASP Top 10 + dependency scan).
4. Restore-from-backup tested and documented.
5. The "first customer onboarding" runbook is followed end-to-end on the staging cluster successfully.
6. Bundle size for the frontend's main route under 500KB (gzipped).
7. p95 latency for the dashboard endpoint under 500ms with 10 farms Ã— 100 blocks of test data.

---

## How to use this roadmap

1. **Run Prompt 1** with Claude Code in a fresh session. Provide it with `prompts/prompt_01_foundation.md` as the user message, and ensure it has access to `docs/ARCHITECTURE.md` and `docs/data_model.md`.
2. **Validate Prompt 1's gate** before proceeding. Do *not* skip this â€” every shortcut here costs 10Ã— later.
3. **Refine Prompt 2** based on what Prompt 1 actually built. The architecture is fixed but the codebase shape may suggest tweaks.
4. **Repeat** for prompts 2â€“6.
5. **If a prompt's gate fails**, do not move on. Open issues, drive fixes, re-run gate. The whole approach depends on each layer being solid before the next is built.

---

*This is a discipline document. Skipping steps invalidates the approach.*
