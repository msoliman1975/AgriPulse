# Signals platform tier — implementation plan

**Status:** APPROVED 2026-08-09 (D8) · **Phase:** S0, blocks the scouting app
**Parent:** [Scout dossier](agripulse-scout-dossier.html) · [spec](mobile-scouting-app-spec.md)

Move signal definitions and templates from per-tenant schemas to `public` with a
nullable `tenant_id`, so a curated scouting form set can be published once and
read by every tenant.

```
NULL      → platform-curated  (authored at /platform/signals)
non-NULL  → tenant-authored   (authored at /config/signals/:farmId, unchanged)
```

---

## 0. Verified starting state

| Fact | Value | Source |
|---|---|---|
| Tenant migration head | **0062** (was 0061 — see below) | `migrations/tenant/versions/0062_decision_tree_eval_traces.py` |
| Public migration head | **0051** | `migrations/public/versions/0051_seed_crop_attribute_definitions.py` |
| Tenant migrations run | per schema, checkpointed per tenant | `scripts/migrate_tenants.py` |
| `tenant_id` from schema | `replace(current_schema(),'tenant_','')` | precedent in tenant migration `0046` |
| Real FKs into `signal_definitions` | 2 — `signal_assignments`, `signal_template_definitions` | `signals/models.py:89,212` |
| `signal_observations` → definitions | **no FK** — logical reference already | `signals/models.py` |
| Tenant → public FKs legal & used | `TenantMembership.user_id → public.users.id` | `iam/models.py` |
| Purge guard | sweeps `information_schema` for `tenant_id`/`farm_id`/`block_id`; every hit must be registered | `shared/purge/registry.py` |
| Cross-schema precedent | `OwnedTable("decision_trees", owner_column="tenant_id", schema="public", order=10, fk=False)` | `registry.py:305` |

---

## 1. Migration split, and why

Two migrations, because the public tables must exist before any tenant schema
tries to write into them.

| Order | Migration | Does |
|---|---|---|
| 1 | **public `0052_signal_catalog_public`** | Creates the three public tables, empty. No data touched |
| 2 | **tenant `0063_signals_to_public_catalog`** | Per schema: copy rows up stamping `tenant_id`, repoint the two FKs, drop the old tenant tables |

`migrate_tenants.py` applies tenant migrations per schema with the tenant's
`search_path`, so migration 0063 can use `current_schema()` to derive its own
`tenant_id` — the same trick migration 0046 already uses.

### Ordering — CONFIRMED, no change needed

`infra/helm/api/templates/migration-job.yaml` is an ArgoCD **PreSync** hook at
`sync-wave: "-1"`, chaining both passes in one container:

```bash
set -euo pipefail
alembic -c /app/alembic.ini -n public upgrade head   # 1. public, once
python -m scripts.migrate_tenants                    # 2. every active tenant
```

`set -euo pipefail` means the tenant pass runs **only if the public pass
succeeded**, and a non-zero exit blocks the ArgoCD sync rather than rolling pods
against a stale schema. Public `0052` is therefore guaranteed to precede tenant
`0063`.

### Revision numbers move under you — take the number late

T2 was first written as `0062` and had to be renumbered to `0063` mid-task:
`0062_decision_tree_eval_traces.py` (PR #386, `c1ed645`) landed on the branch
while this work was in progress, and the local fleet had already been migrated
to it. Symptoms of the collision, worth recognising quickly:

* `alembic -n tenant heads` printed **`0062 (head)` twice** with a warning — two
  files sharing a revision id is two heads, i.e. a branch;
* tenant `alembic_version` read `0062` for a migration that had never been run
  from this worktree.

With ~16 worktrees on this repo, **re-check the head immediately before naming a
migration**, and treat `grep -h '^revision: str' *.py | sort | uniq -d` as part
of the pre-flight rather than a debugging step.

### Two consequences of how the runner works

1. **Archived tenants are skipped.** `_list_tenants` filters
   `WHERE deleted_at IS NULL AND status <> 'archived'`. An archived (or wedged)
   tenant will **not** receive `0063` and will keep its tenant-schema
   `signal_definitions` while the fleet moves on. Add a pre-flight assertion that
   every non-archived tenant reached `0063`, and decide explicitly what happens
   if such a tenant is later revived — its copy-up would run much later, against
   a public table that has since accumulated rows.
2. **`backoffLimit: 1`.** A transient failure partway through the loop leaves the
   fleet **partially migrated**. This is exactly why §3.1's
   `ON CONFLICT (id) DO NOTHING` idempotency is load-bearing rather than
   defensive — a re-run must be a no-op for tenants already done.

### New tenants replay the whole chain

The tenant chain is also the template for tenants created later: a new tenant
replays from `0001`, so it will *create* `signal_definitions` at `0029` and then
*drop* it at `0063`. Correct but wasteful, and brittle if the chain is ever
squashed. Therefore `0063` must use `DROP TABLE IF EXISTS` and tolerate an empty
copy-up rather than assuming rows exist.

---

## 2. T1 — public `0052_signal_catalog_public`

```sql
CREATE TABLE public.signal_definitions (
  id                       uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
  tenant_id                uuid NULL,          -- NULL = platform-curated
  code                     text NOT NULL,
  name                     text NOT NULL,
  description              text NULL,
  value_kind               text NOT NULL,
  unit                     text NULL,
  categorical_values       text[] NULL,
  value_min                numeric(12,4) NULL,
  value_max                numeric(12,4) NULL,
  attachment_allowed       boolean NOT NULL DEFAULT FALSE,
  is_active                boolean NOT NULL DEFAULT TRUE,
  aggregation              text NOT NULL DEFAULT 'latest',
  aggregation_window_days  integer NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);

-- Code uniqueness partitioned per scope — mirrors decision_trees migration 0024.
-- NOTE the `deleted_at IS NULL` half: the tenant original is
-- `uq_signal_definitions_code_active ON (code) WHERE deleted_at IS NULL`.
-- Drop that predicate and soft-deleting a definition burns its code forever.
CREATE UNIQUE INDEX uq_signal_definitions_platform_code
  ON public.signal_definitions (code)
  WHERE tenant_id IS NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_signal_definitions_tenant_code
  ON public.signal_definitions (tenant_id, code)
  WHERE tenant_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_signal_definitions_tenant ON public.signal_definitions (tenant_id);
```

> **T1 SHIPPED + VERIFIED 2026-08-09** — `migrations/public/versions/0052_signal_catalog_public.py`.
> Round-tripped on the local DB (upgrade → downgrade → upgrade); scope semantics
> tested 6/6 including soft-delete code reuse and cross-tenant isolation.
> Two deliberate additions beyond this sketch: `set_updated_at()` triggers (every
> public catalog table has one; `BEFORE UPDATE` only, so the T2 copy-up INSERT
> preserves original timestamps), and **no FK from `tenant_id` to
> `public.tenants`** — matching `decision_trees`, since purge removes tenant rows
> via the ownership manifest and a CASCADE would let a tenant delete take the
> platform catalog with it.
>
> **ORM models were deliberately NOT added in T1** — during the T1→T2 window the
> tenant models still map the tenant tables, and public twins would put two
> classes with the same table name in one registry. They land in T2. Until then,
> **do not run public autogenerate**: `Base.metadata` does not know these tables
> and autogenerate would propose dropping them.

`public.signal_templates` follows the same shape (`code`, `name`,
`description`, `is_active`, `tenant_id`, same two partial uniques).
`public.signal_template_definitions` keeps `(template_id, signal_definition_id,
position, is_required)` with FKs to the two public tables, `ON DELETE CASCADE`.

Carry every column across verbatim — including `aggregation` and
`aggregation_window_days`, which the engine reads.

---

## 3. T2 — tenant `0063_signals_to_public_catalog` (the risky one)

Runs once per tenant schema. **Must be idempotent** — `migrate_tenants.py`
checkpoints per tenant, and a partial failure mid-fleet has to be re-runnable.

> **T2 SHIPPED + VERIFIED 2026-08-09** — applied across all **4 local tenant
> schemas** via `scripts.migrate_tenants`, then round-tripped.
> Upgrade: 4 definitions + 1 template + 2 junction rows moved up, **0 became
> platform-scoped**, all tenant catalog tables dropped, all 4 `signal_assignments`
> FKs verified pointing at `public.signal_definitions` (confirmed via
> `pg_class`/`pg_namespace`, not `pg_get_constraintdef`, which omits the schema
> when it is on the search_path and reads misleadingly).
> **All 8 historical observations still resolve** — the point of preserving ids.
> Downgrade on the one tenant holding data: 6/6 — tables restored with exact row
> counts, observations resolving, FK repointed back, and **only that tenant's rows
> removed from `public`** while the other tenants' remained, proving per-tenant
> isolation. Re-upgraded; fleet left at `0063`.
>
> Two implementation notes beyond the sketch below:
> * A **`RAISE EXCEPTION` guard** runs first if no `public.tenants` row matches
>   `current_schema()`. Without it the `tenant_id` subquery yields NULL and the
>   tenant's definitions are copied up as **platform** rows — instantly visible to
>   every other tenant. Failing hard is vastly preferable.
> * Constraint names are **read from `pg_constraint`, never hardcoded**. The real
>   junction FK is `fk_signal_template_definitions_signal_definition_id_sig_9598`
>   — Alembic's convention overflowed Postgres' 63-char identifier limit and was
>   truncated with a hash suffix.

### 3.1 Copy up, preserving ids

Preserving `id` is what keeps `signal_assignments` and the
`signal_observations` hypertable resolving without touching either.

```sql
-- tenant_id for THIS schema, the migration-0046 way
-- replace(current_schema(),'tenant_','') -> hex uuid without dashes

INSERT INTO public.signal_definitions (
    id, tenant_id, code, name, description, value_kind, unit,
    categorical_values, value_min, value_max, attachment_allowed,
    is_active, aggregation, aggregation_window_days, created_at, updated_at)
SELECT d.id,
       (SELECT t.id FROM public.tenants t
         WHERE replace(t.id::text,'-','') = replace(current_schema(),'tenant_','')),
       d.code, d.name, d.description, d.value_kind, d.unit,
       d.categorical_values, d.value_min, d.value_max, d.attachment_allowed,
       d.is_active, d.aggregation, d.aggregation_window_days,
       d.created_at, d.updated_at
  FROM signal_definitions d
ON CONFLICT (id) DO NOTHING;          -- idempotency
```

Same for templates, then `signal_template_definitions`.

### 3.2 Repoint the two FKs

```sql
ALTER TABLE signal_assignments
  DROP CONSTRAINT signal_assignments_signal_definition_id_fkey;
ALTER TABLE signal_assignments
  ADD CONSTRAINT signal_assignments_signal_definition_id_fkey
  FOREIGN KEY (signal_definition_id)
  REFERENCES public.signal_definitions(id) ON DELETE CASCADE;
```

> Check the real constraint names against the DB — Alembic's naming convention
> doubles them in places, and a downgrade needs the convention-correct name.
> This has bitten before.

### 3.3 Drop the old tenant tables

Only after 3.1 and 3.2 succeed, and only in the same transaction. `IF EXISTS`
because a freshly provisioned tenant replays the chain and may reach `0063` in
an unexpected state (§1):

```sql
DROP TABLE IF EXISTS signal_template_definitions;
DROP TABLE IF EXISTS signal_templates;
DROP TABLE IF EXISTS signal_definitions;
```

### 3.4 Downgrade

Recreates the tenant tables and copies back rows `WHERE tenant_id = <this
tenant>`. **Downgrade is lossy for platform rows by design** — `tenant_id IS
NULL` definitions have no tenant schema to return to. Therefore:

> **Downgrade is only safe before platform seeding (T6).** After tenants start
> depending on platform definitions, rolling back orphans their observations'
> `signal_definition_id`. State this in the migration docstring.

---

## 4. T3 — resolution rule (specify it, or it will be guessed wrong)

A tenant may already have authored a definition whose `code` collides with a
platform one we later seed — e.g. both define `canopy_vigour`.

**Rule: the tenant row shadows the platform row of the same code.**

```sql
SELECT DISTINCT ON (code) *
  FROM public.signal_definitions
 WHERE tenant_id IS NULL OR tenant_id = :tid
 ORDER BY code, tenant_id NULLS LAST   -- non-NULL (tenant) wins
```

Consequences to honour everywhere:
- The snapshot must resolve **one definition per code**, not two.
- The UI must show a tenant-shadowed platform definition as *overridden*, not duplicated.
- Tenants may **read** platform rows and may **not** update or delete them — enforce in the service layer, not just the UI.

---

## 5. T4 — `snapshot.py`, the engine read path

> **T4 + T5 SHIPPED + VERIFIED 2026-08-09.**
> `snapshot.py`, `models.py` and `repository.py` updated; 119/119 signals unit
> tests and 853 unit tests green (5 pre-existing `imagery/test_sentinel_hub`
> failures confirmed unrelated — they fail identically with these changes
> stashed).
>
> **The equivalence test passed: snapshot output is byte-identical** before and
> after, captured by temporarily downgrading the one tenant holding data, running
> the old code, then re-running post-migration.
>
> **A real cross-tenant leak was found and closed.** After the table move,
> `list_definitions()` returned **3** definitions to a tenant owning **2** —
> `select(SignalDefinition)` had no tenant filter and the ORM now pointed at the
> shared table. Schema placement used to be the isolation; it no longer is.
> Every catalog query now carries an explicit predicate:
> `_visible_scope()` for reads (platform + own), and an inline
> `tenant_id = (…current_schema()…)` for writes.
>
> Verified by test, all rolled back: reads scoped (2/2, was 3), a platform row is
> **readable but not writable** (UPDATE and soft-delete both match zero rows and
> leave it untouched), own rows remain writable and are stamped with `tenant_id`,
> shadowing returns exactly one row per code, and another tenant's definition does
> **not** appear even when an assignment pointing at it is fabricated.
>
> One follow-up deliberately left open: `service.py` and `router.py` hold no direct
> table references, so they inherit the repository's scoping — but **nothing yet
> raises a 403 when a tenant edits a platform row**; the write simply no-ops.
> That is safe but silent, and belongs with the T6 platform-authoring work.

`signals/snapshot.py` builds `{signal_code: SignalEntry}` per block in raw SQL
and is consumed by **alerts and recommendations**. Its joins move from the
tenant `signal_definitions` to `public.signal_definitions` with the two-tier
predicate and the §4 shadowing rule.

The aggregation logic (`latest` / `mean` / `median` / `max` / `min` / `sum` /
`count`, with `aggregation_window_days`) is unchanged — only where the
definition row comes from changes.

**This is the highest-blast-radius code change in the plan.** A wrong join here
silently changes what every decision tree and alert evaluates.

---

## 6. T5 — service, repository, router

- Reads resolve both tiers (§4).
- Writes: tenant users may only create/update/delete rows where
  `tenant_id = context.tenant_id`. A 403 on attempting to edit a platform row.
- Platform authoring requires a **platform-admin** context, mirroring
  `/platform/crops` and `/platform/plan-templates`.
- `SignalAssignment` stays tenant-scoped and may reference either tier.

---

## 7. T7 — purge registry (fails CI if missed)

> **T7 SHIPPED + VERIFIED 2026-08-09.** Two entries added to
> `TENANT_PUBLIC_OWNED`; all 12 purge integration tests pass, plus 120
> signals tests.
>
> **The guard test caught a real bug that no amount of reading would have.**
> `test_tenant_schema_has_no_unowned_columns` provisions a brand-new tenant,
> which replays the entire migration chain — and T2's `RAISE EXCEPTION` guard
> fired, **breaking tenant creation outright**. Inside the creation transaction
> no committed `public.tenants` row matches the new schema yet, so the tenant_id
> lookup is NULL.
>
> Fix: make the guard **conditional on there being rows to move**. A fresh
> tenant's catalog tables are empty, so nothing can be mis-scoped and the guard
> has nothing to protect; it now raises only when `pending > 0` and the tenant is
> unresolvable — and reports the row count in the message.
>
> Worth noting how close this came to shipping: the fleet migration, the
> round-trip, and the downgrade all passed happily, because every existing
> tenant *does* have a `public.tenants` row. Only creating a **new** tenant
> exercised the broken path.

`OWNERSHIP_COLUMNS = ("tenant_id","farm_id","block_id")`, and the guard test
sweeps `information_schema` requiring every hit to be registered. Adding
`tenant_id` to three public tables creates three new hits.

Add to `TENANT_PUBLIC_OWNED`, copying the `decision_trees` entry exactly:

```python
OwnedTable("signal_definitions", owner_column="tenant_id", schema="public",
           order=10, fk=False,
           note="tenant-authored definitions; platform rows (tenant_id IS NULL) are never purged"),
OwnedTable("signal_templates", owner_column="tenant_id", schema="public",
           order=10, fk=False, note="as above"),
```

`signal_template_definitions` cascades off `signal_templates`, so it needs no
entry — it has no ownership column.

Deleting `WHERE tenant_id = :tid` **naturally leaves platform rows alone**,
which is exactly the behaviour we want and the reason this pattern was chosen.

Also remove the now-gone tenant-schema entries for these tables if any exist.

---

## 8. T6 — platform catalogue + seeding

> **T6 PART 1 SHIPPED + VERIFIED 2026-08-09 — the S0 gate is met.**
> `migrations/public/versions/0053_seed_scouting_signals.py` seeds **9 definitions
> and 5 templates** as platform rows. Verified: correct values/aggregations,
> clean downgrade (removes exactly the platform rows, leaves tenant rows), and a
> tenant now reads **11 definitions** (9 platform + its own 2) and **6 templates**
> (5 platform + its own 1) with members resolving. Capability
> `signal.platform.manage` (scope `platform`) added — `PlatformAdmin` holds `"*"`
> so it is granted automatically.
>
> **A blocking correctness bug was found and fixed on the way.** The write
> predicate was `tenant_id = (…current_schema()…)`. A platform-admin session runs
> with `search_path = public`, so that subquery is NULL — and `tenant_id = NULL`
> is never true, meaning **platform admins could not edit the catalog they own**.
> Changed to `IS NOT DISTINCT FROM`, which makes NULL match NULL. One operator
> now expresses the whole ownership model, verified 5/5: a platform session sees
> 9 platform rows, edits them, and creates platform rows; a tenant session still
> cannot edit or soft-delete a platform row.
>
> One correction to §7 of this plan: **`disease_severity` is seeded `latest`, not
> `max`/7d.** `mean`/`max`/`min`/`sum` are numeric-only, and a categorical is
> silently coerced to `latest` by the engine — recording `max` would have
> misdescribed what actually happens at evaluation time.
>
> **T6 PART 2 SHIPPED 2026-08-09 — platform authoring.**
> 7 endpoints under `/api/v1/platform/signals/*` (list/create/patch definitions;
> list/get/create/patch templates), gated on the new `signal.platform.manage`
> capability, plus `/platform/signals` in the web app with EN + AR strings and a
> nav entry.
>
> **Scoping is a property of the session, not a parameter.** The endpoints depend
> on `get_admin_db_session` (`search_path = public`), so the repository's
> `current_schema()` lookup resolves to NULL and reads return platform rows while
> writes both stamp and match `tenant_id IS NULL`. There is no "platform mode"
> flag a caller could pass wrongly.
>
> Audit resolved as predicted: `_audit_catalog()` wraps **only the six catalog
> writes** and skips (with an info log) when `tenant_schema is None`, because
> `audit_events` is a per-tenant hypertable and a platform admin has no tenant.
> Every other audit call in the module still goes to `self._audit.record`
> directly, so this cannot silently swallow a tenant event.
>
> Verified 4/4 through the service on a platform session: create and update
> produce platform rows, template creation carries its members, and a tenant
> immediately sees the seeded catalog. 132 signals + purge tests green; frontend
> `tsc`/`eslint`/`prettier` clean and 628 tests pass.
>
> **Deletion is deliberately absent.** Archiving a shared definition affects
> every tenant recording against it, and CS-13's reference scan is tenant-scoped,
> so there is no cross-tenant usage check to make it safe yet. Retirement is
> `PATCH is_active: false`.
>
> **Not browser-verified**, and the page has no render test — it is list-only
> (no create/edit forms yet), so the write endpoints are exercised by service
> tests rather than through the UI.

- New page `/platform/signals` (list, create, edit definitions and templates),
  built like `/platform/crops`.
- Seed the nine scouting definitions and five templates via a **public data
  migration** (`0053_seed_scouting_signals`), not YAML.
- **Set `attachment_allowed = TRUE`** on every definition that should accept a
  photo. Miss it and the camera silently never appears in the app.

**No `sync_from_disk` equivalent.** This is the deliberate divergence from
decision trees: because there is no file-based seeder for signals, a UI edit is
never overwritten on the next deploy.

---

## 9. Test plan

| Level | Test |
|---|---|
| Migration round-trip | upgrade → downgrade → upgrade on a schema with tenant-authored definitions, assignments and observations; assert ids and observation resolution survive |
| Idempotency | run 0063 twice against the same schema; second run is a no-op |
| Multi-tenant | two tenants with colliding `code` values both migrate cleanly (partial uniques hold) |
| Shadowing | tenant `canopy_vigour` + platform `canopy_vigour` → snapshot resolves exactly one, the tenant's |
| Isolation | tenant A cannot read, update or delete tenant B's definitions; neither can edit platform rows |
| Purge | purging tenant A deletes A's definitions, leaves platform rows and tenant B's intact |
| Guard | the `information_schema` sweep passes |
| Engine | snapshot output for a fixture block is **byte-identical** before and after the move |

The engine equivalence test is the one that matters most — capture a snapshot
fixture from the current code first, then assert the migrated code reproduces it.

---

## 10. Rehearsal and rollout

1. **Rehearse on the local 36-block Bashayer clone.** Multi-tenant behaviour cannot be judged on a single-tenant dev DB — create a second throwaway tenant with its own colliding definitions.
2. **CNPG backup immediately before**, as done for the U-4 rollout.
3. Apply public `0052`, then `migrate_tenants.py --dry-run`, then for real.
4. Prod has few tenants; migrate them one at a time and verify between.
5. Verify the engine still evaluates: run a recommendations sweep and diff against the previous run.
6. Only then seed T6 — after which downgrade is no longer safe (§3.4).

**Rollback:** tag rollback does not roll back migrations. Before T6 seeding, the
downgrade path is clean; after it, roll forward instead.

---

## 11. Open risks

| Risk | Severity | Handling |
|---|---|---|
| `snapshot.py` join changes what trees evaluate | **High** | Byte-identical snapshot fixture test (§9) |
| T2 partial failure mid-fleet | **High** | Per-tenant checkpointing + `ON CONFLICT DO NOTHING` idempotency; migrate one tenant at a time |
| Purge guard missed | Medium | §7 — CI catches it, but only if the sweep test actually runs in the PR |
| Downgrade after seeding orphans observations | Medium | Documented in the migration docstring; roll forward instead |
| Constraint-name drift on FK repoint | Medium | Read the real names from the DB, do not assume |
| ~~PreSync applies tenant before public~~ | — | **CONFIRMED SAFE** — chained `set -euo pipefail`, public first (§1) |
| Archived/wedged tenant silently skipped, revived later | Medium | Pre-flight assertion that every non-archived tenant reached `0063` (§1) |
| Partial fleet migration on transient failure (`backoffLimit: 1`) | Medium | `ON CONFLICT (id) DO NOTHING` makes re-runs no-ops (§3.1) |

---

## 12. Sequence

```
T1 public 0052   create empty public tables
  └─ T2 tenant 0063   copy up · repoint FKs · drop old        ← rehearse this
       ├─ T4 snapshot.py two-tier read                        ← engine blast radius
       ├─ T5 service/repo/router + tenant-cannot-edit-platform
       ├─ T7 purge registry                                   ← CI gate
       └─ T3 shadowing rule (touches T4 and T5)
            └─ T6 /platform/signals UI + seed the forms       ← after this, no downgrade
```

T6 is the gate for the whole scouting app: **no forms, no app.**
