# Prompt 3 — Slice 2: Imagery and Indices

> **How to use this prompt**
> Paste the entire content below the `---` line into Claude Code as the first user message of a fresh session. The repository is `msoliman1975/MissionAgre`. Prompts 1 and 2 must be merged to `main` before starting Prompt 3 — this prompt assumes Slice 1 (farms / blocks / crop assignments / attachments / cross-schema FK consistency-check) is in place and green.

---

# Mission

You are building **Slice 2: Imagery and Indices** of MissionAgre. By the end of this prompt, a tenant user can subscribe a block to a Sentinel-2 product, the Celery pipeline pulls the matching scene through the Sentinel Hub Process API, computes the six standard vegetation indices, writes COGs to S3 and aggregates per-scene statistics into a TimescaleDB hypertable, the frontend renders the NDVI raster as an overlay on the block map, and a per-block trend chart shows index values over the available scenes — in both `en` (LTR) and `ar` (RTL).

This is the second **vertical slice** through the foundation. No alerts, no recommendations, no weather, no signals, no dashboards — those come in Prompts 4–5.

# Mandatory first step

**Before writing any code:**

1. Read `docs/ARCHITECTURE.md` end to end (binding) — pay particular attention to § 3 (stack), § 5 (tenancy model), § 6 (module boundaries), § 9 (imagery pipeline), and § 12 (areas/units).
2. Read `docs/data_model.md` § 6 (`imagery` module) end to end (binding spec for every table, column, index, hypertable, retention rule).
3. Read `docs/data_model.md` § 7 (`indices` module) end to end — including the continuous-aggregate definitions in § 14.
4. Read `docs/data_model.md` § 1 (conventions), § 5.5 (`blocks` and the `aoi_hash` column — **load-bearing for idempotency**), § 13 (`audit`), § 15.1 (deferrable FKs), § 15.2 (multi-schema migrations).
5. Read `prompts/roadmap.md` § Prompt 3 to confirm scope.
6. Read `prompts/prompt_02_farm_management.md` to understand the foundation Slice 1 already provides — events, capabilities, RBAC, audit, attachments storage primitive, frontend module shell.
7. Inspect the codebase:
   - `backend/app/modules/imagery/` and `backend/app/modules/indices/` (currently empty `__init__.py`, `events.py`, `service.py` stubs — your starting point).
   - `backend/app/modules/farms/events.py` — `BlockBoundaryChangedV1` is the trigger this slice subscribes to.
   - `backend/app/shared/storage/` — the boto3 wrapper added in Slice 1 PR-C; reuse it for COG upload/presign, **do not reinvent**.
   - `backend/app/shared/conditions/` (does not exist yet — out of scope; alerts/recommendations build it in Prompt 4).
   - `backend/migrations/public/versions/` and `backend/migrations/tenant/versions/` — extend, do not parallel.
   - `backend/workers/celery_factory.py` and `backend/workers/beat/main.py` — both are wired and live; add tasks via the existing `_TASK_PACKAGES` list and Beat schedule entries.
   - `tile-server/` — the TiTiler image is already containerized; this prompt configures the runtime and wires it into the frontend, not a new image.
   - `frontend/src/modules/farms/` — model your new `imagery` and `indices` frontend folders on this layout (pages + components + i18n + tests).

If anything you are about to do contradicts `ARCHITECTURE.md` or `data_model.md`, **stop and open an ADR in `docs/decisions/`**. Do not silently substitute your judgment.

# Operating rules for this session

1. **Stay strictly within the "in scope" list.** If you find yourself wanting to build something on the "out of scope" list, stop and confirm.
2. **Do not invent table columns or hypertable settings.** Every column, type, constraint, index, hypertable config, and continuous aggregate is in `data_model.md` §§ 6–7 and § 14. If something feels missing, ask before adding.
3. **Module boundaries are non-negotiable.** No reads of another module's tables. No imports of another module's internals. The `import-linter` contract written in Prompt 1 is the law. The `imagery` and `indices` modules each expose only their `service.py` Protocol(s) and `events.py` types.
4. **Use existing primitives.** `get_db_session`, the JWT middleware, the RBAC decorator, the event bus, the audit recorder, the structured logger, the correlation-ID middleware, the i18n setup, `app/shared/storage/` for S3, `app/shared/conditions/` (later) — all already exist (or will) from prior prompts. Use them.
5. **Sentinel Hub credentials are runtime config, never committed.** Plan:

   - `app/core/settings.py` adds five fields, all empty-by-default so dev fails closed if no credentials are wired:
     - `sentinel_hub_client_id: str = ""`
     - `sentinel_hub_client_secret: str = ""`
     - `sentinel_hub_oauth_url: str = "https://services.sentinel-hub.com/oauth/token"`
     - `sentinel_hub_catalog_url: str = "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search"`
     - `sentinel_hub_process_url: str = "https://services.sentinel-hub.com/api/v1/process"`
   - `SentinelHubProvider.__init__` raises `SentinelHubNotConfiguredError` (a clear `APIError` subclass) when `client_id` or `client_secret` is empty. The Celery `discover_scenes` task catches it and writes a `failed` job row with `error_message="sentinel_hub_not_configured"` so dev clusters without creds surface the misconfiguration loudly instead of silently skipping work.
   - **Local dev** (compose, docker, host run): values live in `infra/dev/.env` (gitignored, sample at `infra/dev/.env.example` with placeholder strings). The compose service reads them via `env_file:`. Same pattern as the existing `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`. **Do not commit real creds** to `.env.example`; commit `# fill from 1Password / Bitwarden vault entry "missionagre/sentinel-hub-dev"` style placeholders.
   - **Dev / staging / production clusters** (k8s): a `Secret` named `missionagre-sentinel-hub` carries the four sensitive values; the API + worker Deployments mount it via `envFrom: - secretRef: missionagre-sentinel-hub`. The Secret itself is owned by **External Secrets Operator** (already used for the Postgres + Keycloak creds from Prompt 1), pulling from AWS Secrets Manager paths `missionagre/<env>/sentinel-hub/*`. Add the `ExternalSecret` manifest under `infra/helm/shared/templates/sentinel-hub-externalsecret.yaml`.
   - **Tests** never hit real Sentinel Hub. A `pytest` fixture injects fake credentials; `respx` mocks the HTTP layer with recorded fixtures committed under `backend/tests/fixtures/sentinel_hub/`.
6. **Idempotency is a first-class concern.** Every ingestion job is keyed by `(subscription_id, scene_id)`; every COG asset is keyed by `{provider}/{product}/{scene_id}/{aoi_hash}/{index_or_band}.tif` per ARCHITECTURE.md § 9. Re-running an ingestion **must** be a no-op except for `last_attempted_at` updates. The `aoi_hash` on `blocks` (computed by the trigger from Slice 1) is the load-bearing identifier — do not regenerate or re-hash.
7. **Four PRs, in order.** PR-A backend migrations + provider catalog, PR-B Sentinel Hub adapter + ingestion pipeline, PR-C indices computation + aggregates + tile-server, PR-D frontend. Each must be reviewed and merged before the next opens. See § "Sequencing" below.
8. **Conventional commits, squash-merge, branch-based.** `feat(imagery): ...`, `feat(indices): ...`, `feat(frontend/imagery): ...`, `chore(migrations): ...`, `chore(tile-server): ...`.
9. **Tests are not optional.** Unit tests for every service method (mock the Sentinel Hub HTTP layer); integration tests for ingestion idempotency, hypertable inserts, and continuous-aggregate refresh; one end-to-end test for the gate criteria.
10. **When you're stuck on a 50/50 call, ask.** Better five questions than one wrong direction.

# Sequencing — four PRs

## PR-A: backend imagery + indices migrations and provider catalog

Branch: `feat/imagery-foundation`. Scope:

- Public migration: `pgstac` extension; `imagery_providers` and `imagery_products` tables; `indices_catalog` table; seed rows for `sentinel_hub` provider, the Sentinel-2 L2A product, and the six standard indices.
- Tenant migration: `imagery_aoi_subscriptions`, `imagery_ingestion_jobs`, `block_index_aggregates` (TimescaleDB hypertable per § 7.3), the daily and weekly continuous aggregates from § 14, RLS policy on `pgstac.items` per § 6.6.
- ORM models for the new tables in `app/modules/imagery/models.py` and `app/modules/indices/models.py`.
- Pydantic schemas + the **Protocol** (`ImageryService`, `IndicesService`) — empty service implementations are acceptable here; PR-B/C fills them.
- Settings additions for Sentinel Hub credentials + cloud-cover thresholds (`imagery_cloud_cover_visualization_max_pct=60`, `imagery_cloud_cover_aggregation_max_pct=20` per ARCHITECTURE.md § 9).
- RBAC: capabilities `imagery.read`, `imagery.refresh`, `index.read`, `index.compute_custom`, plus `imagery.subscription.manage` already mapped in `role_capabilities.yaml` from Prompt 1 — verify and extend if anything's missing.
- Unit tests for migrations (verify hypertable, continuous-aggregate views, indices catalog seed) using the testcontainers fixture re-enabled by the post-PR-A integration unblock.

## PR-B: Sentinel Hub adapter + ingestion pipeline

Branch: `feat/imagery-sentinel-hub`. Scope:

- `app/modules/imagery/providers/sentinel_hub.py` — `SentinelHubProvider` implementing the `ImageryProvider` Protocol from § 9: OAuth2 client-credentials flow, cached token, paginated `/api/v1/catalog/search` for scene discovery, `/api/v1/process` for raster acquisition with a UTM-32636 output CRS request.
- Celery task chain (`workers.tasks.imagery`):
  - `discover_scenes(subscription_id)` — Beat-driven; calls the provider's `discover()`, creates `imagery_ingestion_jobs` rows in `pending` for new scenes.
  - `acquire_scene(job_id)` — picks up a pending job, calls `provider.fetch()` for raw bands, writes the multi-band COG to S3 at the deterministic key, sets `started_at`/`status='running'`.
  - `register_stac_item(job_id)` — inserts a `pgstac.items` row in the right collection (auto-creating the collection on first use), references the COG asset.
  - On any step failure, set `status='failed'` + `error_message`, audit, emit `IngestionFailedV1`.
  - On `cloud_cover_pct > imagery_cloud_cover_visualization_max_pct`, short-circuit to `status='skipped_cloud'` per § 6.5.
- Beat schedule entry: `imagery.discover_active_subscriptions` running at the longest configured cadence in dev (default hourly).
- On-demand refresh endpoint: `POST /api/v1/blocks/{block_id}/imagery/refresh` (capability `imagery.refresh`) — enqueues `discover_scenes` for the matching active subscription, returns the queued job id(s).
- Subscription endpoints: `POST/GET/DELETE /api/v1/blocks/{block_id}/imagery/subscriptions` (capability `imagery.subscription.manage`) — wire `imagery_aoi_subscriptions` lifecycle.
- Subscribe `BlockBoundaryChangedV1` (from Slice 1) → invalidate cached scenes for that block by setting `imagery_aoi_subscriptions.last_successful_ingest_at = NULL` so the next discovery refetches with the new aoi_hash. **Do not delete past `imagery_ingestion_jobs` rows** — the historical record stays.
- Events: `SubscriptionCreatedV1`, `SubscriptionRevokedV1`, `SceneDiscoveredV1`, `SceneIngestedV1`, `SceneSkippedV1`, `IngestionFailedV1`. Subscribe `audit.record(event)` to all of them.
- Tests: unit (mock httpx for Sentinel Hub OAuth + catalog + process; mock `app.shared.storage` for S3 writes) and integration (`testcontainers` Postgres + a recorded HTTP response cassette via `respx` or `vcrpy` — pick one, document the choice in an ADR if you go beyond `respx` which is the lighter option).

## PR-C: indices computation + aggregates + tile-server wiring

Branch: `feat/imagery-indices-and-tiles`. Scope:

- `app/modules/indices/computation.py` — pure function library taking a raw-bands COG path, returning per-index COGs and the aggregate statistics (`mean`, `min`, `max`, `p10`, `p50`, `p90`, `std_dev`, `valid_pixel_count`, `total_pixel_count`, `cloud_cover_pct`) per `data_model.md` § 7.3. Implement with `rasterio` + `numpy`. **Six standard indices only** per ARCHITECTURE.md § 9 — NDVI, NDWI, EVI, SAVI, NDRE, GNDVI.
- Celery task `compute_indices(job_id)` chained after `register_stac_item`:
  - Read the raw-bands COG via `rasterio` over `s3://`.
  - Compute each of the six index rasters; write each as its own COG to S3 at the deterministic key.
  - Compute aggregates against the `valid_pixel_count` (post-cloud-mask, post-AOI-mask) and insert one row per index into `block_index_aggregates`.
  - Update the corresponding `pgstac.items` row's assets to reference the new index COGs.
  - Emit one `IndexAggregatedV1` event per index.
  - On `valid_pixel_pct < imagery_cloud_cover_aggregation_max_pct`, mark the row but skip the alert/recommendation triggers (those will look at `valid_pixel_pct` themselves in later slices — your job is to compute, not gate).
- Tile-server config: a `ConfigMap` (or `tile-server/config/`) mounted into the TiTiler container giving it the bucket name and the path-style endpoint. Add a tile-server endpoint URL setting on the API (`tile_server_base_url`) so the frontend gets it from `/api/v1/me`-equivalent or a small `/api/v1/config` endpoint.
- Read endpoints:
  - `GET /api/v1/blocks/{block_id}/indices/{index_code}/timeseries?from=&to=&granularity=daily|weekly` (capability `index.read`) — reads from the daily/weekly continuous aggregate per granularity.
  - `GET /api/v1/blocks/{block_id}/scenes?from=&to=` (capability `imagery.read`) — paginated; one row per `imagery_ingestion_jobs` with its `stac_item_id`, status, cloud cover, and a list of asset tile-URL templates.
- Migrations: any indexes / hypertable tweaks that fall out of the test data — likely none if PR-A nailed § 7.3.
- Tests: unit (mocked rasterio against a tiny in-memory ndarray fixture for each index formula; assertions on aggregate stats), integration (insert into hypertable, refresh the daily continuous aggregate, query through the API).

## PR-D: frontend imagery overlay + trend chart + scene picker

Branch: `feat/imagery-frontend`. Scope:

- New deps: `deck.gl`, `@deck.gl/geo-layers`, `@deck.gl/react`, `recharts`, `date-fns` (or `dayjs` — pick one, default `date-fns` for tree-shaking).
- React pages:
  - Update `BlockDetailPage` to add an **Imagery** card with: a date picker (or scrubber) showing dates for which scenes exist, an **NDVI overlay** rendered via deck.gl `BitmapLayer` reading tiles from the tile server's XYZ template, and a small "Refresh" button (gated by `imagery.refresh`).
  - A new **Trend** card on `BlockDetailPage` showing the daily NDVI mean over the last 90 days using Recharts `<LineChart>`, with selectable granularity (daily/weekly) and selectable index (combobox: NDVI/NDWI/EVI/SAVI/NDRE/GNDVI).
  - A `SubscriptionsTab` (analogous to the Slice 1 `MembersList`) on `BlockDetailPage` for subscribing/unsubscribing to products. For MVP only the Sentinel-2 L2A product is selectable.
- Typed API clients in `frontend/src/api/`: `imagery.ts` (refresh, list scenes, subscriptions), `indices.ts` (timeseries).
- New i18n namespaces: `imagery` and `indices` in `en/` and `ar/` JSON. **Translate every label, button, validation message, empty-state, axis label.** Numbers via `Intl.NumberFormat` with the active locale (Latin digits in `ar-EG` per ARCHITECTURE.md § 11).
- RBAC-aware UI: hide the Refresh button without `imagery.refresh`; hide the SubscriptionsTab without `imagery.subscription.manage` (read-only with `imagery.read`).
- Tile-server URL is fetched from a small `GET /api/v1/config` (or piggy-backed onto `/api/v1/me`) and cached in a React context. The frontend never hard-codes the tile URL.
- Tests: vitest unit tests for the timeseries client, the index-formula display helper, and the date-picker bounds; React Testing Library tests per page in `en` and `ar`; one Playwright test (encouraged, optional) for the gate criteria.

# What you are building (in scope)

## Backend (`backend/app/modules/imagery/` and `backend/app/modules/indices/`)

### Tables

Implement exactly as specified in `data_model.md` §§ 6–7 — no additions, no omissions:

- `public.imagery_providers` (§ 6.2) — shared catalog
- `public.imagery_products` (§ 6.3) — shared catalog
- `public.indices_catalog` (§ 7.2) — shared catalog
- `imagery_aoi_subscriptions` in tenant schema (§ 6.4)
- `imagery_ingestion_jobs` in tenant schema (§ 6.5)
- `block_index_aggregates` in tenant schema as a **TimescaleDB hypertable** (§ 7.3)

### Migrations

- `backend/migrations/public/versions/<rev>_pgstac_and_imagery_catalog.py` — enable `pgstac` extension; create `imagery_providers`, `imagery_products`, `indices_catalog`; seed Sentinel Hub provider, Sentinel-2 L2A product, six standard indices.
- `backend/migrations/tenant/versions/<rev>_imagery_subscriptions_and_indices.py` — `imagery_aoi_subscriptions`, `imagery_ingestion_jobs`, `block_index_aggregates` hypertable, the daily and weekly continuous aggregates per § 14, refresh policies. The pgstac RLS policy from § 6.6 lives here too (per-tenant schema attaches the policy).
- A separate seed script (or Python CLI in `scripts/`) for the indices catalog if not inlined in the migration.

### Sentinel Hub adapter

`SentinelHubProvider` in `app/modules/imagery/providers/sentinel_hub.py`:

- OAuth2 client-credentials with token caching (token TTL = 60 min; refresh at 50 min).
- `discover(aoi_geojson, time_window, product_id)` → list of scene metadata dicts (`scene_id`, `scene_datetime`, `cloud_cover_pct`, `geometry`).
- `fetch(scene_id, aoi_geojson_utm36n, bands)` → bytes (multi-band COG); upload to S3 at the deterministic key.
- All HTTP via `httpx.AsyncClient`. No global state. Constructor injects credentials.

### Celery tasks

In `backend/workers/tasks/imagery.py` or `backend/app/modules/imagery/tasks.py` (mirror the Slice 1 pattern in `app/modules/farms/tasks.py`):

- `discover_scenes(subscription_id)` — light queue, default cadence per `imagery_aoi_subscriptions.cadence_hours`.
- `acquire_scene(job_id)` — heavy queue (downloads).
- `register_stac_item(job_id)` — light queue.
- `compute_indices(job_id)` — heavy queue (rasterio).
- `_handle_failure(job_id, exc)` — common error path that audits + emits `IngestionFailedV1` + sets the row status.

Beat schedules (`workers/beat/main.py`):

- `imagery.discover_active_subscriptions` — sweep all active subscriptions whose `last_attempted_at` is older than `cadence_hours`. Cadence is one hour in dev; production cluster overrides via env.

### REST endpoints

All paths under `/api/v1/`. Tenant context from JWT. RFC 7807 errors. Audit on every state-changing call.

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `POST` | `/blocks/{block_id}/imagery/subscriptions` | `imagery.subscription.manage` | Subscribe a block to a product |
| `GET` | `/blocks/{block_id}/imagery/subscriptions` | `imagery.read` | List subscriptions |
| `DELETE` | `/blocks/{block_id}/imagery/subscriptions/{id}` | `imagery.subscription.manage` | Soft-revoke (`is_active=false`) |
| `POST` | `/blocks/{block_id}/imagery/refresh` | `imagery.refresh` | Trigger discovery now |
| `GET` | `/blocks/{block_id}/scenes` | `imagery.read` | List ingested scenes (paginated) |
| `GET` | `/blocks/{block_id}/indices/{index_code}/timeseries` | `index.read` | Continuous-aggregate read |
| `GET` | `/api/v1/config` | any tenant-scoped JWT | Serve the tile-server base URL + supported indices for the UI |

Cursor pagination (`?cursor=&limit=`, default 50, max 200) per ARCHITECTURE.md § 8.

### RBAC

Capabilities required (verify each is in `app/shared/rbac/capabilities.yaml` and mapped in `role_capabilities.yaml`; all should already exist from Prompt 1):

```
imagery.read
imagery.refresh
imagery.subscription.manage   # if absent, add: TenantOwner/Admin/FarmManager grant; Agronomist+below grant only `imagery.read`
index.read
index.compute_custom
```

Per-farm resolution (PlatformRole → TenantRole → FarmScope) is mandatory for every block-scoped endpoint.

### Events

In `app/modules/imagery/events.py` (versioned `...V1`):

- `SubscriptionCreatedV1 { subscription_id, block_id, product_id, actor_user_id }`
- `SubscriptionRevokedV1 { subscription_id, block_id }`
- `SceneDiscoveredV1 { job_id, subscription_id, block_id, scene_id, scene_datetime, cloud_cover_pct }`
- `SceneIngestedV1 { job_id, block_id, scene_id, stac_item_id, valid_pixel_pct }`
- `SceneSkippedV1 { job_id, reason }`  # `reason in ('cloud','duplicate','out_of_window')`
- `IngestionFailedV1 { job_id, error }`
- `IndexAggregatedV1 { block_id, index_code, time, valid_pixel_pct }`

Subscribe `audit.record(event)` to all of them.

### Audit

Every state-changing endpoint AND every Celery task that transitions an ingestion job's status must produce an audit row via `audit.record(event_type, subject_kind, subject_id, before, after, actor_user_id, correlation_id)`. Use the interface from Prompt 1; do **not** insert directly into `audit_events`.

For Celery tasks, the actor is `system` per audit's existing convention (no `actor_user_id`).

### Service layer + Protocol

Per `ARCHITECTURE.md` § 6.1:
- `ImageryService` Protocol in `app/modules/imagery/service.py` with public methods (subscriptions, refresh, list scenes).
- `IndicesService` Protocol in `app/modules/indices/service.py` (timeseries reads, aggregate-row inserts that the imagery pipeline calls).
- `ImageryProvider` Protocol in `app/modules/imagery/providers/protocol.py` (the adapter contract). `SentinelHubProvider` implements it.
- Implementations live next to the Protocol. Other modules consume the Protocols, not the implementations.

### Tile server

- TiTiler runtime config (already containerized) gets:
  - `S3_BUCKET` and `AWS_S3_ENDPOINT_URL` from environment / Helm values.
  - CORS allowing the frontend origin.
  - Max zoom + minimum zoom appropriate for our 10m-resolution data.
- Add a Helm chart entry under `infra/helm/tile-server/` if it doesn't already exist (Prompt 1 may have stubbed it; verify).
- The frontend reads the tile-server URL via `GET /api/v1/config` — never hard-coded.

### Tests

- **Unit tests** for: index formulas (small ndarray fixtures); Sentinel Hub adapter happy path + 4xx/5xx error paths (`respx`-mocked HTTPS); subscription service methods; aggregation math; deterministic-asset-key generation.
- **Integration tests** (testcontainers Postgres):
  - Hypertable inserts produce the expected rows; `valid_pixel_pct` is computed correctly.
  - Daily continuous aggregate refresh is observable.
  - Idempotency: running `discover_scenes` twice with the same `(subscription, scene)` pair produces zero new jobs.
  - `BlockBoundaryChangedV1` invalidates `last_successful_ingest_at` and the next discovery refetches.
  - RLS on `pgstac.items` blocks cross-tenant reads.
  - All RBAC matrices: Viewer can read scenes/timeseries; Agronomist cannot trigger refresh; cross-tenant access returns 404.

## Frontend (`frontend/src/modules/imagery/` and `frontend/src/modules/indices/`)

### Routes

No new top-level routes — the imagery UI lives inside `BlockDetailPage`. New components:

- `<ImageryPanel>` (overlay + scene picker + refresh button)
- `<IndexTrendChart>` (Recharts) — selectable index + granularity
- `<SubscriptionsList>` and `<SubscribeForm>` (the only non-Slice-1 form on this page)

### Map overlay

- deck.gl `BitmapLayer` (or `TileLayer` with `BitmapLayer` sublayer) overlaid on the existing MapLibre block-detail map.
- The tile URL template comes from the `/api/v1/config` response. The frontend interpolates `{collection_id}/{item_id}/{asset}` and `{z}/{x}/{y}` per TiTiler's path convention.
- Visual: 0–1 scale ramp for NDVI; the legend is a simple gradient component beside the map.

### Trend chart

- Recharts `<LineChart>` with `<XAxis dataKey="time">` and `<YAxis>` whose domain matches the index's `value_min`/`value_max` from the catalog.
- Tooltip shows the date in the active locale and the value to 3 decimals.
- Empty state: "No scenes ingested yet" with a CTA button (gated by `imagery.refresh`) that calls the refresh endpoint.

### i18n

- New namespaces `imagery` and `indices` with `en/` + `ar/` JSON.
- Strings for: every label, button, validation message, empty-state, confirmation dialog, axis label, tooltip. **No hardcoded English in JSX.**
- Index names from `public.indices_catalog.name_ar` when `i18n.language === 'ar'`, else `name_en`. (Same pattern as Slice 1's `CropPicker`.)

### Tests

- Vitest unit tests for the typed API clients, the trend-chart-data helper, the tile-URL builder.
- React Testing Library tests per new component: renders correctly in `en` and `ar`; capability gating shows/hides the refresh button and the SubscriptionsList write controls.
- **One Playwright test** (optional but recommended) for the gate criteria below: sign in → open a block → ingest a recorded-cassette scene → see the NDVI overlay → switch to `ar` and confirm the legend translates.

# What is explicitly out of scope (do NOT build)

- Self-managed Sentinel-2 pipeline (only the Sentinel Hub Process API in MVP).
- Planet, Airbus, premium-imagery providers.
- Custom on-demand indices (`indices_catalog.is_standard=false`) — Prompt 4 if at all; for now only the six.
- Cloud-mask soft-mode / inpainting.
- Reprocessing of historical scenes outside the ingestion window.
- Alert rules, recommendations, decision trees (Prompt 4).
- Weather, signals, dashboards (Prompt 5).
- Mobile offline app.
- Webhook-based ingestion triggers (Beat polling only per ARCHITECTURE.md § 9).
- Bulk subscription import via CSV.

If you find yourself wanting to add something not listed in "in scope," **stop and confirm**.

# Definition of done — your gate

You are done with Prompt 3 when **all** of the following are true. Provide evidence in the final PR description.

1. PR-A, PR-B, PR-C, PR-D are all merged to `main`. CI is green on each. Container images for `api`, `workers`, `tile-server`, `frontend` rebuilt and pushed.
2. ArgoCD has synced `dev`. `kubectl get pods -A` shows all pods `Running` (no crash loops). The tile-server ingress responds to a `/healthz` probe. The frontend ingress serves the new pages.
3. **Subscription:** a `TenantAdmin` user signs in via the dev Keycloak, navigates to a block, subscribes it to the Sentinel-2 L2A product. A row appears in `imagery_aoi_subscriptions`.
4. **Discovery:** the Beat schedule (or the manual refresh button) triggers `discover_scenes`. New `imagery_ingestion_jobs` rows appear with `status='pending'`.
5. **Acquisition + storage:** within one Beat cycle (or via the manual refresh path) a real Sentinel Hub fetch produces a multi-band COG in S3 at the deterministic key. The corresponding job row transitions `pending → running → succeeded` and `assets_written` is populated.
6. **STAC registration:** a new `pgstac.items` row exists in the right collection. RLS prevents tenant B from reading it.
7. **Indices:** six per-index COGs exist in S3 (NDVI/NDWI/EVI/SAVI/NDRE/GNDVI) and six rows appear in `block_index_aggregates` for that scene's `time` and `block_id`.
8. **Idempotency:** re-running the same job (force the same `scene_id` + `subscription_id`) produces no new rows in `imagery_ingestion_jobs` or `block_index_aggregates`. A scene above the cloud-cover threshold is correctly recorded as `status='skipped_cloud'` with no per-index aggregates.
9. **Boundary invalidation:** editing the block's boundary (Slice 1 endpoint) causes `imagery_aoi_subscriptions.last_successful_ingest_at` to reset and the next discovery to refetch — verifiable by changes in `aoi_hash` and a fresh STAC item.
10. **Frontend overlay:** the NDVI raster renders on the block map at the right geographic position; switching the date picker swaps the displayed scene; the refresh button is hidden for `Viewer` and visible for `FarmManager`.
11. **Trend chart:** the chart shows at least one point; the granularity selector switches between the daily and weekly continuous aggregates; the index selector swaps formulas correctly.
12. **i18n + RTL:** every page/component renders correctly in both `en` (LTR) and `ar` (RTL). Axis labels and tooltips translate. No hardcoded English. Logical CSS only. Provide screenshots in both locales.
13. **Audit trail:** every state-changing endpoint AND every Celery state transition produced an audit row with correct `subject_kind`, `subject_id`, `actor_kind`, `correlation_id`. Provide a sample query output.
14. **RBAC enforcement:**
    - A `Viewer` on a farm cannot trigger refresh (UI control hidden; API returns 403).
    - An `Agronomist` cannot manage subscriptions; can read scenes and the trend.
    - A user with no scope on a block sees the block only if they are `TenantAdmin`/`TenantOwner`.
15. **Cross-tenant isolation:** a user in tenant T1 attempting to query scenes/timeseries with an arbitrary `block_id` belonging to tenant T2 receives 404 from the API and an empty result from raw SQL through the request session. The pgstac RLS policy is also exercised in an integration test.
16. **Tests:**
    - Backend: ≥85% line coverage on `app/modules/imagery/` and `app/modules/indices/` and the new migrations. Integration tests cover all gate criteria 4–9 + 14–15.
    - Frontend: every new page/component has a render test in `en` + `ar`. The trend-chart-data helper, the tile-URL builder, and the Sentinel Hub provider's HTTP layer are unit-tested.
17. **Module boundaries:** `import-linter` passes. `imagery` does not read `farms`, `indices`, or `audit` tables. `indices` does not import from `imagery` internals (subscription IDs flow via Protocol method args).
18. **OpenAPI:** `/openapi.json` includes all new endpoints with correct schemas, examples, and RFC 7807 error responses. The frontend's typed API client (regenerated from OpenAPI if you went that route) compiles.

# Reporting back

In each PR description:

- Link to the issue it closes (or describe the gate item it delivers).
- Migration files changed and any irreversible changes called out (especially hypertable and continuous-aggregate definitions).
- Screenshots for any UI work (en + ar).
- Test coverage summary.
- Any deviations from `data_model.md` or `ARCHITECTURE.md` — and the ADR opened for them.

In the final (PR-D) description, additionally:

- The full gate-criteria checklist with evidence per item.
- A short "what's next" note: anything Prompt 4 (alerts) will need that came up while building this slice — particularly which `block_index_aggregates` columns the rule engine should index against.

# When to stop and ask

- Sentinel Hub returns a scene with no usable bands (all-zero), or with a band layout that doesn't match what the catalog says — schema or provider catalog needs to change, ask first.
- The `pgstac` extension's tenant-isolation story per ARCHITECTURE.md § 6.6 fights an actual production query; that's an ADR-worthy moment.
- TiTiler can't read COGs from MinIO with the current path-style endpoint config — there's a known foot-gun around `AWS_VIRTUAL_HOSTING=FALSE` and `AWS_HTTPS=NO`; if you trip on it, ask before changing the Helm values.
- A continuous-aggregate refresh policy fights the chunk-interval choice (cf. § 7.3 vs § 14) — that's a data-model question for the human.
- Your computed NDVI for a known test scene drifts more than 0.02 from a hand-checked reference — possible band-order bug; ask before "fixing the formula".
- Any cross-module import would be the simplest way out — that's a sign the design is wrong; ask.
- A test failure that suggests a foundation bug rather than a slice bug. (Several were found in Slice 1's coverage push — same pattern: investigate, don't paper over.)

I'd much rather answer five questions than rebuild a slice.

---

Begin by reading the referenced documents and the existing scaffolding under `backend/app/modules/imagery/`, `backend/app/modules/indices/`, `backend/workers/`, and `tile-server/`. Then propose the precise file plan for PR-A (which migrations, which models, which seed rows, which tests) and wait for my approval before writing code.
