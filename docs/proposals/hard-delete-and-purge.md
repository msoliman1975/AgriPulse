# Hard delete (Purge) for Block / Farm / Tenant

**Status:** BUILT — see § 9 for what shipped and how it differs from the plan
**Date:** 2026-07-29
**Audience:** platform admins (Phase 1); tenant admins for farm/block in Phase 2
**Motivation:** during testing phases we repeatedly create and abandon farms, blocks and whole
tenants. Today none of them can be truly removed, so the environment accretes half-configured
entities and their data. We need a delete that provably leaves nothing behind.

---

## 1. Where we are today

| Entity | "Delete" available | What it actually does |
|---|---|---|
| Block | `DELETE /v1/blocks/{id}` | Alias for inactivate — sets `active_to` + `deleted_at`, runs `apply_block_cascade` (resolves alerts, skips future irrigation/activities, deactivates weather + imagery subs). Fully reversible. |
| Farm | `DELETE /v1/farms/{id}` | Same, plus the block cascade for each child block. |
| Tenant | `POST /v1/admin/tenants/{id}/purge` | Real hard delete: `DROP SCHEMA … CASCADE` + 3 public tables + Keycloak group. |

So we have exactly **one** hard-delete path (tenant purge) and one narrow escape hatch —
`hard_delete_block()` (`backend/app/modules/farms/repository.py:787`), reachable only from the AOI
bulk-replace flow and only when `block_has_dependents()` says the block is pristine.

That escape hatch is the right *shape* and the wrong *scope*: it can only delete a block that owns
nothing, which is never the block you actually want gone after a test run.

### 1.1 What leaks today

Even the tenant purge, the strongest path we have, leaves orphans. From the FK/ownership audit:

**Rows with `tenant_id` / `farm_id` / `block_id` and no FK to cascade off:**

- `public.decision_trees` (+ `decision_tree_versions` via CASCADE) — tenant-authored trees survive a purge forever
- `public.backfill_runs.tenant_id`
- `public.farm_scopes.farm_id` — cross-schema, only cleaned indirectly when the parent membership cascades. `farms/consistency_check.py` *detects* these hourly and deliberately never deletes them
- `public.users` with zero remaining memberships
- Tenant-schema, if we ever delete a farm/block without dropping the schema: `audit_events`,
  `imagery_ingestion_jobs`, `block_index_aggregates`, `block_grid_aggregates`,
  `weather_observations`, `weather_forecasts`, `weather_ingestion_attempts`, `signal_observations`,
  `recommendations.farm_id`, `recommendations_history`

**Non-DB artifacts nothing ever deletes:**

- **Imagery COGs in R2.** `build_asset_key()` produces
  `{provider}/{product}/{scene_id}/{aoi_hash}/{band}.tif` — **no tenant, farm or block component**.
  Ownership is only expressible through `blocks.aoi_hash`, and because `aoi_hash` is derived from
  geometry, two blocks *in different tenants* with an identical AOI share a prefix. A prefix delete
  on purge would be cross-tenant destructive. This is the single hardest part of the problem.
- **pgstac collections and items.** Collection id is `{tenant_schema}__{product_code}`, but pgstac
  lives outside the tenant schema, so `DROP SCHEMA` misses all of it. Nothing in `tenancy/` or
  `platform_admins/` references pgstac at all.
- **Attachments in R2** are fine — `build_attachment_key()` is
  `tenants/{tenant_id}/{farms|blocks}/{owner_id}/attachments/…`, so a prefix delete is exact.
- **Keycloak** is handled but best-effort; a failure logs and moves on.
- **Celery beat** needs nothing — all 14 schedules are global sweeps that re-derive their work from
  `public.tenants` + `blocks.deleted_at IS NULL`. Deleting an entity removes it from the sweep.

**Two structural gotchas the implementation must respect:**

1. **`ON DELETE RESTRICT` on the spine.** `blocks.farm_id`, `blocks.parent_unit_id`,
   `plan_activities.block_id`, `public.tenant_subscriptions.tenant_id` are all RESTRICT. A purge
   must delete in explicit topological order; a naive `DELETE FROM farms` fails.
2. **Timescale continuous aggregates.** `block_index_daily` / `block_index_weekly` are CAGGs over
   `block_index_aggregates`. Deleting source rows does **not** remove aggregate rows — the CAGG
   needs an explicit `refresh_continuous_aggregate` over the affected range, or the block's data
   stays visible in every chart that reads the aggregate.

---

## 2. Design principles

1. **Purge is a new, separate verb.** Archive/inactivate keeps its exact current tenant-facing
   semantics and stays reversible. Purge is platform-admin-only and irreversible.
2. **Completeness is enforced by the type system, not by diligence.** A declarative ownership
   manifest drives the purge; a CI test compares the manifest against `information_schema` and fails
   when a new table carrying `tenant_id`/`farm_id`/`block_id` isn't registered. This is the core of
   the proposal — everything else is plumbing.
3. **Preview before, receipt after.** Every purge shows a machine-generated impact table first and
   emits a receipt afterwards that includes an independent orphan re-scan. The receipt is what makes
   the feature trustworthy.
4. **The scanner is independently useful.** Ship it first; it audits the environments we already
   have, including the tenant purges done to date.
5. **Async, phased, resumable.** Tenant purge touches thousands of R2 objects. It becomes a job with
   recorded phases so a crash resumes rather than half-deletes.

---

## 3. The ownership manifest

New module `backend/app/shared/purge/`:

```python
# registry.py
@dataclass(frozen=True)
class OwnedTable:
    schema: Literal["tenant", "public"]
    table: str
    owner_column: str | None       # "block_id" | "farm_id" | "tenant_id"
    via: str | None = None         # reach it through a parent, e.g. "imagery_aoi_subscriptions.id"
    strategy: Literal["delete", "cascade", "refresh_cagg"] = "delete"
    order: int = 0                 # topological rank; children first

BLOCK_OWNED: tuple[OwnedTable, ...] = (...)
FARM_OWNED:  tuple[OwnedTable, ...] = (...)
TENANT_PUBLIC_OWNED: tuple[OwnedTable, ...] = (...)
```

`BLOCK_OWNED` starts from the existing `_BLOCK_DEPENDENT_TABLES` allowlist (already curated and
deliberately broad) and adds the no-FK tables the allowlist omits, plus the CAGG refresh entries.
`FARM_OWNED` adds the 13 farm-FK tables, `audit_events`, `weather_observations`,
`weather_forecasts`, `recommendations.farm_id`. `TENANT_PUBLIC_OWNED` is the fix for the leak list in
§1.1: `decision_trees` (+ versions), `backfill_runs`, `farm_scopes`, `tenant_settings_overrides`,
`tenant_memberships`, `tenant_subscriptions`, `tenant_settings`, `tenants`.

**The guard test** (`backend/tests/test_purge_registry_complete.py`):

```
for every table in tenant schema + public schema:
    for col in ("tenant_id", "farm_id", "block_id"):
        if table has col and (table, col) not in registry and not in EXPLICIT_EXEMPTIONS:
            fail(f"{table}.{col} is unowned — add it to the purge registry or exempt it")
```

`EXPLICIT_EXEMPTIONS` is a short annotated list (`audit_events_archive` — orphaned by design;
`public.users` — global identity). Every future migration that adds an ownership column now either
registers it or writes down why not. This is the mechanism that makes "no orphans" a property rather
than a hope.

### 3.1 Imagery COG reclamation

Because the key scheme has no tenant component, deletion must be **refcounted by `aoi_hash`**:

```
assets_for(block)  = pgstac items in collection {tenant_schema}__{product}
                     whose item id ends with /{block.aoi_hash}
safe_to_delete(k)  = no other block, in ANY tenant schema, has this aoi_hash
```

`shared/purge/imagery.py` walks `public.tenants` once to build the live `aoi_hash` set, subtracts the
hashes owned only by the purge target, then deletes the matching pgstac items and their R2 objects.
Shared-AOI blocks (identical geometry across tenants) correctly keep their COGs.

This is also worth exposing standalone as a **`GET /v1/admin/orphans/imagery`** report — I expect it
to find a meaningful amount of dead R2 spend from tenants already purged.

> **Recommendation, separate from this work:** change `build_asset_key()` to prefix
> `tenants/{tenant_id}/…` for *new* writes. It makes future reclamation a prefix delete instead of a
> cross-tenant refcount. It's a breaking change for the tile server and existing pgstac hrefs, so it
> belongs in its own PR — but every month we don't do it makes the backfill larger.

---

## 4. API surface

All new routes under `/api/v1/admin/purge`, gated by a **new capability `platform.purge_data`**
(added to `shared/rbac/capabilities.yaml`, granted to PlatformAdmin only — deliberately *not*
bundled into `platform.manage_tenants`, so it can be withheld in production).

### 4.1 Preview (read-only, safe to call freely)

```
GET /v1/admin/purge/preview?kind=block|farm|tenant&id={uuid}[&tenant_id={uuid}]
200 {
  "kind": "farm",
  "id": "…", "name": "Bashayer", "tenant_slug": "acme",
  "blocking": [ {"reason":"tenant_not_pending_delete", …} ],   // empty = ready
  "db_rows": [ {"table":"block_index_aggregates","rows":184203}, … ],
  "children": {"blocks": 35, "pivots": 4},
  "storage": {"attachment_objects": 12, "imagery_objects": 4180,
              "imagery_objects_shared_kept": 22, "bytes": 91234567},
  "pgstac": {"collections": 2, "items": 4180},
  "keycloak": {"users": 0, "groups": 0},
  "estimated_seconds": 95
}
```

For a block this replaces nothing; for a farm and tenant it supersedes/extends the existing
`inactivate-preview`. Preview is generated *from the manifest*, so it can never drift from what the
purge actually does.

### 4.2 Execute

```
POST /v1/admin/purge
{
  "kind": "block" | "farm" | "tenant",
  "id": "…",
  "tenant_id": "…",            // required for block/farm
  "confirmation": "Bashayer",  // must equal entity name (farm/block) or slug (tenant)
  "reason": "test data cleanup 2026-07-29",
  "dry_run": false
}
202 { "job_id": "…", "status": "queued" }
```

- `dry_run: true` runs the full manifest inside a transaction and rolls back, returning real deleted
  row counts. Storage/pgstac steps are simulated. This is the honest rehearsal.
- Blocks and small farms complete inline (< ~5s) and return `200` with the receipt; anything larger
  goes async. The client handles both by always polling if it gets a `202`.

```
GET /v1/admin/purge/jobs/{job_id}
200 { "status":"running", "phase":"imagery_objects", "phases":[…],
      "progress":{"done":2100,"total":4180}, "errors":[] }

GET /v1/admin/purge/jobs        # history, filterable by kind/actor/date
```

### 4.3 Receipt + verification

On completion the job stores a receipt (new `public.purge_receipts`, retained indefinitely — it is
the tombstone for a deleted entity):

```
{ "job_id":"…", "kind":"farm", "id":"…", "name":"Bashayer", "tenant_slug":"acme",
  "actor_user_id":"…", "reason":"…", "started_at":…, "finished_at":…,
  "deleted": {"db_rows":{…}, "storage_objects":4192, "pgstac_items":4180, "kc_users":0},
  "verification": {"orphans_found":0, "scanned_tables":57} }
```

The verification block comes from re-running the scanner against the just-deleted id. **A purge that
reports `orphans_found > 0` is a failed purge** and surfaces as a red receipt with the residual list.

```
GET /v1/admin/orphans/scan?scope=all|tenant&tenant_id=…
```
Standalone read-only sweep for every registered table: rows whose `tenant_id`/`farm_id`/`block_id`
points at something that no longer exists, plus unreferenced pgstac items and R2 objects. Exposed in
the UI and runnable from CI/cron against dev.

### 4.4 Tenant purge changes

The existing `POST /v1/admin/tenants/{id}/purge` stays as the entry point (it is already wired into
the UI and has the slug-confirmation + grace-window logic). It gains:

- the manifest-driven public-schema cleanup — replacing `delete_public_rows()`'s 3-table sweep
- pgstac collection/item deletion
- R2 attachment prefix delete + refcounted imagery reclamation
- Keycloak failures promoted from "log and continue" to a recorded receipt error, so the residue is
  visible instead of silently accepted
- async execution + receipt
- `PURGE_ALLOW_IMMEDIATE` env flag (default **false**; true on dev/staging) which permits `force`
  without the 30-day grace window. Today `force` already skips the window for anyone with
  `platform.manage_tenants`; putting it behind an env flag is a small production safety win.

### 4.5 Reset tenant data (the one you'll actually use most)

```
POST /v1/admin/purge/tenant-data
{ "tenant_id":"…", "confirmation":"acme", "keep": ["users","settings","integrations"] }
```

Purges **every farm and block** in a tenant and all their data, leaving the tenant, its Keycloak
group, memberships, settings and integration config intact. This is the real testing-phase primitive
— it gives a clean slate without re-running provisioning, re-inviting users and re-entering API
keys. Implemented as a loop over `FARM_OWNED` for each farm, so it inherits the same guarantees.

---

## 5. UX

### 5.1 Platform admin gets a data explorer

Platform admins currently have no farm/block UI at all — `/platform/tenants/:id` shows admins,
integrations and lifecycle actions only. Add a **Data** tab to `TenantAdminDetailPage`:

```
┌ Tenant: acme ──────────────────────────────────────────────────────┐
│ Overview │ Admins │ Integrations │ Data │                          │
├────────────────────────────────────────────────────────────────────┤
│  Farms (4)                             [ Reset all tenant data… ]  │
│                                                                    │
│  ▸ Bashayer            35 blocks   184k rows   4.2 GB   ⋯ Purge…   │
│  ▸ North Delta          8 blocks    22k rows   0.9 GB   ⋯ Purge…   │
│    ▾ Block A-1                       6.1k rows  180 MB  ⋯ Purge…   │
│    ▾ Block A-2 (archived)            5.8k rows  174 MB  ⋯ Purge…   │
│                                                                    │
│  Orphaned data                                     [ Scan now ]    │
│  ⚠ 3 decision trees from purged tenants · 1.4 GB unreferenced COGs │
│                                                    [ Reclaim… ]    │
└────────────────────────────────────────────────────────────────────┘
```

Row counts and sizes come from the preview endpoint (cached, computed lazily per row on expand).
Archived entities are shown greyed with an "archived" pill — purging an archived entity is the
common path, but purging a live one is allowed with a stronger warning.

The orphan panel is the payoff of the scanner: it makes accumulated cruft visible and reclaimable
without a new purge.

### 5.2 The confirm dialog

One shared `PurgeDialog` component for all three kinds, three sections:

```
┌ Permanently delete farm "Bashayer"?  ──────────────────────────────┐
│                                                                    │
│  This cannot be undone. Archiving is reversible — purging is not.  │
│                                                                    │
│  ── What will be deleted ─────────────────────────────────────     │
│   35 blocks (4 pivots)                                             │
│   184,203 measurement rows across 21 tables            [details ▾] │
│   4,180 imagery files (4.2 GB)    22 kept — shared AOI  [why? ⓘ]   │
│   2 STAC collections · 12 attachments                              │
│   ✓ Nothing outside this farm is affected                          │
│                                                                    │
│  ── Confirm ──────────────────────────────────────────────────     │
│   Type the farm name to confirm:  [ Bashayer            ]          │
│   Reason (recorded in the audit log): [ test cleanup    ]          │
│                                                                    │
│         [ Dry run ]        [ Cancel ]   [ Delete permanently ]     │
└────────────────────────────────────────────────────────────────────┘
```

- `[details ▾]` expands the per-table row counts straight from the preview — no hand-maintained copy.
- **`[ Dry run ]` is a first-class button**, not a checkbox. It runs the rollback rehearsal and swaps
  the impact table for measured results. In a testing phase this is the button that builds trust in
  the feature; it should be one click, not a hidden option.
- The confirm input requires the *exact* entity name (blocks use their code). Reuses the existing
  slug-confirmation pattern from `TenantActionPanel`.
- The destructive button stays disabled until the text matches and `blocking` is empty.

### 5.3 Progress + receipt

Async purges show a progress drawer with the phase list, then a receipt card:

```
┌ Purged "Bashayer" ─────────────────────────────────────────────────┐
│  ✓ 184,203 rows · 4,192 objects · 2 STAC collections               │
│  ✓ Verification: 0 orphans across 57 tables                        │
│  Purged by mohamed@… · 2026-07-29 14:02 · reason: test cleanup     │
│                                              [ Copy receipt JSON ] │
└────────────────────────────────────────────────────────────────────┘
```

A failed verification renders red with the residual rows listed and a **Retry cleanup** action that
re-runs only the failed phases against the recorded target.

### 5.4 Tenant-side

No change. Tenant users keep Archive only. If a platform admin is browsing tenant surfaces while
holding `platform.purge_data`, `ArchiveButton` gains a secondary "Delete permanently…" item that
opens the same dialog — so you don't have to navigate to `/platform` mid-cleanup.

---

## 6. Delivery plan

| PR | Scope | Ships value alone |
|---|---|---|
| **P-1** | `shared/purge/registry.py` manifest + `information_schema` guard test + `GET /v1/admin/orphans/scan` + orphan panel | Yes — audits current environments immediately |
| **P-2** | Purge engine (topological delete, CAGG refresh, dry-run rollback) + block purge API + preview | Yes — blocks are the most common test residue |
| **P-3** | Farm purge (children first, reuses P-2) | Yes |
| **P-4** | Imagery reclamation: pgstac item delete + `aoi_hash` refcount + R2 delete + `GET /admin/orphans/imagery` | Yes — reclaims dead R2 spend from past purges |
| **P-5** | `purge_jobs` + `purge_receipts` tables (migration), Celery task, phased/resumable execution, job APIs | No — needs P-2..4 |
| **P-6** | Tenant purge upgraded onto the manifest + pgstac + R2 + `PURGE_ALLOW_IMMEDIATE`; `POST /purge/tenant-data` | Yes |
| **P-7** | FE: Data tab, `PurgeDialog`, progress drawer, receipt card, `ArchiveButton` secondary action | Yes |

P-1 and P-2 together are the minimum that solves the stated testing-phase pain for blocks; P-6 gives
the reset-tenant-data primitive.

## 7. Risks

- **Deleting live data.** Mitigated by: separate capability, exact-name confirmation, mandatory
  preview, dry run, receipt, and audit-archive record written *before* execution (the pattern
  `purge_tenant` already uses).
- **Hypertable delete performance.** `block_index_aggregates` and `signal_observations` can be large.
  Delete in time-bucketed batches inside the job so a purge doesn't hold a long transaction; report
  progress per batch.
- **CAGG staleness.** Explicit `refresh_continuous_aggregate` entries in the manifest, and the
  scanner checks CAGGs for rows whose `block_id` no longer exists — so a missed refresh is caught.
- **Cross-tenant COG deletion.** The refcount is the guard; P-4 ships with a dry-run-only mode first
  and a test fixture covering two tenants sharing one `aoi_hash`.
- **Partial failure.** Phases are recorded; a failed job leaves a red receipt and a Retry action
  rather than an unknown state. The DB portion is one transaction; storage/pgstac run after commit
  and are idempotent on retry.

## 8. Decisions

1. **Archive first, then purge — decided, enforced.** A block or farm must have
   `deleted_at IS NOT NULL` before it can be purged; `tenant_data` requires the tenant to be
   suspended or pending-delete; whole-tenant purge keeps its existing `pending_delete` gate. The
   one exception is a dry run, which writes nothing and may therefore rehearse a live entity —
   that is how an admin learns what archiving would commit them to.
2. **Platform-admin only in Phase 1 — decided.** The new `platform.purge_data` capability is
   platform-scoped. Phase 2 will extend *farm and block* purge to TenantAdmin; tenant-level purge
   stays platform-only permanently.
3. Receipts are retained indefinitely — they are tiny and are the only remaining evidence the
   entity existed.
4. Re-keying imagery to a tenant-prefixed layout (§3.1) is still recommended and still out of
   scope — it needs a backfill plus tile-server coordination.

---

## 9. What shipped

Built as one branch (`feat/platform-purge`) rather than seven PRs; the internal structure is the
one described above.

| Piece | Where |
|---|---|
| Ownership manifest | `backend/app/shared/purge/registry.py` |
| Purge engine (topological delete, dry-run rollback, CAGG refresh) | `backend/app/shared/purge/engine.py` |
| Imagery reclamation (pgstac + `aoi_hash` refcount) | `backend/app/shared/purge/imagery.py` |
| Orphan scanner | `backend/app/shared/purge/scanner.py` |
| Jobs / receipts / API | `backend/app/modules/purge/` |
| Migration (`purge_jobs`, `purge_receipts`) | `migrations/public/versions/0047_*.py` |
| Tenant purge upgraded onto the manifest | `backend/app/modules/tenancy/service.py` |
| Data tab, PurgeDialog, orphan panel | `frontend/src/modules/admin/components/` |

### Differences from the plan

* **`GET /admin/purge/preview`** takes `kind` + `id` + `tenant_id` as query params rather than a
  path-shaped route, so one endpoint serves all three kinds.
* **Small purges run inline** (under 50k rows and 200 objects) and return a completed job with its
  receipt; only larger ones reach the `purge.run_job` Celery task. Both paths call the same
  `run_job`, so there is one execution path, not two.
* **Whole-tenant purge stayed in `tenancy/service.py`** instead of moving under `/admin/purge`.
  It owns the status machine, the Keycloak teardown and the schema drop; it now calls the shared
  manifest and reclaimer and writes the same receipts. `POST /admin/tenants/{id}/purge` is
  unchanged for callers.
* **`PURGE_ALLOW_IMMEDIATE` defaults to `true`**, which is exactly today's behaviour — `force` has
  always been available to anyone with `platform.manage_tenants`. The flag exists so a real
  production deployment can close that escape hatch without a code change.

### Two things the build found that the plan did not anticipate

* **`signal_observations.attachment_s3_key`** — a third object-storage artifact, missed by the
  original inventory. Signal photos would have leaked on every purge. Now collected and deleted.
* **A self-deadlock in tenant purge.** Planning imagery reclamation reads `<tenant>.blocks`, which
  takes an ACCESS SHARE lock. Done on the request's own session — which stays open — the
  `DROP SCHEMA … CASCADE` that follows waits forever for a lock the same request is holding. The
  planning read (and the verification scan) now run on their own short-lived sessions. An
  integration test caught this as a hang.

### Verified

21 integration tests (12 purge + 9 tenant lifecycle) plus 6 frontend tests. The guard test is the
load-bearing one: it introspects a freshly-migrated tenant schema and the public schema and fails
on any unregistered ownership column. It caught two real gaps on first run — `purge_jobs.tenant_id`
and `purge_receipts.tenant_id`, both now explicit exemptions.

Not yet exercised against real imagery: the dev database has no pgstac items or R2 COGs, so the
`aoi_hash` refcount path is covered by construction and code review rather than by a test with real
shared-AOI data. Worth a careful first run on a tenant that actually has scenes.
