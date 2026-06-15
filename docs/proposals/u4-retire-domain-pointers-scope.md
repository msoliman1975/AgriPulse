# U-4 scope — retire the domain-pointer role plane

**Status:** scoped 2026-06-14, decisions locked, not started.
**Parent:** `docs/proposals/identity-users-members-workers-unification.html` (U-4).
**Builds on:** branch `feat/identity-unification` (commit `b529fe5`, tenant migration head **0044**). U-4 migrations chain off 0044, so U-4 lands on top of that branch (or after it merges).

---

## 1. Why this is smaller than the proposal implied

The unification doc framed U-4 as "derive the `*_id` pointers from the unified model, then drop them." Exploration of the actual code changes that framing — **both columns are barely wired**:

| | `farms.farm_manager_id` | `blocks.agronomist_id` |
|---|---|---|
| Writable via API | ❌ in schema but silently dropped (not in service/allowlist) | ✅ create + update |
| Returned in responses | ❌ omitted from `_farm_row_to_dict` | ✅ in `_block_row_to_dict` + `api/blocks.ts` |
| UI to set it | ❌ none | ❌ none (no input in BlockForm) |
| Read by notifications / recs / RBAC / reports | ❌ never | ❌ never |
| Points at | raw `public.users.id` | raw `public.users.id` |

Evidence: `farms/models.py:193` / `:249`; `farms/schemas.py:248,275,302` (fm) / `:378,415,439` (agro); `farms/repository.py` `_FARM_UPDATABLE_COLUMNS:33-49` (excludes fm) / `_BLOCK_UPDATABLE_COLUMNS:65-80` (includes agro) / `insert_block:461-481` / `_farm_row_to_dict:1371-1395` / `_block_row_to_dict:1397-1422`; `frontend/src/api/blocks.ts:51,79`; migration `0027` (added fm, renamed `responsible_user_id`→`agronomist_id`).

**Two consequences:**
1. The "wait for adoption before dropping" timing concern **evaporates** — nothing reads these columns, so changing them now is low-risk.
2. There is **no block-level IAM scope** — `farm_scopes` is per-*farm* (`iam/models.py:120-141`). So `agronomist_id` is the *only* per-block person link and cannot be "derived" from IAM. That fork is what the locked decisions resolve.

---

## 2. Locked decisions

- **U-4a — `farm_manager_id`:** DROP the column; add a read-only derived `farm_manager` to `FarmResponse`, resolved from the `FarmManager` farm-scope.
- **U-4b — `agronomist_id`:** KEEP per-block; repoint the column from raw `users.id` → `agronomist_membership_id` (→ `public.tenant_memberships`), consistent with U-3's worker→member link. **No** new RBAC plane (it's an assignment, not a permission). Promotion to a real `block_scopes` table stays a future option if per-block *permissions* ever become a requirement.

The two tracks are independent of each other and can ship as two PRs in either order.

---

## 3. Track U-4a — derived `farm_manager` (drop dead column)

### Design
"Farm manager" = the **active `FarmManager` farm-scope holder on this farm**. A farm may have 0, 1, or many; define the surfaced value deterministically:
- `farm_manager` = the active `FarmManager` scope with the **earliest `granted_at`** (the canonical/primary manager), or `null` if none.
- Shape: `{ membership_id, full_name } | null`. (If the UI later wants all managers, add a `farm_managers[]` list — not in V1.)

### Cross-schema resolver (the only non-trivial bit)
`farm_scopes`, `tenant_memberships`, `users` live in `public`; the farms service runs on the **tenant** session. The resolver is a schema-qualified read:
```sql
SELECT fs.membership_id, u.full_name
FROM public.farm_scopes fs
JOIN public.tenant_memberships tm ON tm.id = fs.membership_id
JOIN public.users u ON u.id = tm.user_id
WHERE fs.farm_id = :farm_id AND fs.role = 'FarmManager' AND fs.revoked_at IS NULL
ORDER BY fs.granted_at ASC
LIMIT 1
```
Confirm the tenant session can read `public.*` (it can — tables are schema-qualified and `public` is in `search_path`). Batch it for list endpoints (one query keyed by `farm_id IN (...)`) to avoid N+1.

### Change list
- **Migration `0045_drop_farm_manager_id`** (tenant): `DROP COLUMN farms.farm_manager_id`. Downgrade re-adds nullable.
- `farms/models.py`: remove `farm_manager_id` (line 193).
- `farms/schemas.py`: remove `farm_manager_id` from `FarmCreateRequest` (248) + `FarmUpdateRequest` (275); replace in `FarmResponse`/`FarmDetailResponse` (302) with `farm_manager: FarmManagerRef | None`.
- `farms/service.py` + `farms/repository.py`: add the resolver; populate `farm_manager` in `_farm_row_to_dict` / detail paths (single-fetch and list — batch).
- `frontend/src/api/farms.ts`: add `farm_manager: { membership_id: string; full_name: string } | null` (additive — it wasn't there). Optional: surface it on the farm header.
- Tests: resolver unit test (0/1/many managers → deterministic pick); farms response includes `farm_manager`.

### Effort: **S–M** (~0.5–1 day). Risk: low; the cross-schema/batched read is the only unknown.

---

## 4. Track U-4b — repoint `agronomist_id` → `agronomist_membership_id`

### Design
Per-block agronomist stays, but the column references the canonical membership instead of a raw user. No FK (cross-schema logical ref — same pattern as `farm_scopes.farm_id` and the U-3 worker link). Existence/tenant-membership of the value is **not** DB-enforced; optional app-layer validation on write (V1: advisory, matching U-3).

### Tenant-aware backfill (the riskiest piece)
The migration runs per-tenant (migrate_tenants). It must map the existing `agronomist_id` (a `users.id`) to the membership **in this tenant**, since one user can be a member of several tenants. Resolve the tenant from the schema name (`tenant_<uuid_hex>`):
```sql
ALTER TABLE blocks ADD COLUMN agronomist_membership_id uuid;

UPDATE blocks b
SET agronomist_membership_id = tm.id
FROM public.tenant_memberships tm
WHERE tm.user_id = b.agronomist_id
  AND tm.tenant_id = (
      -- schema is tenant_<hex>; rebuild the uuid and match
      SELECT t.id FROM public.tenants t
      WHERE replace(t.id::text, '-', '') = replace(current_schema(), 'tenant_', '')
  )
  AND b.agronomist_id IS NOT NULL;

-- rows whose user isn't a member of this tenant (stale) keep NULL — the
-- raw column was unread anyway, so no behaviour is lost.

ALTER TABLE blocks DROP COLUMN agronomist_id;
```
Watch the **asyncpg/alembic gotchas** (see `feedback_alembic_asyncpg_gotchas`): CAST nullable text binds; downgrade `DROP/ADD` constraint naming; must be exercised by the CI real-DB migration-roundtrip test. Downgrade re-adds `agronomist_id` and back-maps via `tenant_memberships.user_id`.

### Change list
- **Migration `0046_block_agronomist_membership`** (tenant): add `agronomist_membership_id`, backfill (above), drop `agronomist_id`. Reversible.
- `farms/models.py`: `agronomist_id` → `agronomist_membership_id` (line 249).
- `farms/schemas.py`: rename in `BlockCreateRequest` (378), `BlockUpdateRequest` (415), `BlockResponse`/`BlockDetailResponse` (439).
- `farms/repository.py`: `_BLOCK_UPDATABLE_COLUMNS` (65-80), `insert_block` (461-481), `_block_row_to_dict` (1397-1422).
- `farms/service.py`: `create_block` / `update_block` param rename.
- `frontend/src/api/blocks.ts`: `agronomist_id` → `agronomist_membership_id` (51, 79); update `BlockDetailPage.test.tsx` / `BlockEditPage.test.tsx` mocks.
- **Optional value-add (the actual "unlock"):** wire a block-detail member picker reusing U-3's `MemberSelect` so the agronomist is finally *settable in the UI* and shows the member's name. Recommend as a small follow-up, not blocking the rename.
- Tests: block create/update round-trips with `agronomist_membership_id`; backfill correctness in the migration-roundtrip suite.

### Effort: **M** (~1–1.5 days), dominated by backfill correctness + real-DB test. Risk: medium (tenant-aware cross-schema backfill).

---

## 5. Sequencing, dependencies, timing

- **Start now** — on top of `feat/identity-unification` (migrations chain off 0044). No adoption-wait needed (columns are inert).
- **No hard dependency on U-3** being merged: `tenant_memberships` exists independently. But U-4b reuses the membership-link model and `MemberSelect`, so it's cleanest to land *after/with* the identity-unification branch.
- **Migrations:** `0045` (drop farm_manager_id) and `0046` (block agronomist repoint), each independently reversible.
- **Coordinate with farm-block-config** only for merge-conflict avoidance — both touch `farms/{models,schemas,service,repository}.py`. If that rollout (`project_farm_block_config_model`) is imminent, sequence to avoid clobbering. It is *not* a logical prerequisite anymore.
- **PR plan:** PR-U4a (farm_manager derived) and PR-U4b (agronomist repoint) — independent, reviewable separately. Total ~2–2.5 days incl. tests.

## 6. Open items to confirm during build
1. Tenant session can read `public.farm_scopes` in the resolver (expected yes; verify wiring / whether the admin session is needed).
2. Multiple-`FarmManager` tie-break = earliest `granted_at` (locked here; revisit if product wants a list).
3. Backfill behaviour for stale `agronomist_id` with no membership in the tenant → leave `NULL` (accepted).
4. Whether to add app-layer validation that `agronomist_membership_id` belongs to the tenant on write (V1: skip, advisory — matches U-3).
