# Integration Health — Depth Pass

**Status:** Proposal — not yet implemented.
**Branch (planned):** `feat/integration-health-depth`
**Predecessor work:** PR-Set2 (`d5a08fa`) added the read-only farm/block health views; Reorg7 (`7e80595`) added the cross-tenant rollup.

## Problem

Both **PlatformAdmin** and **TenantOwner** today land on `/platform/integrations/health` and `/settings/integrations/health` and see a flat summary: active subs, last sync timestamp, a 24h failure count for imagery. That is enough to ask "is something broken?" — it is not enough to answer **why**, **what is queued**, **what just ran**, or **is the provider itself up?**

Concretely missing today:
- No per-attempt history for weather. `weather_subscriptions` only stores `last_successful_ingest_at` + `last_attempted_at`. A failed sync leaves no row anywhere.
- Imagery has a real execution log (`imagery_ingestion_jobs.status` transitions through `requested → running → completed|failed`) but we never surface it to the UI.
- No queue concept for weather; imagery's queue is buried in the same `imagery_ingestion_jobs` table but not exposed.
- No liveness check on the providers themselves. If OpenMeteo returns 500 for an hour, we learn about it only via per-block failures piling up.

## Goals

1. **Drill-down + history** — click a Farm or Block, see the last N attempts for weather and imagery with status, duration, and the error reason if it failed.
2. **Pipeline / queue view** — show what is overdue (next sync due in the past), what is running now, and what is stuck (running too long).
3. **Periodic provider probes** — every few minutes, ping each configured provider with a cheap call; surface red/green status per provider.
4. **Same depth for TenantOwner as PlatformAdmin within their tenant** — single React UI, mounted under both `/settings/integrations/health` and `/platform/integrations/health/tenants/:id`.

## Non-goals (V1)

- **No operator actions.** No pause/resume, no manual retry, no force-refresh buttons. Read-only. Operator actions get a follow-up proposal once we know which actions are actually wanted in practice.
- **No quota tracking.** Provider probes return up/down only; parsing Sentinel Hub rate-limit headers / OpenMeteo daily quotas is deferred. We will leave a `quota_used_pct` column nullable in `provider_probe_results` so the follow-up can fill it in without a migration.
- **No alerting.** The notifications subsystem already fires on individual ingestion failures; this proposal just adds *visibility* surfaces. Alerting rules off the new attempt log are a follow-up.
- **No platform impersonation.** PlatformAdmin viewing a tenant's drill-down hits the same APIs with their own JWT (which carries `platform.*` caps, gated separately).

## Locked decisions

These came out of the clarification round; recorded so we do not relitigate.

1. **Add the weather attempt log now** — new per-tenant table, written by every `fetch_weather` Celery task. Do not settle for `last_error_message` columns; we want history.
2. **Same depth for TenantOwner** — single UI, tenant-scoped via JWT. PlatformAdmin gets a tenant picker on top and otherwise sees identical screens.
3. **Probes, not just reactive** — scheduled probe task per provider, stored in `public.provider_probe_results`. Providers are global so the table is in `public`, not per tenant.
4. **No operator actions in V1.** Read-only across the board.

## Data model

### Per-tenant schema additions

```
weather_ingestion_attempts                    (new)
  id                  uuid v7 pk
  subscription_id     uuid fk -> weather_subscriptions(id) ON DELETE CASCADE
  block_id            uuid  -- denormalized for filtering
  farm_id             uuid  -- denormalized
  provider_code       text  -- denormalized
  started_at          timestamptz default now()
  completed_at        timestamptz nullable
  status              text  -- 'running' | 'succeeded' | 'failed' | 'skipped'
  rows_ingested       int   nullable
  error_code          text  nullable  -- short categorized code
  error_message       text  nullable  -- truncated provider message
  duration_ms         int   generated (completed_at - started_at)
  index: (block_id, started_at desc)
  index: (status, started_at desc) where status in ('running','failed')
  retention: trim rows older than 14 days (matches forecast retention)
```

We do **not** drop `weather_subscriptions.last_*_at` — they keep the existing "current state" answer hot without scanning the attempt log.

### Public schema additions

```
provider_probe_results                        (new, in public)
  id                  uuid v7 pk
  provider_kind       text  -- 'weather' | 'imagery'
  provider_code       text  -- matches weather_providers.code / imagery_providers.code
  probe_at            timestamptz default now()
  status              text  -- 'ok' | 'error' | 'timeout'
  latency_ms          int   nullable
  error_message       text  nullable
  quota_used_pct      int   nullable  -- placeholder for V2
  index: (provider_kind, provider_code, probe_at desc)
  retention: trim rows older than 7 days
```

### View changes

Tenant migration **0020** updates the two existing views and adds one:

- `v_farm_integration_health` / `v_block_integration_health`: add columns
  - `weather_failed_24h` (count from `weather_ingestion_attempts` where status='failed' and started_at > now() - 24h)
  - `weather_running_count` (status='running' rows currently)
  - `imagery_running_count` (`imagery_ingestion_jobs.status IN ('requested','running')`)
  - `weather_overdue_count` — subscriptions where `coalesce(last_successful_ingest_at, '-infinity') + cadence_hours * interval '1 hour' < now()`
  - `imagery_overdue_count` — same idea on `imagery_aoi_subscriptions`
- New `v_integration_recent_attempts` — `UNION ALL` of recent weather + imagery attempts, one schema (kind, started_at, status, error_message, block_id, farm_id, provider_code). Limited to last 14 days by view definition; consumers apply their own LIMIT.

## API

All paths under `/api/v1`. Capability gates in parentheses.

### Tenant-scoped (`tenant.read_integration_health` — TenantOwner + TenantAdmin already have it)

- `GET /integrations/health/farms` — existing, extended fields.
- `GET /integrations/health/farms/{farm_id}/blocks` — existing, extended fields.
- `GET /integrations/health/blocks/{block_id}/attempts?kind=weather|imagery&limit=50` — paginated recent attempts for one block.
- `GET /integrations/health/queue?kind=weather|imagery&state=overdue|running|stuck` — pipeline view. `stuck` = `running` for > 30 min (configurable via `platform_defaults`).
- `GET /integrations/health/providers` — tenant-scoped projection: only the providers this tenant has subscriptions to, with their last 24h of probe results aggregated to one row each.

### Platform-scoped (`platform.manage_tenants`)

- `GET /admin/integrations/health` — existing rollup, extended with `weather_failed_24h` + queue counters.
- `GET /admin/integrations/health/providers` — full provider liveness table across every configured provider.
- `GET /admin/integrations/health/probes?provider_code=...&limit=200` — recent probe rows for one provider; deep-link from the providers table.
- `GET /admin/integrations/health/tenants/{tenant_id}/...` — same path shapes as the tenant routes above, scoped to the specified tenant. Internally these set search_path to that tenant and call the same service.

### Capability matrix

| Capability | Who | Routes |
|---|---|---|
| `tenant.read_integration_health` | TenantOwner, TenantAdmin, PlatformSupport | `/integrations/health/*` |
| `platform.manage_tenants` | PlatformAdmin | `/admin/integrations/health/*` |

No new capabilities. The `quota_used_pct` follow-up would not need new capabilities either.

## Provider probes

A new Celery beat task `probe_providers` runs every 5 minutes (configurable via `platform_defaults.provider_probe_interval_minutes`).

- Each provider protocol gets a `probe()` method that returns `ProbeResult(status, latency_ms, error_message)`.
- `OpenMeteoProvider.probe()` — `GET /v1/forecast?latitude=0&longitude=0&hourly=temperature_2m&forecast_days=1`, 5s timeout.
- `SentinelHubProvider.probe()` — OAuth token refresh + `GET /api/v1/catalog/1.0.0/collections`, 5s timeout.
- Results written to `public.provider_probe_results` in the public engine session (no tenant context).

Probes run regardless of tenant subscriptions — providers are global, and a probe failure is meaningful even for tenants who happen not to have an active subscription right now.

## Frontend

Tenant route: `/settings/integrations/health` keeps the URL, gains tabs:

1. **Overview** — current farm/block rollup (existing component), with new badges for `weather_failed_24h` + queue counters.
2. **Runs** — recent attempts table (kind, started_at, status, duration, error_message). Filters: kind, status, farm.
3. **Queue** — three sub-sections: Overdue / Running / Stuck. Each row links to the block detail drawer.
4. **Providers** — liveness panel. Green/yellow/red per provider with last probe latency. Click → recent probe results.

Platform route: `/platform/integrations/health` keeps the cross-tenant rollup as the landing view. Each tenant row links to `/platform/integrations/health/tenants/:id` which mounts the **same four tabs** with the tenant_id baked into the API calls. The Providers tab there shows the **full** provider list (not just the providers this tenant uses).

Components live under `frontend/src/modules/integrationsHealth/` so both portals can import them. The current `IntegrationsHealthPage.tsx` becomes the Overview tab.

## PR breakdown

Seven PRs, each independently deployable. Order matters because the views in PR-IH2 depend on the table from PR-IH1.

| PR | Title | Scope |
|---|---|---|
| **IH1** | weather_ingestion_attempts table + writer | Tenant migration 0020a; wire `weather/tasks.py` + `weather/repository.py` to insert one row per attempt. No API changes. |
| **IH2** | Extended views | Tenant migration 0020b — update v_farm/v_block + add v_integration_recent_attempts. Service + schemas grow new fields; frontend continues to ignore unknown fields. |
| **IH3** | Drill-down API + Runs tab | `GET /integrations/health/blocks/{id}/attempts` + the Runs tab UI. Frontend component reused by platform drill-in (added in IH7). |
| **IH4** | Queue API + Queue tab | `GET /integrations/health/queue` + the Queue tab UI. |
| **IH5** | Provider probes — schema + scheduler | Public migration; `probe()` on each provider protocol; Celery beat task; writer. No API surface yet. |
| **IH6** | Providers API + Providers tab | `GET /integrations/health/providers` + `GET /admin/integrations/health/providers` + Providers tab UI on both portals. |
| **IH7** | Platform tenant drill-in | `/admin/integrations/health/tenants/{id}/...` routes; `/platform/integrations/health/tenants/:id` frontend that mounts the tenant tabs. |

IH3 and IH4 could fold into one PR if we want to ship faster — both are small frontend tabs reading from one new endpoint each.

## Risks

- **Attempt-log write amplification on weather.** Today `fetch_weather` updates two timestamps on each affected subscription. After IH1 it also inserts one row into `weather_ingestion_attempts` per attempt. Volume: roughly 1 row per (farm, provider) pair per cadence — a few hundred rows per tenant per day at typical settings. Retention pruning is required from day one or the table grows unboundedly.
- **Probe task hammering providers.** Five-minute cadence × N providers is fine for OpenMeteo (no quota on a single tiny call) but Sentinel Hub charges per processing unit even for catalog calls. We should confirm Sentinel Hub's catalog endpoint is free / cheap before merging IH5; if not, drop probe cadence to 15 minutes or use an oauth-token-only ping.
- **Probe writes contend with public schema migrations.** Probe inserts use the public engine. If a deploy runs alembic at the same moment a probe writes, the writer should retry on serialization failure. The existing notifications writer has this pattern; reuse it.
- **View column additions can break Pydantic strict mode.** The frontend uses generated types; adding columns to the views requires regenerating the OpenAPI client at the IH2 cut. Standard process for this repo; flagged for completeness.
- **Cross-tenant drill-in path duplicates routes.** The `/admin/integrations/health/tenants/{id}/...` mirror of every tenant route doubles the surface. Acceptable in V1 because the alternative (impersonation tokens) is more invasive. If we add impersonation in a future proposal, these admin mirrors can be deleted.

## Out of scope / explicit deferrals

These are real follow-ups, not "won't ever do":

- Operator actions: pause, retry, force re-sync, rotate credentials.
- Quota tracking on the providers (parse `X-RateLimit-*` / processing-unit counters).
- Alerting rules sourced from the new attempt log (notifications module hook).
- Materialized view backing the cross-tenant rollup once tenants exceed ~100.
- Platform impersonation, which would let PlatformAdmin replace `/admin/integrations/health/tenants/{id}/...` with a direct `/integrations/health/*` call under an impersonated context.

## Open questions

1. **Attempt-log retention window.** 14 days matches forecast retention (per memory: Slice 4 weather decisions). Confirm 14 is right; halving to 7 also reasonable given daily row volume.
2. **"Stuck" threshold.** Proposed 30 min for both weather and imagery. Imagery scenes can legitimately take 10+ min; 30 is a defensible default but should be platform-configurable.
3. **Probe cadence default.** 5 min for OpenMeteo, possibly 15 min for Sentinel Hub depending on cost confirmation. Should both be in `platform_defaults` and per-provider overrideable?
4. **Where does the Providers tab live for tenants?** It shows global provider state — informationally useful (a tenant can tell "weather is down for everyone right now"), but technically it is platform state. Including it gives tenants a "not my fault" signal; excluding it keeps the tenant surface strictly about their own subscriptions. Proposal includes it; flag if you disagree.
