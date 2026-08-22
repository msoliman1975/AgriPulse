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

**Total wall-clock:** ~5–7 weeks at single-engineer pace for prompts 1–6. The 6-week MVP target is achievable with disciplined scoping and parallel work on frontend/backend within prompts.

Prompts 1–6 are delivered. Prompt 7 is the first post-MVP track and follows the same gate discipline.

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

## Prompt 8 — Agronomic depth: the Egyptian organic mango ruleset

**Goal:** make a real agronomic manual expressible as configuration. `docs/MangoManual_Final.pdf`
(AgriPulse Organic Mango Manual v2.0, 27pp, Arabic — Keitt / Sukkary / Zebda / Yasmina / Crimson)
is the forcing function: it is the first document that specifies a whole crop year in enough
detail to show where the decision-tree vocabulary runs out.

**Source analysis:** the mapping, the manual review, and this register were produced in the
2026-08-10 session. Nothing else in `docs/proposals/` covers it — do not go looking for a
plan document that was never written.

### What the manual costs us to implement

Twenty-eight tree-shaped rules were extracted. **Nine are authorable today with no platform
change** (six already ship — the powdery-mildew, anthracnose, fruit-fly, stress-induction,
canopy-health and post-harvest-nitrogen trees). **Nine more need only a signal definition.**
**Ten are blocked on the gaps below.**

### Scope decisions (locked — do not re-litigate)

1. **§4 (the two weekly plans) is plan-template work, not decision-tree work.** Activities
   anchor to a phenology stage with an `offset_days`; that is what
   `plan_template_activities.anchor = 'stage'` already models.
2. **The manual's week numbers are discarded on transcription.** They are internally
   inconsistent — §4.1's own month labels put week 1 in late October, which makes its
   "week 31 = Sukkary harvest" fall in late May against §3.6's 10 July. The Keitt plan drifts
   ~4 months by week 37, and neither plan closes the year (34 and 40 weeks for a 52-week
   cycle). The month labels agree with §3.6 and are the survivors.
3. **No calendar condition source will be added** (see G-1). §4.1's own warning that dates
   shift 7–14 days between governorates is the argument against calendar-driven rules.
4. **Risk-model coefficients stay named module constants**, tunable without touching logic —
   the existing contract in `weather/risk/models.py`. Recalibration is a constant edit, never
   a rewrite.
5. **Three manual defects are the author's to resolve, not ours to guess:** the minimum
   harvest TSS equals the Grade A export threshold (making Grade B unreachable); Keitt's
   varietal 15–18 °Brix versus its ≥11 °Brix picking gate; and the ambiguous TSS/TA ratio.
   The five harvest-window trees are blocked on answers, not on engineering.

### Gap register

Fourteen platform gaps between the manual and a working configuration. G-1..G-4 are
structural; the rest are additive. "Evidence" is why it is a gap, not merely a wish.

| ID | Gap | Evidence — why it's a gap | Manual ref | Blocks |
|---|---|---|---|---|
| **G-1** | A tree cannot read the date | The `ValueRef` union is nine closed sources (`shared/conditions/models.py:212`) and `parse_value_ref` raises on anything else (`:307`). None is a calendar. The only time proxy is `block.growth_stage`, itself six-stage granular. | §3, §4 | The whole 40-week plan — **by design**; route to plan templates |
| **G-2** | No elapsed-time or stage-relative refs | `BLOCK_FIELDS` is `growth_stage / soil_texture / salinity_class` only (`models.py:53`). `CROP_ATTRIBUTE_KEYS = ("value",)` with a `days_since` placeholder documented but unbuilt (`context.py:142`). `block_crops.growth_stage_updated_at` is stored (`tenant/0002:378`) and unreadable from a condition. | §3.1, §3.5, §6 | Stop N 4–6 wk pre-harvest; deficit irrigation last 4 wk (the +1.5–2.5 °Brix lever); prune within 2 wk of harvest |
| **G-3** | Mango phenology fits Keitt and nothing else | Only Keitt carries `phenology_stages_override` (`public/0033:106`); Sukkary, Zebda, Yasmina and Crimson inherit the generic cycle whose `post_harvest_flush` runs 07-16→10-31 (`:63`) — so the platform believes Yasmina (harvest 1 Aug–15 Sep) and Crimson (10 Aug–20 Sep) are in post-harvest flush during fruit development. No `harvest` stage exists: seven manual phases compress to six and harvest is the one that disappears. Perennials are locked to `calendar_doy \| manual` (`farms/phenology.py:35`), so GDD cannot rescue it. | §3.6, §1 | Every stage-gated mango rule, for 4 of 5 varieties |
| **G-4** | No duration, run-length or accumulation operators | `WEATHER_SCOPES` gives two single days plus forecast windows (`context.py:179`); the only rolling fields are `precip_mm_7d` / `precip_mm_30d` (`weather/derivations.py:9`). No chill units, no consecutive-day counter, no "how long has this been true". | §3.2, §4.1 wk 11–12 | "Stress 3–6 wk, alarm past 6"; "4 weeks of nights below 18 °C" — the two rules that decide whether the crop flowers at all |
| **G-5** | 3 pathogen models against the manual's 11 | `RISK_MODELS` holds `powdery_mildew`, `anthracnose`, `fruit_fly` (`weather/risk/registry.py:42`). The manual documents 5 diseases and 5 pests. Adding one is a Python function plus a registry entry — a deploy, not config. | §5.1, §5.2 | Bacterial black spot, scab |
| **G-6** | No count-based pest signals | Every §5.1 threshold is a count per unit (3 flies/trap/day, 5 mealybugs/branch, 10 scales/cm², 10 mites/leaf, 1 bore hole, 0.5% fruit). The platform catalog has 9 definitions and exactly one pest measure, `pest_incidence_pct` — a percentage expresses none of them (`public/0053:51`). | §5.1 | 6 pest-threshold rules |
| **G-7** | No fruit-quality or lab signals | TSS, TA, firmness, density and blush carry all of §3.6 and §7; none is platform-curated (`public/0053`). Tenants can author them, but the tree validator checks `crop_attribute` refs (`recommendations/loader.py`, `_assert_crop_attribute_refs_resolve`) and **does not check signal codes at all** — a mistyped code fails closed silently at every evaluation, forever. | §3.6, §7 | 5 harvest-window trees; the export-grade gate |
| **G-8** | Action vocabulary doesn't cover mango operations | 8 values in `ActionType` (`recommendations/schemas.py:12`) and the matching CHECK (`tenant/0015:125`). Thinning, bagging, whitewashing, hive placement and harvest all collapse to `other` — which is also what the Action Center groups by. **Already drifted:** `action_type: inspect` ships in `ndvi_baseline_alert_v1.yaml:97,115` and `date_palm_ripening_rain_risk_v1.yaml:246` and is not one of the 8; it survives only because those leaves are `kind: alert` and `alerts.action_type` was added with no CHECK (`tenant/0063:55`). A recommendation leaf using it is rejected at insert. | §3.4, §3.3, §3.6 | Correct grouping in the Action Center; 4 operation types |
| **G-9** | No organic-input catalog, no certification model | There is no `inputs`, `products` or `certification` module under `app/modules/`. §2.2's 12 permitted inputs with doses and §2.1's certification state (conversion period, certifier, buffer zone, inspection) have nowhere to live. Consequently nothing can verify a recommended input is permitted, and **nothing can total season copper** — the manual prescribes Bordeaux and copper sulphate with no annual budget against the 4 kg Cu/ha/yr cap, which is a certification-loss risk. | §2.1, §2.2, §5.2 | Organic-compliance guarantees of any kind |
| **G-10** | A tree cannot emit a repeating series | `uq_recommendations_block_tree_open` allows one open recommendation per (block, tree) (`tenant/0015:141`). `valid_for_hours` expires a row; nothing re-fires it. | §3.3, §3.4, §6 | "Sulphur every 10 days", "Ca+B every 10 days", weekly neem/seaweed — **route to plan templates** |
| **G-11** | Parameter overrides are tenant-scoped, not variety-scoped | Overrides key on (tenant, tree, parameter) — `/decision-trees/{code}/parameter-overrides/{param_name}`, resolved in `recommendations/engine.py:81`. Any per-variety threshold needs one near-duplicate tree per variety. | §3.6, §3.4 | 5 harvest gates + 2 thinning rates become 7 trees instead of 2 |
| **G-12** | Canopy size and planting density stored but unreadable | `block_crops` carries `plant_density_per_ha` / `row_spacing_m` / `plant_spacing_m` (`tenant/0002:374`) and the catalog seeds mango size classes incl. `very_large` for Sukkary/Zebda (`public/0033:96`). Neither is in `BLOCK_FIELDS`; `canopy_size_class` was deliberately removed in the condition-source audit (#388–#392), on relevance grounds that predate dose arithmetic. | §3.1, §6 | Per-tree doses (20–30 kg compost/tree, 500–700 g bone meal/tree) cannot be converted to a block instruction |
| **G-13** | No cross-rule conflict detection | Trees evaluate independently per block (`recommendations/service.py`, `evaluate_block`); there is no pass over the resulting set. §3.3 asks for 2–3 hives/feddan in the same window as wettable sulphur and Bordeaux at 200 g/100 L. The manual mitigates by evening spraying; the platform cannot see the collision. | §3.3 | Bee safety; any "these two actions conflict" guarantee |
| **G-14** | Doses are untyped free text | `recommendations.parameters` is unvalidated JSONB (`recommendations/models.py`); `_substitute_params_in_outcome_params` (`engine.py:107`) resolves refs to literals and stops there. "250–300 g/100 L every 10 days" enters as a string — not convertible to a block total, not checkable against a permitted range, not accumulable across a season. | §2.2, §6 | Falls out of G-9 |

### In scope

- **Data-only, no code** — G-3: author `phenology_stages_override` for Sukkary, Zebda, Yasmina
  and Crimson from the §3.6 harvest calendar, plus a seventh `harvest` stage. The
  `/platform/catalog` console (#410, prod `fb6981b`) already makes every one of these fields
  authorable at each taxonomy level, so this is data entry, not a migration.
- **Config-only** — G-6, G-7: seed 6 pest-count and 5 fruit-quality signal definitions at
  platform scope, plus a `scout_mango_pest_v1` and `scout_harvest_readiness_v1` template.
  Unblocks 15 rules and is the best effort-to-value item here.
- **Recalibration** — the shipped powdery-mildew and anthracnose models against the manual's
  bands. Anthracnose disagrees by six degrees (manual 18–26 °C, model 24–30 °C) and the manual
  is the better fit for a February–March Egyptian flowering window. Keep the model's
  rain-suppression term for powdery mildew: §5.2 omits the mechanism, and CABI is right.
- **Vocabulary** — G-8: add `thin`, `protect`, `pollinate`, `harvest`; fold `inspect` into
  `scout`. One CHECK migration and one `Literal` union, in lock-step.
- **Condition sources** — G-2 (`days_in_stage` on `block`, `days_since` key on
  `crop_attribute`) and G-12 (`plant_density_per_ha`, `canopy_size_class` on `block`). All
  four are additive to closed vocabularies and migrate no stored condition.
- **Validator** — extend the tree validator to check signal codes the way it already checks
  crop-attribute codes (G-7).
- **Plan templates** — §4.1 and §4.2 as two stage-anchored templates, week numbers discarded.

### Out of scope (must not build)

- A calendar / day-of-year condition source (scope decision 3, and G-1 is a routing decision
  rather than a defect)
- The organic-input catalog and applied-dose ledger (G-9, G-14) — the largest item here and
  its own track; it is what would make AgriPulse useful to a certified grower rather than
  merely compatible with one
- Cross-rule conflict detection (G-13) — belongs in the Action Center, which already groups
  by block and due date
- Per-variety parameter overrides (G-11) — accept 7 trees; revisit only if a third axis of
  variation appears
- A data-driven risk-model DSL (G-5) — add the two missing pathogens as functions first and
  see whether the shape really is regular
- Alternate-bearing management for Sukkary and Zebda — the manual diagnoses it in §1.2, cites
  El-Shaer 2019, and then never returns to it. There is no rule to implement until the manual
  has one.

### Definition of done (the gate)

1. A mango block of each of the five varieties resolves the correct phenology stage on the
   day its §3.6 harvest window opens. Today four of five resolve `post_harvest_flush`.
2. All nine "ready" rules and all nine "needs a signal" rules exist as published trees, and
   `:dry-run` against a real block returns the expected leaf for each.
3. A tree referencing a misspelled signal code is rejected at authoring time, not silently at
   every evaluation.
4. `action_type: inspect` no longer appears in any seed, and the CHECK constraint and the
   `ActionType` union list the same values.
5. Both weekly plans exist as plan templates whose activities anchor to stages; no activity
   carries a transcribed week number.
6. A recommendation carrying a per-tree dose states the block total, derived from
   `plant_density_per_ha` and block area.
7. `ruff`, `mypy`, `tsc -b`, `eslint`, `import-linter` and the purge orphan guard all pass.

### Known traps (repo-specific)

- **Every new tenant table joins the purge manifest or CI fails.** Nothing here should need
  one, but the signal seeds land in `public` — check before assuming.
- **Seed YAML compiles at startup.** A malformed seed raises `DecisionTreeParseError` in
  `_lifespan`, so a bad file does not fail a test, it fails the pod. Compile locally first.
- Conditions are permissive on missing data: a null reference short-circuits the comparison to
  false and takes `on_miss`. Order branches so the fail-closed path is the safe one, never the
  one that dispatches a spray.
- The manual's §7 grade thresholds and §3.6 maturity minimums are the same numbers. Do not
  encode either until scope decision 5 is answered.

### Open questions (answer before the first PR)

- Who owns resolving the three manual defects in scope decision 5 — us or the manual's author?
- Do the copper cap and the EU-equivalence framing in §2.1 need a certifier's sign-off before
  the manual is issued to growers? (§2.1 attributes an ≥8 m buffer zone and a 2006 Egyptian
  instrument to EU 848/2018, which contains neither.)
- Is `harvest` a real seventh phenology stage, or a derived window from the variety's
  `default_thresholds`?

---

## Prompt 9 — Tenant and farm defaults

**Goal:** make the defaults surfaces tell the truth, and make a new farm arrive already
configured. Today Platform Admin → Tenant details → Integrations accepts values that no
runtime code reads, and `create_farm` writes a farm row and nothing else.

**Source analysis:** the audit below was produced in the 2026-08-21 session by reading
`origin/main`. It extends the 2026-07-29 audit (PR #334, migration `public/0048`), which
dropped eight keys that nothing read. Nothing in `docs/proposals/` covers this — do not go
looking for a plan document that was never written.

### What the audit found

The tab shows four keys, listed in `integrations/service.py:45-52`.

| Category | Key | Platform value | Read at runtime |
|---|---|---|---|
| weather | `weather.default_provider_code` | `open_meteo` | No. No consumer anywhere. |
| weather | `weather.default_cadence_hours` | 3 | No. `weather/tasks.py:1034` uses `settings.weather_default_cadence_hours` from the environment. |
| imagery | `imagery.cloud_cover_threshold_pct` | 30 | No. `imagery/tasks.py:1758` reads the `cloud_cover_max_pct` column and the environment ceiling. It never calls the resolver. |
| detection | `grid.anomaly_z_threshold` | 1.5 | Yes. `grid/snapshot.py:43` and `grid/tasks.py:97`. |

A key changes behaviour only if some code calls `SettingsResolver`. Outside the integrations
module there are exactly two such callers, both in `grid/`. **Three of the four rows on the
tab accept a value and discard it.** This is the same defect PR #334 fixed one tier higher:
that audit dropped keys with no consumer at any tier, and kept these three as documented
defaults, but a documented default that the editor lets you change is not documentation.

The catalog is also frozen. The last key added was `grid.anomaly_z_threshold` in migration
`public/0026`, dated 2026-06-07. Since `public/0048` there are 16 more public migrations on
`origin/main`, up to `0068_seed_msavi_index.py`, and none of them adds a default. Features
built in that window with no entry on the tab: thermal indices (LST, CWSI, SMI), MSAVI, BSI,
MSI, SPI drought, weather index forecast, farm-level subscriptions, Action Center and alert
grouping, Scout, field access, push notifications, backfill runs, tenant purge, RBAC role
overrides.

### Farm creation reads none of it

`FarmService.create_farm` (`farms/service.py:729`) inserts the farm row, writes an audit
entry, and publishes `FarmCreatedV1`. **Nothing subscribes to `FarmCreatedV1`.** The only
subscribe calls in `backend/app` are the realtime pub/sub in `notifications/router.py`, which
is an unrelated mechanism. The frontend matches: `CreateFarmFlow.tsx:144-151` calls
`createFarm(payload)` and then navigates to the console, with no follow-up call.

A farm created today therefore has no row in `imagery_farm_subscriptions`, no row in
`weather_subscriptions`, `farms.default_grid_cell_size_m` NULL,
`farms.default_anomaly_z_threshold` NULL, and no `grid_configs` row on any block. Until
someone opens the Farm tab and sets each one by hand, the farm fetches no imagery and no
weather.

### Gap register

| ID | Gap | Evidence — why it's a gap | Blocks |
|---|---|---|---|
| **D-1** | Three of the four tenant keys are display-only | Only `grid/snapshot.py:43` and `grid/tasks.py:97` call `SettingsResolver` outside the integrations module. The other three keys have no reader. | Any operator trust in the tab |
| **D-2** | The key catalog stopped growing on 2026-06-07 | Last add is `public/0026`. Sixteen public migrations since `public/0048` add none. | Per-tenant control of every feature built since |
| **D-3** | `create_farm` provisions nothing | `farms/service.py:729` inserts one row and publishes one event. No subscription, no grid template, no column write. | A new farm produces no data until configured by hand |
| **D-4** | `FarmCreatedV1` has no subscriber | No subscribe call for it exists in `backend/app`. The event is published into nothing. | Any event-driven provisioning design |
| **D-5** | Two mechanisms hold the anomaly threshold | `grid.anomaly_z_threshold` is a resolver tier read at evaluation time. `farms.default_anomaly_z_threshold` is a farm column written down into `grid_configs` on Apply (`farms/config_template.py:914-943`). The farm column does not seed from the tenant value. | One number, two sources of truth, no reconciliation |
| **D-6** | Ten environment values are shared by every tenant | Each has a real consumer and is set once per server: `imagery_cloud_cover_visualization_max_pct` (60), `imagery_cloud_cover_aggregation_max_pct` (20), `imagery_discovery_anchor_hour_utc` (14), `imagery_cloud_mask_enabled` (true), `imagery_backfill_floor_days` (90), `weather_past_hours` (48), `weather_forecast_hours` (120), `integration_failure_streak_threshold` (3), `recommendations_eval_run_retention_days` (100), `grid_superseded_retention_days` (7). `core/settings.py:310` already records that the failure streak wants a `platform_defaults` override. | Per-tenant tuning of imagery cost and alert noise |
| **D-7** | No key describes what a new farm should get | There is no `farm.default_*` key of any kind. The seven values a new farm needs live only in the operator's head. | D-3; any consistent onboarding |

### Scope decisions (locked — do not re-litigate)

1. **Every key must have a runtime reader, or it does not exist.** A key that only round-trips
   to the editor is worse than no key, because it reads as configured.
2. **The farm tier stays where it is.** Farm-level values already live on `farms.*` columns and
   on the subscription rows. Do not add a farm tier to `SettingsResolver` for the new keys.
3. **Provisioning happens in `create_farm`, not in an event subscriber.** `FarmCreatedV1` has
   no subscriber, and the event bus dispatches sync handlers inside the publisher's call stack
   (`imagery/subscribers.py` header). A default that half-applies after commit is worse than
   one applied in the same transaction.
4. **Existing farms are not backfilled.** A farm already configured by hand must not be
   rewritten by a default it never saw.
5. **`imagery.cloud_cover_threshold_pct` keeps its ceiling semantics.** `_effective_cloud_cap`
   takes the lower of the platform value and the subscription value on purpose
   (`imagery/tasks.py:1735-1760`). Wiring the tenant tier must not let a tenant raise the cap
   above the platform ceiling.

### In scope

- **Backend: resolve the three inert keys.** For each of `weather.default_provider_code`,
  `weather.default_cadence_hours` and `imagery.cloud_cover_threshold_pct`, either make the
  consumer call `SettingsResolver`, or delete the key in a migration and drop it from
  `WEATHER_KEYS` / `IMAGERY_KEYS`. No third option.
- **Backend: seven new keys** in `public.platform_defaults`, each with a `KeyConstraint` in
  `shared/settings/constraints.py`: `farm.default_imagery_product_code`,
  `farm.default_imagery_cadence_hours`, `farm.default_fetch_farm_aoi`,
  `farm.default_weather_provider_code`, `farm.default_weather_cadence_hours`,
  `farm.default_grid_cell_size_m`, `farm.default_anomaly_z_threshold`.
- **Backend: `create_farm` provisions from the resolver** in the same transaction — one
  imagery farm subscription, one weather farm subscription, and both `farms.default_*` grid
  columns. Route the imagery subscription through `ImageryService._resolve_block_scope`
  (`imagery/service.py:397`), never a direct insert.
- **API:** `POST /v1/farms` gains `apply_defaults: bool`.
- **Frontend:** the create panel gains an "apply tenant defaults" checkbox that shows the
  resolved values read-only. The Integrations tab marks any row that is not read at runtime.
- **Backend: ten environment values promoted to keys**, imagery first, then weather, then the
  retention and alerting values. One migration per category, not one migration for all ten.
- **Tests:** a CI test that fails when a row in `platform_defaults` has no `SettingsResolver`
  caller. That test is what would have caught D-1 and D-2.

### Out of scope (must not build)

- A farm tier in `SettingsResolver` for the new keys (scope decision 2).
- Backfilling defaults onto farms that already exist (scope decision 4).
- Retiring `farm_weather_overrides` and `farm_imagery_overrides`, whose only reader is the
  resolver itself. That is its own decision, recorded in the 2026-07-29 audit.
- Merging `farms.default_anomaly_z_threshold` and `grid.anomaly_z_threshold` into one
  mechanism (D-5). Name it here, do not fix it here.
- A tenant-facing editor for the seven new farm keys. Platform Admin only in this prompt.
- Any new category on the Integrations tab. `email` and `webhook` were removed in
  `public/0048` and stay removed.

### Definition of done (the gate)

1. Every key returned by `GET /api/v1/admin/defaults` either has a runtime consumer, or is
   absent. No key is editable and unread.
2. Adding a key with no `SettingsResolver` caller fails CI.
3. Creating a farm with `apply_defaults` true produces one active imagery subscription, one
   active weather subscription, and both grid columns set. A count query on the new farm is
   the proof.
4. Creating a farm with `apply_defaults` false produces exactly the rows it produces today.
5. Setting a tenant override, then creating a farm, uses the override value and not the
   platform value.
6. Editing `imagery.cloud_cover_threshold_pct` on the Integrations tab changes what the
   discovery task fetches, and cannot raise the cap above the platform ceiling.
7. `ruff`, `mypy`, `tsc -b`, `eslint` and `import-linter` all pass.

### Known traps (repo-specific)

- **The defaults cache is 60 seconds per process** (`shared/settings/resolver.py:34`). A write
  calls `invalidate_defaults_cache()` on the API pod only. A Celery worker keeps the old value
  for up to 60 seconds. Do not write a test that asserts an immediate flip inside a worker.
- **`tenant_settings_overrides.key` is a foreign key to `platform_defaults.key` with ON DELETE
  RESTRICT.** Delete the override rows before deleting a key, or the migration errors.
  `public/0048` records the same trap.
- **A farm imagery subscription with `fetch_farm_aoi` false and no block rows fetches nothing,
  ever.** Measured on production for greenFarm_Test. `_resolve_block_scope` exists to stop
  this; call it.
- **The block tier uses different column names than the farm tier.** `imagery_aoi_subscriptions`
  has `cloud_cover_max_pct`; `farm_imagery_overrides` has `cloud_cover_threshold_pct`. Mapping
  one onto the other raised `UndefinedColumn` on every read for months, and a bare `except`
  hid it. See `_BLOCK_IMAGERY_COLUMNS` in `shared/settings/resolver.py`.
- **Re-check the next free public migration number right before pushing.** This race has been
  lost three times on this repo.

### Open questions (answer before the first PR)

- For each of the three inert keys: wire it, or retire it?
- Should `apply_defaults` default to true on the API, or only in the console, so a script that
  creates farms does not start spending provider quota by surprise?
- Does a new farm get live subscriptions, or only the template values, so imagery starts on a
  deliberate act?
- `farm.default_imagery_product_code` or `farm.default_imagery_product_id`? The code is stable
  and readable; the id is what the subscription row needs.

---

## Prompt 10 — Onboarding: from tenant created to a farm you can trust

**Goal:** make the first hour of a new customer work without an operator. Today a
provisioning failure shows one fixed sentence and hides its cause, account email is
branded but English only, the first screen a new owner sees is a single empty card, a farm
drawn with the wrong boundary can only be fixed by inactivating and purging it, and the
date on screen is formatted from four different sources depending on which component drew
it.

**Source analysis:** read on 2026-08-21 against `origin/main` at `aa719d0b`, which
includes PR #542 (`677c7dc`, HTML product email and a Keycloak email theme). The first
read of track 2 was taken from a branch 226 commits behind and was wrong; it is corrected
here. Line numbers are from `origin/main`. Nothing in `docs/proposals/` covers this.
Track 3 depends on Prompt 9 (D-3); the other four tracks do not.

### What the reading found

Five tracks. Each is a separate step of the same journey, and each fails on its own.

**Track 1 — provisioning.** `TenantService.create_tenant` has two failure shapes and one
status for both. Shape A: `self._kc.ensure_group` raises, the service logs
`tenant_provisioning_failed` and sets `pending_provision` (`tenancy/service.py:449-462`).
No owner row is written at all, because `TenantUsersService.invite_user` is never reached.
Shape B: the group is created, `invite_user` runs and returns `keycloak_provisioning !=
"succeeded"`, so the `public.users`, `tenant_memberships` and `tenant_role_assignments`
rows do land (`tenancy/service.py:462-489`). Both shapes end as `pending_provision`, and
the reason is written only to the log line.

**Track 2 — account email.** PR #542 closed most of this before the prompt was written.
An `email/` theme now exists with `executeActions` (the invite) and `password-reset` in
both html and text, `emailTheme` is set in the realm file and in the promote script, and
`Dockerfile.theme` asserts seven email files. What is left is language and coverage: the
theme ships `messages_en.properties` only, and its own `theme.properties` records why —
"locales: English only. The realm has internationalizationEnabled unset." Product email
(alerts, recommendations) is bilingual because the api sends it, not Keycloak.

**Track 3 — first run.** `HomePage.tsx:37-52` is the whole first-run experience: one
heading, one sentence, one button. There is no checklist and no second step.

**Track 4 — boundary correction.** The API already accepts a new farm boundary. The
frontend has no way to send one.

**Track 5 — date format.** The frontend has 57 date and time formatting calls outside
tests, and they read the locale from four different places: `i18n.language`, the browser
default, a hard-coded `"en-US"`, and `chartDateLocale`, which itself returns `"en-US"` for
every language that is not Arabic (`lib/chartFormat.ts:15-17`). The farm country is used
by nothing. A user in Egypt with an `en-GB` browser reads `8/21/2026` on one screen and
`21/08/2026` on another.

### Gap register

| ID | Gap | Evidence — why it's a gap | Blocks |
|---|---|---|---|
| **O-1** | The provisioning failure reason is never stored | `tenancy/service.py:451-458` puts the Keycloak error string in a log line only. `TenantSnapshot` carries no reason field, so the console shows one fixed sentence for every cause (`en/admin.json:266`). | Any operator fixing the failure without shell access to the pod |
| **O-2** | Two different failure shapes share one status | Shape A leaves no owner rows; shape B leaves all of them. Both write `pending_provision`. Nothing on the row records which happened. | O-3; any correct retry |
| **O-3** | Retry does not use the create path | `retry_provisioning` (`tenancy/service.py:544-583`) calls `self._kc.ensure_group` and `self._kc.invite_user` directly. It never calls `TenantUsersService.invite_user`. After shape A it sets the tenant to `active` while the owner still has no `public.users` row, no membership and no role assignment. | A retried tenant whose owner can sign in and see nothing |
| **O-4** | Retry writes no Keycloak subject back | `set_provisioning_state` updates the tenant row only. A `public.users` row created during shape B keeps `keycloak_subject = 'pending::<email>'` for ever, and the third branch of the Keycloak provisioning helper (`iam/users_service.py:666-668`) returns `pending` for that email with no Keycloak call at all. | Re-inviting the owner; `resend_invite` returns `pending` for a `pending::` subject (`users_service.py:876`) |
| **O-5** | The retry tests cannot see O-3 or O-4 | `tests/integration/tenancy/test_keycloak_provisioning.py:103-125` asserts the tenant snapshot and `len(fake.users) == 1`. It reads no `public.users`, `tenant_memberships` or `tenant_role_assignments` row. | Catching this class of defect at all |
| **E-1** | Two account emails are covered; the rest fall through unbranded | The theme holds `executeActions` and `password-reset` only. Its own `theme.properties` records the consequence: any Keycloak email with no template "still falls through to base and renders unbranded; today that is only templates for flows this realm has switched off (self-registration, email verification, OTP)". Switching one of those flows on ships a stock email. | Turning on email verification, which `agripulse-realm.json` does not set either way |
| **E-2** | ~~The realm has no email theme~~ — **closed by PR #542** | `themes/agripulse/email/` now holds `html/template.ftl`, `html/executeActions.ftl`, `html/password-reset.ftl`, both text versions, `theme.properties` and `messages/messages_en.properties`. `emailTheme` is set in `agripulse-realm.json:17` and again in `promote-kc-tenancy.py:180`, because the live realm never re-reads the import file. `Dockerfile.theme:38-44` asserts all seven files. | Nothing. Kept as the record of what shipped, and as the pattern to copy |
| **E-3** | `accountTheme` names a theme that has no account directory | `agripulse-realm.json:16` sets `accountTheme: agripulse`, and `themes/agripulse/` holds `login/` and `email/` only. Keycloak falls back to its own default for a missing theme type, so the key reads as configured and changes nothing on screen. Still open after #542. | Trusting the realm file as a record of what users see |
| **E-4** | Account email is English only | `email/theme.properties` sets `locales=en` and says why: "The realm has internationalizationEnabled unset, so Keycloak has one language to render in." `agripulse-realm.json` sets no `internationalizationEnabled` and no `supportedLocales`. The product ships Arabic, `default_locale` is a tenant column, and product email is already bilingual through `public/0070`. | An Arabic-speaking owner reading an English invite as the first thing the product sends |
| **E-5** | SMTP is set once and never checked | `promote-kc-tenancy.py` writes `realm["smtpServer"]` from the `BREVO_*` values at promote time and prints the host. There is no test send, no delivery record and no alert. `keycloak_smtp_enabled` (`core/settings.py:101`) switches invites to a temporary password in the API response with no other signal. PR #542 fixed the matching gap for product email — the workers chart carried `SMTP_PASSWORD` and none of the other four keys — which is the same class of defect one layer down. | Knowing whether a welcome email arrived |
| **F-1** | The first screen has one action and no path | `HomePage.tsx:37-52`. With `farm.create` the user gets a title, one sentence and one button. Without it the user gets "Welcome" and "Features coming soon." and no action at all. | Any owner whose first job is not creating a farm — inviting a team, setting units, picking crops |
| **F-2** | The first action routes to a labs URL | `HomePage.tsx:46` links to `/labs/map-v2?create=farm`. The first task asked of a paying customer runs through a route named `labs`. | Confidence; and the two-console drift already recorded for the Farm tab |
| **F-3** | The first farm still produces nothing | Prompt 9, D-3: `create_farm` writes one row. A new farm has no imagery subscription, no weather subscription and no grid template. The empty state disappears and no data arrives. | The whole first-run promise. Fix D-3 before F-3 |
| **F-4** | There is no first-run checklist | I searched the frontend for onboarding, getting-started and checklist. No component exists. | Knowing what is left to set up |
| **B-1** | The frontend cannot change a farm boundary, but the API can | `PATCH /farms/{farm_id}` accepts `boundary` (`farms/router.py:241-264`), `FarmUpdateRequest.boundary` is declared (`farms/schemas.py:549`), and `update_farm` validates and writes it (`farms/service.py:837-889`). | The reported problem: the only fix today is inactivate, purge, re-create |
| **B-2** | Nothing links to the farm edit page | The route is registered at `App.tsx:152`. A search over `frontend/src` for links to `/farms/:farmId/edit` returns the route line and its two test files only. | Reaching the page that already exists |
| **B-3** | The edit form drops the boundary it was given | `FarmEditPage.tsx:87` passes `initial.boundary`. `FarmForm` never reads it: `drawnPolygon` and `uploadedBoundary` both start `null` (`FarmForm.tsx:77-78`), `MapDraw` and `AoiUploader` receive no initial value (`FarmForm.tsx:340-345`), and submit stops with `boundaryRequired` when both are empty (`FarmForm.tsx:108-112`). Renaming a farm therefore forces a full redraw. | B-1; any use of the edit page for any field |
| **B-4** | `FarmBoundaryChangedV1` has no subscriber | Published at `farms/service.py:880-888`. No `subscribe` call for it exists in `backend/app`. Same shape as `FarmCreatedV1` in Prompt 9, D-4. | Recomputing anything after a boundary changes |
| **L-1** | Four locale sources for one date | Of the 57 formatting calls outside tests, spread over 34 files: 6 pass `chartDateLocale(lang)`, 4 pass `i18n.language`, 3 pass `undefined` (the browser), 3 hard-code `"en-US"`, and 2 pass nothing at all. Nothing decides which is right. | One readable date across the product |
| **L-2** | The chart helper hard-codes US order | `chartDateLocale` returns `"en-US"` for every language that is not Arabic (`lib/chartFormat.ts:15-17`). A browser set to `en-GB`, and every Egyptian user reading the English UI, gets month-before-day on every chart axis and tooltip. | The reported problem |
| **L-3** | There is no shared date helper for tables and pages | `lib/chartFormat.ts` covers chart axes and tooltips only. A search for a `formatDate` export over `frontend/src` returns nothing. Each page formats its own dates. | Fixing L-1 in one place |
| **L-4** | The farm country carries no locale, and will not be the source | `public.countries` (`public/0043`) holds `code`, `name_en` and `name_ar` and nothing else — no locale, no date order, no timezone. `farms.country_code` is nullable and the create form leaves it optional. Recorded so the option is not re-opened: scope decision 9 uses the browser instead. | Nothing, once scope decision 9 stands |
| **L-5** | There is no farm or tenant timezone | No timezone column exists on `farms` or `tenants`. Every timestamp renders in the browser's own zone, and a date-only value parsed by `new Date()` is UTC midnight, so a browser west of UTC shows the previous day. `WeatherForecastPanel.tsx:182` already records that hazard in a comment. | The day shown next to a satellite pass or a weather row |
| **B-5** | Nothing counts what the old boundary already produced | A farm can carry a farm-level imagery subscription, past scenes, grid cells, block aggregates and a weather point, all derived from the old outline. No read collects those counts. | The safety condition the user asked for: allow the override only when nothing is attached |

### Scope decisions (locked — do not re-litigate)

1. **The failure reason lives on the tenant row.** An operator must not need pod logs to
   read why provisioning failed. Store the reason and the shape, and show both.
2. **Retry uses the create path.** `retry_provisioning` calls
   `TenantUsersService.invite_user`, the same call `create_tenant` makes. One invite path,
   not two.
3. **Account email stays Keycloak's job.** PR #542 already settled this: the theme lives
   at `infra/helm/keycloak/themes/agripulse/email/` and `emailTheme` is set in two places.
   Extend that theme. Do not add account templates to `public.notification_templates`;
   that table serves alerts, recommendations and visits, and its renderer runs inside the
   notifications subscriber.
4. **Arabic is part of this track, not a follow-up.** Turn on realm internationalisation
   with `en` and `ar`, and ship both message files with the email theme.
5. **A boundary override is allowed only when nothing derived from the old boundary
   exists.** "Nothing derived" is a counted list, not a judgement: zero blocks, zero grid
   cells, zero imagery subscriptions, zero imagery jobs, zero index aggregates, zero
   weather subscriptions. The counts are read and shown before the save.
6. **When something is attached, the override is refused with the counts.** Do not build a
   cascade that deletes imagery so a boundary can move. That is the purge path, and it
   already exists.
7. **The first-run screen creates no sample data.** A demo farm in a real tenant becomes
   real data nobody deletes.
8. **One date helper, and a lint rule that keeps it the only one.** A direct
   `toLocaleDateString` in a component fails the build after this prompt.
9. **The browser locale decides the date format.** Read `navigator.languages[0]`, or
   `navigator.language` when that is empty. Not `i18n.language`, which is only `en` or
   `ar` and carries no region. Not the farm country. Not the tenant `default_locale`. One
   source, chosen by Mohamed on 2026-08-21.
10. **Region and language are read from two places.** The browser locale gives the region,
    which sets the field order and the separator. `i18n.language` gives the language, which
    sets the month name. The helper builds one BCP-47 tag from both, and always appends
    `-u-nu-latn` so digits stay Latin, as `ARCHITECTURE.md` § 11 requires and
    `lib/chartFormat.ts:1-13` already records. Switching the interface to Arabic changes
    the month name only.

### In scope

- **Backend: record the failure.** Add `provisioning_error` and `provisioning_stage` to the
  tenant row, write both in the two `except` paths of `create_tenant`, clear them on a
  successful retry, and return them on `TenantSnapshot` and `TenantDetailResponse`.
- **Backend: one invite path.** Rewrite `retry_provisioning` to call
  `TenantUsersService.invite_user` with the pending owner, so shape A produces the
  `public.users`, `tenant_memberships` and `tenant_role_assignments` rows it skipped.
- **Backend: write the subject back.** After a successful invite for an email whose
  `public.users.keycloak_subject` still starts with `pending::`, update the column. Cover
  the third branch of the Keycloak provisioning helper (`iam/users_service.py:666-668`),
  which today makes no Keycloak call.
- **Backend tests: assert the rows, not the fake.** Extend `test_keycloak_provisioning.py`
  so every retry test reads `public.users`, `tenant_memberships` and
  `tenant_role_assignments`. That is what would have caught O-3.
- **Frontend: show the reason.** The tenant detail page shows the stored stage and error
  next to the Retry provisioning button, in place of the one fixed sentence.
- **Infra: Arabic account email.** Set `internationalizationEnabled`,
  `supportedLocales: [en, ar]` and `defaultLocale` on the realm, change
  `email/theme.properties` from `locales=en` to `locales=en,ar`, and add
  `messages_ar.properties` to both the email theme and the login theme. Add the Arabic
  files to the `Dockerfile.theme` assertion list, which already checks seven email files.
- **Infra: close the two theme gaps #542 left.** Fix `accountTheme` by adding an
  `account/` directory or removing the key (E-3), and decide whether `email-verification`
  needs a template before `verifyEmail` is ever switched on (E-1).
- **Infra: prove the mail path.** Add a test-send step to the promote job, or an admin
  endpoint that sends one email and reports the result. E-5 is the reason nobody knows
  whether a welcome email arrived.
- **Frontend: a first-run page.** Replace the single card with a checklist that reads live
  state and shows what is done: farm created, imagery subscribed, weather subscribed, grid
  set, team invited, crop assigned. Each row links to the page that completes it. A row the
  user has no capability for is shown as another person's task, not hidden, so F-1's dead
  end disappears.
- **Frontend: move the first action off `labs`.** The create-farm entry point on the
  first-run page points at the supported farm-creation route.
- **Backend: a boundary-change preflight.** `GET /farms/{farm_id}/boundary-change-preview`
  returns the six counts from scope decision 5 and one `can_replace` boolean.
- **Backend: gate the boundary write.** `PATCH /farms/{farm_id}` with a `boundary` returns
  409 with the counts when `can_replace` is false. Today it accepts the write with no check
  at all.
- **Frontend: a farm boundary editor.** Link to the farm edit page from the farm detail and
  Farm Console pages, seed `MapDraw` and `AoiUploader` from `initial.boundary` so the form
  no longer forces a redraw (B-3), and show the preflight counts before the save.
- **Frontend: one date module.** Add `lib/dateFormat.ts` with a `useDateFormat()` hook that
  returns day, day-with-time, month and weekday formatters. It builds one BCP-47 tag from
  the browser region and the interface language, per scope decisions 9 and 10. Move
  `chartDateLocale` onto the same resolver so its `"en-US"` fallback goes.
- **Frontend: replace all 57 call sites** with the helper, including the ones that pass no
  locale at all and the ones that hard-code `"en-US"`.
- **Frontend: a lint rule.** Ban `toLocaleDateString`, `toLocaleTimeString`,
  `Date.prototype.toLocaleString` and bare `Intl.DateTimeFormat` outside `lib/dateFormat.ts`.
  Without the rule the four sources come back one pull request at a time.
- **Tests:** render one timestamp under `en-GB`, `en-US` and `ar`, and assert three
  different strings. Assert Latin digits in the Arabic case.

### Out of scope (must not build)

- Provisioning a farm from tenant defaults. That is Prompt 9, D-3, and F-3 waits for it.
- A subscriber for `FarmBoundaryChangedV1` (B-4). Name it here, do not build it here.
- Any cascade that deletes imagery, grid cells or aggregates so a boundary can move
  (scope decision 6).
- Moving account email out of Keycloak into the app's own SMTP sender.
- Per-tenant email branding. One realm theme for the platform in this prompt.
- Editing a block boundary. `update_block` has its own destructive-replace rules and its
  own gate; this prompt is farm-level only.
- Sample or demo data on first run (scope decision 7).
- A self-service signup page. `registrationAllowed` stays false.
- A farm or tenant timezone column (L-5). Name it here, do not build it here. Timestamps
  keep rendering in the browser's zone.
- A date format derived from the farm country, and a `default_locale` column on
  `public.countries` to carry it (L-4). Scope decision 9 rules this out.
- A per-user date-format setting. The browser decides; the user does not choose inside the
  product. Changing the browser or system region is the way to change the format.
- Any non-Gregorian calendar. Hijri dates are a separate decision.
- Number, area and unit formatting. `lib/units.ts` and `lib/weatherUnits.ts` stay as they
  are; this track is dates and times only.

### Definition of done (the gate)

1. A tenant whose `ensure_group` fails shows the failure stage and the Keycloak error text
   on the tenant detail page, with no pod log read.
2. After Retry provisioning succeeds on that tenant, a count query returns one
   `public.users` row, one `tenant_memberships` row and one `tenant_role_assignments` row
   for the owner, and `keycloak_subject` does not start with `pending::`.
3. That owner signs in and lands on the first-run page with a tenant role, not a 403.
4. A retry test fails when the membership rows are missing.
5. An invite email received in a tenant whose `default_locale` is `ar` is in Arabic. The
   English version already carries the AgriPulse layout from PR #542, so this gate is
   about language only.
6. One command or endpoint sends a test email and reports success or the SMTP error.
7. The first-run page shows six checklist rows, and each row's state matches a query
   against the tenant schema.
8. On a farm with zero blocks and no subscriptions, an owner redraws the boundary from the
   farm page and saves. `GET /farms/{id}` returns the new outline and the area changes.
9. On a farm with at least one block, the same attempt returns 409 and the response names
   the counts.
10. Opening the farm edit page and changing only the name saves, with no redraw.
11. A browser set to `en-GB` shows `21/08/2026` on every screen, and a browser set to
    `en-US` shows `8/21/2026` on every screen. The farm on the page changes nothing.
12. The same two browsers disagree on a chart axis as well as in a table. Charts read the
    same helper, so `chartDateLocale`'s `"en-US"` fallback is gone.
13. Switching the interface to Arabic changes the month name and keeps Latin digits. No
    screen shows `٢١`.
14. `grep -rn "toLocaleDateString" frontend/src` returns `lib/dateFormat.ts` only, and
    adding the call back to a component fails `eslint`.
15. `ruff`, `mypy`, `tsc -b`, `eslint` and `import-linter` all pass.

### Known traps (repo-specific)

- **`retry_provisioning` runs on a tenant that may already hold owner rows.** Shape B wrote
  them. Calling `TenantUsersService.invite_user` again must reuse the existing
  `public.users` row by email — that path exists at `iam/users_service.py:723-742` — and
  must not insert a second membership.
- **`create_tenant` flushes but does not commit**; the caller's `session.begin()` commits
  (`tenancy/service.py:422`). A new column write must stay inside that transaction.
- **`invalidate_tenant_status_cache` is per process.** The API pod clears its own cache.
  Do not assert an immediate flip from a worker.
- **A missing Keycloak theme type falls back with no error.** E-3 is the proof: an
  `accountTheme` that names a theme with no `account/` directory has been in the realm file
  and has changed nothing. Check the rendered page, not the realm JSON.
- **The theme image is built separately.** `infra/helm/keycloak/Dockerfile.theme` copies
  `themes/agripulse` and asserts eleven files: four login, seven email. A new Arabic file
  that is not added to that list ships missing without failing the build.
- **`emailTheme` is set in two places on purpose.** `agripulse-realm.json:17` covers a
  fresh import; `promote-kc-tenancy.py:180` covers the live realm, which never reads the
  import file again. Changing one and not the other looks correct and changes nothing on
  the running server.
- **`keycloak_smtp_enabled` changes the invite result shape.** When false the API returns a
  temporary password instead of sending mail. A first-run test that asserts on email
  delivery passes or fails on this flag, not on the theme.
- **`FarmForm` is shared by create and edit** (`FarmForm.tsx:44`). Seeding the map from
  `initial.boundary` must not pre-fill the create flow.
- **A farm boundary has no `aoi_hash`.** The trigger in `tenant/0002` computes `aoi_hash`
  for blocks only. Do not use a hash comparison to decide whether a farm boundary changed;
  compare the geometry.
- **Plain `ar` emits Arabic-Indic digits.** `lib/chartFormat.ts:1-13` records the decision
  to pass `ar-u-nu-latn` instead. Any new formatter must carry the same suffix.
- **A date-only string is parsed as UTC midnight.** `new Date("2026-08-21")` in a browser
  west of UTC renders 20 August. `WeatherForecastPanel.tsx:182` and
  `signals/components/ObservedAtPicker.tsx:17` both work around this today.
- **`farms.country_code` is nullable.** The create form leaves the field optional, so many
  farms carry no country. The resolver must fall through, not throw.
- **`chartDateLocale` is imported by six call sites and still returns `"en-US"` for every
  language that is not Arabic on `origin/main`.** Changing its return value changes
  every chart axis at once. Read the callers before editing it.
- **jsdom reports one locale.** `navigator.language` under Vitest does not follow the
  machine. A test for gate item 11 must set the value itself, or it asserts nothing.
- **`navigator.languages` can be empty.** Read `navigator.languages[0]` first and fall back
  to `navigator.language`, then to a written-down default. Do not index an empty array.
- **Re-check the next free migration number right before pushing.** This race has been lost
  four times on this repo.

### Open questions (answer before the first PR)

- Does `pending_provision` need to split into two statuses, one per failure shape, or is a
  `provisioning_stage` column next to the existing status enough?
- Is the failure text shown raw, or mapped to a short list of causes? A raw Keycloak error
  can carry a URL and a client id.
- Is `verifyEmail` going to be switched on? If yes, `email-verification` needs a template
  before that day, or the first email a customer sees is stock Keycloak markup.
- Is the email locale the tenant's `default_locale`, the user's `preferred_language`, or
  the Keycloak user locale attribute? All three exist and they can disagree. Keycloak
  renders from its own user locale, so something has to write it at invite time.
- Does the first-run page replace `HomePage`, or does `HomePage` redirect to it while the
  checklist is incomplete?
- For the boundary override: is "zero blocks" the whole condition, or do zero blocks plus a
  farm-level imagery subscription with past scenes still stop the change?
- Is the override gated by a capability beyond `farm.update`? Replacing an outline is
  closer to re-creating the farm than to renaming it.
- With an Arabic interface and an `en-US` browser, does the user want `٢١ أغسطس` order
  from the language or `August 21` order from the region? Scope decision 10 takes the
  order from the region and the month name from the language. Confirm on one screen before
  the whole replacement.
- Should a printed or exported report use `2026-08-21` instead of the browser order? A CSV
  read by a spreadsheet is a different reader from a person, and `lib/csv.ts` writes its
  own dates today.
- What happens when the browser reports a locale with no region, such as plain `en`? The
  helper needs one written-down answer, not a per-call guess.
- Does the timezone gap (L-5) need to move into this prompt? Without it, a satellite pass
  at 03:24 UTC shows as 21 August in Egypt and 20 August in a browser set to New York.

---

## Prompt 11 — Farms outside Egypt: the fixed UTM zone

**Goal:** let a tenant create a farm anywhere on Earth and get a correct area, a correct grid,
and a stable imagery identity. Today a country check blocks the attempt. That check is also
the only thing keeping a wrong area out of the database.

**Source analysis:** produced in the 2026-08-21 session while answering a support question —
"Boundary is outside Egypt's bounding box" on a farm outside Egypt. In that session the check
was removed, the effect was measured, and the check was put back unchanged. Nothing in
`docs/proposals/` covers this. Do not go looking for a plan document that was never written.

### What the reading found

Two separate limits look like one limit.

The first limit is a check, and it is small. `farms/geometry.py` rejects any vertex outside
longitude 24 to 36 and latitude 22 to 32. It raises `GeometryOutOfEgyptError`
(`farms/errors.py:333`). The browser carries the same box as `EGYPT_BBOX` in
`frontend/src/lib/geometry.ts`. Removing both, with their tests and their English and Arabic
text, is a change of about 120 lines across 16 files.

The second limit is the database, and it is not small. The tenant migration
`0002_farms_blocks_attachments.py` converts every boundary to UTM zone 36 North. The zone
number is a literal inside two trigger functions:

```
NEW.boundary_utm := ST_Multi(ST_Transform(NEW.boundary, 32636));   -- farms, line 48
NEW.area_m2      := ST_Area(NEW.boundary_utm);                     -- farms, line 50
NEW.boundary_utm := ST_Transform(NEW.boundary, 32636);             -- blocks, line 65
NEW.aoi_hash     := encode(digest(ST_AsText(NEW.boundary_utm), 'sha256'), 'hex');  -- line 68
```

The columns also pin the number in their type: `Geometry("MULTIPOLYGON", srid=32636)` at line
98 and `Geometry("POLYGON", srid=32636)` at line 229. PostGIS rejects any other SRID in those
columns.

Zone 36 is correct for Egypt. Far from zone 36, `ST_Transform` does not fail. It returns a
finite number that is wrong. Measured with pyproj against a local equal-area projection at the
same point, using a 0.01-degree square:

| Place | Longitude | Area error |
|---|---|---|
| Cairo, Egypt | 31.2 | -0.01% |
| Aswan, Egypt | 32.9 | -0.08% |
| Nairobi, Kenya | 36.8 | +0.36% |
| Riyadh, Saudi Arabia | 46.7 | +4.80% |
| Tripoli, Libya | 13.2 | +8.75% |
| Dubai, UAE | 55.3 | +13.36% |
| Madrid, Spain | -3.7 | +26.09% |
| Iowa, USA | -93.6 | +55.44% |
| Sao Paulo, Brazil | -46.6 | +427.57% |

**Removing the check alone would let a farm save and then report a wrong size, with no error
shown.** `area_m2` feeds the feddan and hectare display, the grid cell size derived from a
maximum block area, and every per-hectare number in plans and reports.

### Gap register

| ID | Gap | Evidence — why it's a gap | Blocks |
|---|---|---|---|
| **U-1** | The country check exists twice | `farms/geometry.py` holds the box for the API. `frontend/src/lib/geometry.ts` holds the same four numbers for the browser. | Removing it in one place only, which leaves the other rejecting the farm |
| **U-2** | The UTM zone is a literal in two triggers | Migration `0002` lines 48 and 65 both write `32636`. | Any farm outside longitude 30 to 36 |
| **U-3** | The columns pin SRID 32636 in their type | Migration `0002` lines 98 and 229. | Writing any other zone without an `ALTER TABLE` on every tenant schema |
| **U-4** | `aoi_hash` is a SHA-256 of the UTM text | Migration `0002` line 68. The hash is how a block is matched to its stored satellite imagery. | Changing a block's zone, which changes the hash and orphans its imagery history |
| **U-5** | Egypt itself spans two zones | Longitude 24 to 30 is zone 35 North (SRID 32635). Longitude 30 to 36 is zone 36 North. The current check accepts both halves. | A rule that derives the zone from the centroid on every write, which moves existing farms west of longitude 30 into zone 35 |
| **U-6** | The grid inherits the zone from the block | `grid/repository.py:75` reads `ST_SRID(boundary_utm)`. `grid/service.py:346` stores it on `grid_configs.utm_srid`. | Grid cells, which move whenever the block's zone moves |
| **U-7** | No test covers a boundary outside Egypt | The three tests that mention the box all assert rejection. | Any confidence that the rest of the stack works outside Egypt |

### Scope decisions (locked — do not re-litigate)

1. **The zone is stored once per farm, not derived on every write.** A trigger that derives the
   zone from the centroid recomputes it on every update. An existing Egyptian block at
   longitude 27 would then move from zone 36 to zone 35 on its next edit, change its
   `aoi_hash`, and lose its imagery history without showing an error. Storing the zone makes
   the change explicit and reviewable.
2. **Every farm that exists today keeps SRID 32636.** The migration backfills the stored zone
   with 32636 for all existing farms. No existing `boundary_utm`, `area_m2`, or `aoi_hash`
   value changes. Re-zoning the Egyptian farms west of longitude 30 is a separate decision with
   its own imagery backfill, and it is out of scope here.
3. **The zone comes from the boundary centroid, not from the user.** The rule is
   `32600 + floor((longitude + 180) / 6) + 1` north of the equator, and `32700 + ...` south of
   it. A farm that crosses a zone edge takes the zone of its centroid. Blocks always take their
   farm's zone, so a farm and its blocks always share one coordinate system.
4. **The check removal and the zone fix ship in the same pull request.** Removing the check
   first would create farms with wrong areas that a later migration cannot repair. The original
   boundary is the only correct input, and by then the wrong area has already reached reports.
5. **The area unit stays as it is.** Feddan is an Egyptian unit. Whether a farm outside Egypt
   should default to hectare is a product question, not part of this track.

### In scope

- A new tenant migration that adds a `utm_srid` column to `farms`, backfills it with 32636,
  widens `farms.boundary_utm` and `blocks.boundary_utm` to accept any SRID, and replaces both
  trigger functions to read the stored zone instead of the literal.
- A helper that derives the zone from a longitude and a latitude, called by `create_farm` to
  set `farms.utm_srid` on insert.
- Removal of the country check from `farms/geometry.py`, `farms/errors.py`, the bulk-import
  `out_of_egypt` error code in `farms/service.py`, `frontend/src/lib/geometry.ts`, the three
  form handlers, and the English and Arabic text.
- Tests: a farm created outside Egypt gets an area within 0.1% of the true area; its blocks and
  its grid use the farm's zone; an existing Egyptian farm's `aoi_hash` does not change.

### Out of scope (must not build)

- Re-zoning existing Egyptian farms west of longitude 30. Their imagery is linked by
  `aoi_hash`.
- Letting the user pick a projection.
- Changing the default area unit per country.
- Any change to the imagery provider footprint or to weather coverage. Whether Sentinel-2 and
  Open-Meteo return usable data for the new location is a separate check.

### Definition of done (the gate)

1. How large is a farm in Riyadh, in hectares, and does that number match an outside source
   within 0.1%?
2. What is the `aoi_hash` of an existing Egyptian block before and after the migration, and are
   the two values the same?
3. What SRID does `grid_configs.utm_srid` hold for a block on a farm outside Egypt?
4. Can the same boundary be rejected by the browser and accepted by the API, or the reverse?

### Known traps (repo-specific)

- Tenant migrations run once per tenant schema. Check the highest tenant migration number on
  `origin/main` immediately before naming a new one. That race has been lost three times.
- `ALTER TABLE ... ALTER COLUMN boundary_utm TYPE geometry(MultiPolygon, 0)` needs a `USING`
  clause. The column is not empty.
- Both trigger functions must be replaced in one migration. Replacing only the block trigger
  gives a farm and its blocks two different coordinate systems.
- The browser and the API hold the same four numbers with no test tying them together. The two
  copies drift and nothing fails until a user sees it.
- `ST_Transform` returns a finite wrong number outside the zone. There is no error to catch and
  no log line to search. Only a comparison against a known area shows the fault.

### Open questions (answer before the first PR)

1. How many farms in production sit west of longitude 30, and how much imagery history would a
   later re-zoning have to rebuild?
2. Does the imagery pipeline assume one SRID anywhere else? `grid/` reads it from the block,
   but the STAC search, the raster write path, and the tile server were not read in this
   session.
3. Should a farm outside Egypt default to hectare instead of feddan?

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
| Guard `_verify` so a failed verification cannot report a *committed* purge as `failed` | `backend/app/modules/purge/service.py:449` | The trigger is already gone: #484 moved the orphan scan onto an autocommit connection and counts hypertables chunk-by-chunk, so the lock exhaustion that used to break it no longer fires. What remains is latent shape, costing nothing today. `_verify` runs **after** the row deletion has committed and after storage + STAC cleanup, yet it sits unguarded inside the outer `except`, which marks the job `failed` and re-raises — so *any* future scan error would file an irreversible, genuinely successful purge as a failure, and the receipt would be the only record. The fix is to catch around it and record `{"error": …}` on the receipt, exactly as `tenancy/service.py:1097` already does for the same scanner. | Any PR touching the purge module |

---

*This is a discipline document. Skipping steps invalidates the approach.*
