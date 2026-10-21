# AgriPulse — Build Roadmap

This roadmap shows the six-prompt arc that built AgriPulse to MVP, plus the post-MVP tracks that follow it. Each prompt is a single Claude Code session that ends in a hard human-reviewed gate before the next prompt starts.

**Approach:** vertical slices through a horizontal foundation.
**Repo:** `msoliman1975/AgriPulse`
**Reference docs:** `docs/ARCHITECTURE.md` and `docs/data_model.md` are read at the start of every session.

---

## Overview

| # | Prompt | Goal | Duration | Gate signal |
|---|---|---|---|---|
| 1 | Foundation | Repo, infra, CI, auth, tenancy, observability | 3–5 days | Healthcheck endpoint authenticated; tenant created; CI green |
| 2 | Slice 1 — farm management | Farms, blocks, AOIs, crop assignments, basic frontend shell | 4–6 days | A user can create a farm and a block from the UI |
| 3 | Slice 2 — imagery and indices | Sentinel Hub adapter, ingestion pipeline, NDVI displayed on map | 5–7 days | A block shows real NDVI from a real Sentinel Hub fetch |
| 4 | Slice 3 — alerts and recommendations | Rule engine, decision trees, notifications | 5–7 days | A real alert fires from real data and emails a real user |
| 5 | Slice 4 — weather, signals, dashboards | Open-Meteo integration, custom signal entry, native dashboards | 4–6 days | The dashboard shows index trend, weather forecast, custom signals |
| 6 | Polish | i18n, RTL, audit, performance, hardening, runbooks | 4–6 days | Bilingual UI works end-to-end; security checklist complete |
| 7 | Product & engagement telemetry | Know how the product is actually used | 9–13 days | Five product questions answerable from the UI without hand-written SQL |
| 8 | Subscription, billing & self-serve trial | Tiers that are enforced, a price per enrolled feddan, and a front door | 12–16 days | A visitor provisions their own trial and reaches a signed-in tenant with no human in the loop |

**Total wall-clock:** ~5–7 weeks at single-engineer pace for prompts 1–6. The 6-week MVP target is achievable with disciplined scoping and parallel work on frontend/backend within prompts.

Prompts 1–6 are delivered. Prompts 7 and 8 are post-MVP tracks and follow the same gate discipline.

---

## Prompt 1 — Foundation

**Goal:** stand up the repository, the cluster bootstrap, the CI pipeline, the auth path, the tenant context, and the observability stack. **No business features yet.**

### In scope
- GitHub repo structure (`backend/`, `frontend/`, `tile-server/`, `infra/`, `docs/`, `prompts/`, `.github/`)
- Backend: FastAPI app skeleton with health endpoint, structured logging, OpenTelemetry, Prometheus metrics, error handling middleware, correlation-ID middleware
- Backend: SQLAlchemy + Alembic + tenant-aware session middleware (`SET LOCAL search_path`)
- Backend: Keycloak integration — JWT validation against JWKS, claim extraction, RBAC dependency
- Backend: capability-based RBAC (`capabilities.yaml`, `role_capabilities.yaml`, `@requires_capability` decorator)
- Backend: in-process event bus + Celery worker scaffolding (light + heavy queues, beat scheduler)
- Backend: `_shared/` skeleton (db, auth_utils, conditions stub, eventbus)
- Backend: `import-linter` config enforcing module-boundary contracts
- Backend: `tenancy` module — Tenant entity, TenantSubscription, TenantSettings, tenant-creation admin endpoint, tenant-schema bootstrap
- Backend: `iam` module — User entity, UserPreferences, TenantMembership, role-assignment tables, `/me` endpoint
- Backend: `audit` module — minimal `audit.record(event)` interface, `audit_events` hypertable
- Frontend: Vite + React + TypeScript scaffold, MapLibre, Recharts, Tailwind with RTL plugin
- Frontend: react-i18next setup with empty `en` and `ar` namespaces
- Frontend: OIDC login flow against Keycloak, JWT storage, axios interceptor
- Frontend: app shell with header, navigation stub, language toggle, unit toggle
- Frontend: `/me` page showing user info from backend
- Tile server: Dockerfile and minimal config (no real data yet — verify deployment topology)
- Infra: Helm charts for `api`, `workers`, `tile-server`, `frontend`, `keycloak`, plus a `shared` chart for ConfigMaps and Secrets
- Infra: ArgoCD ApplicationSet manifests for the three environments
- Infra: Terraform for VPC, EKS, KMS, S3 buckets, ECR (or Docker Hub) — minimal viable setup
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
10. `import-linter` runs in CI and passes (no cross-module imports yet, so this is trivial — but the contract is in place).

This is a **lot** for one prompt. It is intentional. Everything here is foundation that every subsequent prompt assumes works. We pay the upfront cost once.

---

## Prompt 2 — Slice 1: farm management

**Goal:** end-to-end farm and block management. By the end, a user can sign in, create a farm, draw block boundaries on a map, assign a crop, and see the list of their farms and blocks.

### In scope
- Backend: `farms` module — full implementation per data model
  - `farms`, `blocks`, `block_crops`, `farm_attachments`, `block_attachments` tables
  - PostGIS triggers for `boundary_utm`, `centroid`, `area_m2`, `aoi_hash`
  - REST endpoints: CRUD farm, CRUD block (including geometry), assign crop, list
  - Service Protocols and event definitions (`FarmCreated`, `BlockBoundaryUpdated`, etc.)
  - Grid-based auto-blocking (manual editing supported)
  - File upload to S3 for attachments (presigned URL pattern)
- Backend: `public.crops` and `public.crop_varieties` seeded with the ~20 Egyptian crops
- Backend: `farm_scopes` table activation — assigning users to farms with roles
- Frontend: farm list, farm detail, farm create/edit pages
- Frontend: block list within a farm, block detail, block create/edit pages with MapLibre + draw control
- Frontend: AOI upload (GeoJSON, Shapefile, KML) — using `shp-write` / `shpjs` for shapefile parsing
- Frontend: crop assignment form
- Frontend: i18n strings for the `farms` namespace in `en` and `ar`
- Frontend: unit display (feddan / acre) consistently applied
- Backend: integration tests for the cross-schema FK consistency-check job

### Out of scope (must not build)
- Imagery, indices, alerts, recommendations (only the data model placeholders)
- Activity log entry forms (basic only — store free text + type + date + optional quantity)
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

## Prompt 3 — Slice 2: imagery and indices

**Goal:** real Sentinel Hub fetches, real NDVI computed for a real block, real time-series stored, real tiles displayed on the map.

### In scope
- Backend: `imagery` module — full implementation
  - `imagery_providers`, `imagery_products`, `imagery_aoi_subscriptions`, `imagery_ingestion_jobs` tables
  - `SentinelHubProvider` adapter implementing the `ImageryProvider` Protocol
  - pgstac integration: collection per tenant×product, item registration on success
  - Celery tasks: discovery, acquisition, preprocessing, storage, index computation, aggregation
  - Idempotency via deterministic asset IDs
  - On-demand refresh endpoint
  - Scheduled polling via Celery Beat
- Backend: `indices` module — full implementation
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

## Prompt 4 — Slice 3: alerts and recommendations

**Goal:** the reasoning engine works end-to-end. A real rule fires on real data, sends a real email and an in-app SSE update.

### In scope
- Backend: `_shared/conditions/` — full implementation of the condition language (data sources, operators, aggregations, evaluator)
- Backend: `alerts` module — full implementation
  - `alert_rules`, `alert_rule_scopes`, `alerts`, `alerts_history` tables
  - Pull-based evaluation every 15 minutes via Celery Beat
  - Lifecycle: open / acknowledged / snoozed / resolved / auto-resolved
  - Cooldown enforced by uniqueness constraint
- Backend: `recommendations` module — full implementation
  - `public.decision_trees`, `public.decision_tree_versions`, `recommendations`, `recommendations_history` tables
  - YAML loader for decision trees
  - Daily per-block evaluation
  - Tree path captured for explainability
- Backend: `notifications` module — full implementation
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

## Prompt 5 — Slice 4: weather, signals, dashboards

**Goal:** the platform's full data picture comes together — weather forecasts feed alerts, custom signals fill gaps, and the native dashboard ties everything together.

### In scope
- Backend: `weather` module — full implementation
  - `weather_observations`, `weather_forecasts`, `weather_derived_daily` tables (hypertables for the first two)
  - `OpenMeteoProvider` adapter
  - Celery Beat schedules: hourly current, 6-hourly forecast, nightly derived signals
  - GDD, ET₀, cumulative rainfall computation
- Backend: `signals` module — full implementation
  - `signal_definitions`, `signal_assignments`, `signal_observations` (hypertable) tables
  - REST endpoints for definition CRUD, observation entry, observation list
  - Photo attachment via S3 presigned URL
- Backend: extend `_shared/conditions/` data sources to include weather and signals (alerts and recs gain access automatically)
- Backend: `analytics` module — views and continuous aggregates per data model § 14
  - *Delivered differently.* The aggregates and views shipped inside the modules owning their source tables (`block_index_daily` / `block_index_weekly` in `indices`, `weather_hourly` in `weather`, `v_active_alerts` / `v_farm_integration_health` in `alerts` / `integrations_health`). `app/modules/analytics/` is still an empty placeholder. It is **not** the home for product telemetry — see Prompt 7.
- Frontend: weather forecast widget on farm and block pages
- Frontend: custom signal definition UI for tenant admins
- Frontend: signal observation entry form (with photo)
- Frontend: native dashboard per farm — combines NDVI trend, weather, alert count, recommendations, signal latest values
- Frontend: native dashboard per block — same but block-scoped
- Frontend: i18n strings for `weather`, `signals`, `analytics` namespaces

### Out of scope (must not build)
- IoT signal ingestion (machine-to-machine auth) — manual entry only
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

## Prompt 6 — Polish

**Goal:** make the platform shippable. This prompt is the cleanup and hardening pass.

### In scope
- **Internationalization completeness:** every user-visible string in en and ar; RTL bugs fixed across every page; numeral formatting per locale; date formatting per locale.
- **Performance:** N+1 query audit; index review; slow-query log review; frontend bundle size review; image optimization; tile-server caching headers.
- **Security:** OWASP Top 10 review; secret scanning; dependency vulnerability fix pass; rate-limiting verification; CORS verification; HTTPS-only cookie verification; CSP headers; input validation audit (especially geometry uploads).
- **Audit completeness:** every state-changing endpoint emits an audit event with proper subject_kind, subject_id, before/after where relevant.
- **Error handling:** every endpoint returns RFC 7807 problem+json with translated detail messages.
- **Backup/DR:** verify CloudNativePG PITR works; document restore procedure.
- **Runbooks:** `docs/runbooks/` for: tenant onboarding, tenant offboarding, imagery pipeline failure, alert evaluator stuck, Postgres failover, Keycloak reset.
- **End-to-end Playwright tests** covering: login, create farm, create block, upload AOI, create alert rule, acknowledge alert, apply recommendation, log signal — in both `en` and `ar`.
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
7. p95 latency for the dashboard endpoint under 500ms with 10 farms × 100 blocks of test data.

---

## Prompt 7 — Product & engagement telemetry

**Goal:** stop guessing. Know which capabilities are used, where users spend their time, which flows they abandon, and where they hit friction — from first-party data we own.

**Full plan:** `docs/proposals/product-telemetry-plan.md`. That document is authoritative for schema, event taxonomy, and PR sequencing; this section is the gate contract.

### Scope decisions (locked — do not re-litigate)
1. **First-party on the existing TimescaleDB.** No PostHog, no SaaS, no second node. Customer usage data does not leave the cluster.
2. **Internal consumer only.** One platform-admin surface. No tenant-facing usage API in this prompt.
3. **Full identity** on every event — `user_id` + `tenant_id` + role — so per-role funnels and retention are possible.
4. **"Struggle" is derived**, not recorded. No session replay, no rage-click SDK, no third-party script.
5. **Telemetry does not survive a tenant purge.** No archive row, no summary, no exemption. Accepted cost: a churn post-mortem has to be taken while the tenant is still live.

### In scope
- Backend: **new `telemetry` module** (`app/modules/telemetry/`) — *not* `analytics`, which `data_model.md § 14` reserves for agronomic aggregates
  - `public.usage_events` hypertable (migration `public/0049`), compression @14d, retention @180d
  - Closed event vocabulary in `taxonomy.yaml` — 10 event names, ~20 features, 4 tracked flows — generated into both a Python enum and a TS union so they cannot drift
  - `POST /api/v1/telemetry/events` — batched, always `202`, identity stamped server-side from `RequestContext`, `props` keys allow-listed, rate-limited
  - `usage_daily` + `usage_flow_daily` continuous aggregates, kept 24 months
  - Purge registry entries for `(usage_events, tenant_id)` and `(usage_events, farm_id)` — CI's orphan guard fails without them
  - **Purge-completeness work in `shared/purge/`**: a `PUBLIC_CAGGS` tuple and a `public`-schema continuous-aggregate refresh phase on the tenant path. The existing `BLOCK_CAGGS` machinery is block- and tenant-schema-scoped, and the tenant path has no CAGG phase at all — so without this the aggregates keep serving a purged tenant's numbers. Includes a test that purges a tenant whose events predate the 14-day compression threshold
  - New `"telemetry internals are private"` import-linter contract; telemetry is a leaf, no domain module may import it
  - New capability `platform.read_usage` in `capabilities.yaml`
- Frontend: `src/telemetry/` SDK — queue with hard cap, batching, unload-safe transport, session lifecycle, route-template resolution with a manifest drift test
- Frontend: automatic `page_view` / `page_leave` with **visibility-aware dwell** (backgrounded tabs excluded, 30-minute cap)
- Frontend: `api_error` capture inside the existing `apiClient` interceptor, reusing the `x-correlation-id` it already reads
- Frontend: **`<AppErrorBoundary>` — new**; no error boundary exists in the codebase today, so uncaught render errors currently white-screen with no signal
- Frontend: `app_version` via a vite `define`, so a behaviour change can be attributed to a deploy
- Frontend: ~25 curated `feature_used` calls and 4 instrumented flows
- Frontend: `/platform/usage` dashboard — engagement KPIs, time-per-surface, capability adoption, funnels, struggle board, tenant health. DS-1..DS-11 components, en + ar
- Ops: Grafana read-only Postgres datasource for ad-hoc exploration (**gated** — the `observability-*` ArgoCD apps still carry AWS-era `gp3` / `*.agripulse.local` values and must be verified healthy first)
- Docs: `docs/reference/telemetry.md` — every event, every field, every prop, and the retention policy

### Out of scope (must not build)
- DOM session replay (OpenReplay too heavy for one node; Clarity would ship customer screens to Microsoft)
- Any third-party analytics SaaS or forwarder
- Tenant-facing usage surface (needs small-N suppression and a DPA change)
- Rage-click / dead-click / Web Vitals instrumentation
- Archive-before-purge (`usage_tenant_summary`) — rejected by scope decision 5, not deferred
- Retention and cohort engine, feature flags, experiments
- Server-side request-level capture middleware
- Pre-authentication events (the login funnel)
- In-app surveys or qualitative feedback

All of the above are Phase B in the plan document, ordered by value-per-effort.

### Definition of done (the gate)
1. Without hand-writing SQL, the platform surface answers: distinct weekly users by tenant and role; the five surfaces absorbing the most user time with median visit length; capabilities unused by any tenant in 30 days; the `farm_onboarding` completion rate and the step that kills the rest; the route with the highest error-per-view rate, with a recent `correlation_id` traceable to a server log line.
2. `is_platform_staff = true` traffic is excluded from every default chart.
3. A client posting a forged `user_id` or `tenant_id` has it discarded; the server value wins.
4. The kill switch off (either end) leaves the app fully functional and writes zero rows.
5. A telemetry endpoint that 500s or times out is invisible to the user — no retry storm, no console noise, no broken render.
6. `props` containing an unknown key is stored without that key. No agronomic or customer content is reachable in `usage_events`.
7. Dwell excludes backgrounded time; no `page_leave` row exceeds 30 minutes.
8. Purging a tenant leaves zero rows attributable to it in `usage_events` **and in both continuous aggregates**, including for a tenant whose events predate the compression threshold. The orphan scanner reporting zero is the proof.
9. `ruff`, `mypy`, `tsc -b`, `eslint`, `import-linter`, and the purge orphan guard all pass.
10. `docs/reference/telemetry.md` matches the shipped taxonomy exactly.

### Known traps (repo-specific)
- **Bind real `datetime` / `UUID` objects, never `.isoformat()` strings through a `CAST`.** This family caused #331, #332 and #335. A 50-row batch insert of timestamps is a textbook place to reintroduce it. The integration test must run against real asyncpg and must not be `skip`ped — 5 of 6 backfill tests were skipped, which is why #331 shipped broken.
- The rolling CAGG refresh policy is correct here **only because events always arrive at `now`**. Never bulk-import historical events without an explicit `refresh_continuous_aggregate` over the range — that was #336.
- Do not run `prettier --write` over a broad glob; `main` carries formatting drift. Format only touched files.
- `OwnedTable(hypertable=True)` in the purge registry is **documentation only** — `shared/purge/engine.py` never reads the flag. Setting it buys no behaviour; the CAGG refresh phase above is what actually makes a hypertable purge complete.

### Open questions (answer before TEL-1)
- Is the pre-auth login funnel in scope now or Phase B?
- Unload transport: `fetch(keepalive: true)` (keeps the auth header) or `sendBeacon` (more reliable, needs a token in the URL)?
- New `platform.read_usage` capability, or fold into the existing `platform.read`?

---

## Prompt 8 — Subscription, billing & the self-serve trial

**Goal:** make a tier mean something, put a price on enrolled area, and let a website visitor provision their own trial without a human in the loop.

**Full plan:** `docs/proposals/subscription-billing-and-self-serve-trial.md`. That document is authoritative for the pricing formula, the schema, and the flow; this section is the gate contract.

### Scope decisions (locked — do not re-litigate)
1. **Free is a time-limited trial**, not a permanent tier. A platform admin can extend it, audited, with a reason. At the end the tenant goes **read-only** — sign-in and reads work, writes and background jobs stop.
2. **One dollar rate per feddan per crop**, plus a default rate. Not a multiplier on a base rate, and not a rate per crop *group*.
3. **A published price list is immutable.** A term pins the version for a year. Changing a rate means publishing a new version. Editing in place would rewrite bills already invoiced.
4. **A block's billing crop is pinned** the first time the block enters the meter and holds until renewal. Area is *not* pinned — adding blocks still moves the invoice.
5. **The contract belongs to the tenant**, not the farm. One term, one meter, one invoice.
6. **Every rate and threshold is editable in the interface.** No number in `settings.py`, in a Python constant, or in a frontend constant.
7. **`PlatformAdmin` keeps pricing access through its wildcard.** No deny list is added to `CapabilityRegistry` — it could grant itself the role anyway. The control is the audit trail.
8. **Nothing is provisioned from an unverified email address.**

### In scope
- Backend: **new `billing` module** (`app/modules/billing/`) — never the word "subscription" inside it; `ImageryAoiSubscription` and `WeatherSubscription` already own that noun
  - `billing_price_lists`, `billing_crop_rates` (FK `public.crops`), `billing_discount_bands` — a versioned, immutable rate card
  - `billing_block_crop_pins` — the crop lock; `block_id` and `farm_id` are **logical UUIDs with no foreign key**
  - `billing_meter_readings` — append-only, the evidence behind every invoice
  - `billing_invoices` + `billing_invoice_lines`, `billing_entitlements`
  - New columns on `public.tenant_subscriptions`: `price_list_id`, `base_fee`, `minimum_units`, `minimum_rate`, `committed_units`, `discount_pct`, `included_seats`, `seat_price`, `billing_period`, `currency`. Each row already behaves like a term — reuse it, do not add a rival table
  - Monthly meter task: per tenant, per active block, from the **pinned** crop and the **pinned** price list. Never reads `block_crops` for pricing
  - Six new platform capabilities: `platform.pricing.{read,manage,publish}`, `platform.subscription.manage`, `platform.trial.{read,manage}`
  - New platform role **`PlatformBillingAdmin`** — see the eight registration points in § 11.3 of the plan
- Backend: **entitlement enforcement wired into the existing `requires_capability`.** No tier is enforced anywhere today; `feature_flags` is stored, displayed, and read by nothing
- Backend: **a public, unauthenticated route surface** — the first in the API. `POST /api/v1/public/trial/signups`, `GET /api/v1/public/trial/verify`, `GET /api/v1/public/trial/status/{handle}`. Own rate limiting, Cloudflare Turnstile, excluded from the tenant-context middleware because at that point there is no tenant
- Backend: `public.trial_signups` and the provisioning Celery task — slug generation with a collision suffix, `create_tenant(initial_tier="free")`, trial dates from the published price list, and **success reported only on `keycloak_provisioning == "succeeded"`**
- Backend: four email templates — verify address, set password, trial ending (D−7, D−1), trial ended
- Frontend: `/platform/pricing` (crop rates, bands, draft/publish, version history with a difference view), `/platform/trials` (the signup queue), tenant subscription panel with extend-trial, platform meter viewer
- Frontend: the customer's own billing page — plan, live meter, invoices — behind `subscription.read`
- Marketing site: the trial form, posting to the public endpoint with a Turnstile token
- Infra: Turnstile secret in the `shared` chart
- Docs: `docs/reference/billing.md` — the formula, every variable, and the meter rule

### Out of scope (must not build)
- Payment collection, card capture, a payment provider, dunning
- Multi-currency price lists (one US dollar list for the first release)
- Tax, VAT registration, or invoice numbering for a tax authority
- Farm-level contracts and third-party payers (bank, exporter, aggregator) — the plan's § 7 second-buyer models
- Per-crop *band* schedules; volume discount is a percentage on the whole bill
- Self-service upgrade from trial to paid without a human — sales closes the first cohort
- A deny list in `CapabilityRegistry` (scope decision 7 rejects it, it is not deferred)
- Dropping `premium` from the tier enum, or `price_per_feddan` from the table — both stay one release

### Definition of done (the gate)
1. A visitor on the marketing site who has never spoken to anyone reaches a working, signed-in tenant with their own farm drawn, and every step is visible as a row in `trial_signups`.
2. A signup whose Keycloak provisioning returns `pending` **never** shows the visitor a success page. It retries, and raises a platform alert after N attempts.
3. Posting the same email twice, or an email whose domain belongs to an active tenant, creates **no** second tenant, and the response body is identical either way.
4. A platform admin without `PlatformBillingAdmin` or the wildcard cannot open `/platform/pricing`, and the route returns 403 with the capability named.
5. Publishing a new price list does not change the total on any existing term. Proven by an invoice generated before and after, from the same meter readings.
6. A block that changes crop mid-term bills at its pinned rate until renewal, and re-pins at renewal.
7. A tenant at `A_free` + 1 feddan cannot add another block, and the message names the limit rather than failing generically.
8. At `trial_end` the tenant can sign in and read, and every write route returns 403. Imagery, weather and decision-tree jobs write nothing for it.
9. An invoice line traces to the meter readings behind it, in the interface, without hand-written SQL.
10. Every rate, cap, band and trial length is changed through the interface only. Grepping the shipped image for a hard-coded price finds nothing.
11. Publishing a price list, extending a trial, and setting a negotiated discount each appear in the audit log with the actor, both values, and the typed reason.
12. `ruff`, `mypy`, `tsc -b --force`, `eslint`, `import-linter`, and the purge orphan guard all pass.

### Known traps (repo-specific)
- **The role allow-list exists in seven places across two backend files** — `admins_service.py:113` *and* `:306`, plus five `Literal[...]` annotations in `admins_router.py`. Grep for every copy before editing one. `frontend/src/rbac/capabilities.ts` is a hand-maintained mirror with no test that fails on drift.
- **Keycloak provisioning returns 201 with `keycloak_provisioning: "pending"` and no error.** This already shipped broken on the invite path. On a self-serve signup it is fatal: the visitor is told to check an email that never arrives.
- **Never FK from `public` into a tenant schema.** `billing_block_crop_pins` holds logical UUIDs.
- **The meter loops tenants**, so each iteration needs its own SAVEPOINT or one bad tenant kills the run. Integration tests must assert `current_schema()` at the point of use — a test's own `commit()` unscopes the next read and it returns an empty list with no error.
- **Bind real `date` and `UUID` objects, never `.isoformat()` strings through a `CAST`.** Meter readings and invoice periods are exactly where this family reappears.
- **Store two dunum constants.** Iraq is 2,500 m², the Levant and Gulf are 1,000 m². One shared constant bills Iraqi customers 2.5× wrong.
- Take the next free `public` migration number **at PR time, not at design time**. Two files at one revision merge clean and then break `upgrade head` in the cluster.
- New tenant-scoped tables must join the purge manifest or CI fails.

### Open questions (answer before BILL-1)
- Which features are in the trial basic set — is a trial the full product for a short time, or a small product?
- Auto-provision on email verification, or hold every signup for platform review?
- Free-mail addresses: allow, hold, or reject?
- Does a trial start with a seeded demo farm, or empty?
- Does a block with no crop bill at the default rate or at zero?
- How long does read-only last before archive and purge, and does reactivation backfill the gap?

---

## How to use this roadmap

1. **Run Prompt 1** with Claude Code in a fresh session. Provide it with `prompts/prompt_01_foundation.md` as the user message, and ensure it has access to `docs/ARCHITECTURE.md` and `docs/data_model.md`.
2. **Validate Prompt 1's gate** before proceeding. Do *not* skip this — every shortcut here costs 10× later.
3. **Refine Prompt 2** based on what Prompt 1 actually built. The architecture is fixed but the codebase shape may suggest tweaks.
4. **Repeat** for prompts 2–6.
5. **If a prompt's gate fails**, do not move on. Open issues, drive fixes, re-run gate. The whole approach depends on each layer being solid before the next is built.

Prompts 1–6 are delivered; they remain here as the record of what was built and why. **Post-MVP tracks start at Prompt 7** and keep the same contract: a locked scope, an explicit out-of-scope list, and a gate that is a set of answerable questions rather than a set of merged PRs. Each has a detailed plan under `docs/proposals/`; this file carries only the scope and the gate.

---

## Housekeeping backlog

Small, bounded cleanups that fall out of shipped work. Deliberately **not**
prompts: they carry no gate and no locked scope, and inventing a slice for a
two-line deletion would cheapen the contract above. The rule is that an item
here rides along with the next PR that already touches the same area — a
cleanup that needs its own build, review and promote cycle is not a cleanup.

An item earns a line here only if it is (a) already understood, (b) safe, and
(c) currently costing nothing. Anything failing (c) is a bug and belongs in an
issue instead.

| Item | Where | Why it's safe | Ride along with |
|---|---|---|---|
| Delete orphaned `expectedHarvestStart` / `expectedHarvestEnd` keys | `frontend/src/i18n/locales/{en,ar}/farms.json` | Orphaned by #383, which dropped the matching `block_crops` columns in migration 0061. **No component references either key** — nothing renders a broken value; they are dead weight, not a defect. | Any frontend PR touching the farms namespace |

---

*This is a discipline document. Skipping steps invalidates the approach.*
