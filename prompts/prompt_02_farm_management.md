# Prompt 2 — Slice 1: Farm Management

> **How to use this prompt**
> Paste the entire content below the `---` line into Claude Code as the first user message of a fresh session. The repository is `msoliman1975/MissionAgre`. Prompt 1 must be merged to `main` before starting Prompt 2 — this prompt assumes the foundation (auth, tenancy schemas, RBAC, event bus, observability, CI, ArgoCD dev sync) is in place and green.

---

# Mission

You are building **Slice 1: Farm Management** of MissionAgre. By the end of this prompt, a tenant user can sign in, create a farm, draw block boundaries on a map, assign a crop to a block, upload AOI files (GeoJSON / Shapefile / KML), attach photos and documents to farms and blocks, and see all of this rendered correctly in both `en` (LTR) and `ar` (RTL).

This is the first **vertical slice** through the foundation. No imagery, no alerts, no weather, no signals — those come in Prompts 3–5.

# Mandatory first step

**Before writing any code:**

1. Read `docs/ARCHITECTURE.md` end to end (binding).
2. Read `docs/data_model.md` § 5 (`farms` module) end to end (binding spec for every table, column, index, trigger, and constraint).
3. Read `docs/data_model.md` § 1 (conventions), § 4.6 (`public.farm_scopes`), § 13 (`audit`), § 15.1 (deferrable FKs), § 15.2 (multi-schema migrations).
4. Read `prompts/roadmap.md` § Prompt 2 to confirm scope.
5. Read `prompts/prompt_01_foundation.md` to know exactly what the foundation already provides.
6. Inspect the codebase:
   - `backend/app/modules/farms/` (currently empty `__init__.py`, `events.py`, `service.py` — your starting point).
   - `backend/app/shared/db/`, `backend/app/shared/auth/`, `backend/app/shared/rbac/`, `backend/app/shared/eventbus/`, `backend/app/shared/correlation/` (existing primitives — use these, do not reinvent).
   - `backend/migrations/public/` and `backend/migrations/tenant/` (existing Alembic envs — extend, do not parallel).
   - `frontend/src/api/`, `frontend/src/auth/`, `frontend/src/i18n/`, `frontend/src/pages/`, `frontend/src/shell/`, `frontend/src/prefs/` (existing primitives).

If anything you are about to do contradicts `ARCHITECTURE.md` or `data_model.md`, **stop and open an ADR in `docs/decisions/`**. Do not silently substitute your judgment.

# Operating rules for this session

1. **Stay strictly within the "in scope" list.** If you find yourself wanting to build something on the "out of scope" list, stop and confirm.
2. **Do not invent table columns.** Every column, type, constraint, index, and trigger is in `data_model.md` § 5. If something feels missing, ask before adding.
3. **Module boundaries are non-negotiable.** No reads of another module's tables. No imports of another module's internals. The `import-linter` contract written in Prompt 1 is the law.
4. **Use existing primitives.** `get_db_session`, the JWT middleware, the RBAC decorator, the event bus, the audit recorder, the structured logger, the correlation-ID middleware, the i18n setup, the OIDC client, the axios interceptor — all already exist from Prompt 1. Use them.
5. **Three PRs, in order.** PR-A backend, PR-B frontend, PR-C attachments + integration tests. Each must be reviewed and merged before the next opens. See § "Sequencing" below.
6. **Conventional commits, squash-merge, branch-based.** `feat(farms): ...`, `feat(frontend/farms): ...`, `test(farms): ...`, `chore(migrations): ...`.
7. **Tests are not optional.** Unit tests for every service method; integration tests for every endpoint; an end-to-end test for the gate criteria.
8. **When you're stuck on a 50/50 call, ask.** Better five questions than one wrong direction.

# Sequencing — three PRs

## PR-A: backend `farms` module

Branch: `feat/farms-backend`. Scope:

- Migrations (public + tenant), models, services, REST routes, events, audit, RBAC capabilities, crops seed, `farm_scopes` activation, and unit tests + integration tests for the API. **No S3 attachments** — those land in PR-C. Attachment endpoints stubbed `501 Not Implemented` is acceptable, or simply omitted from the OpenAPI spec until PR-C.

## PR-B: frontend farm + block management

Branch: `feat/farms-frontend`. Scope:

- React pages, MapLibre + draw control, AOI file uploads (GeoJSON / Shapefile / KML — parsed client-side, posted as GeoJSON), crop assignment UI, en/ar i18n for the `farms` namespace, feddan/acre toggle wired through, RBAC-aware UI (hide / disable controls per capability), unit + component tests in en and ar.

## PR-C: attachments + cross-schema FK consistency-check + integration tests

Branch: `feat/farms-attachments-and-consistency`. Scope:

- S3 presigned-URL upload flow for `farm_attachments` + `block_attachments` (backend + frontend).
- Periodic Celery Beat job for cross-schema FK consistency check (`public.farm_scopes.farm_id` → `tenant_<id>.farms.id`) — logs orphans to `audit_events`, does **not** delete.
- End-to-end gate-criteria test (Playwright optional but recommended; otherwise an integration-style API + DB test that exercises the full flow).
- Update `README.md` and `docs/runbooks/` (a stub is fine — Prompt 6 fills it).

Each PR must be green in CI (lint, typecheck, mypy, import-linter, pytest, eslint, vitest, helm lint, container build) before opening the next.

---

# What you are building (in scope)

## Backend (`backend/app/modules/farms/`)

### Tables

Implement exactly as specified in `data_model.md` § 5 — no additions, no omissions:

- `public.crops` (§ 5.2) — shared catalog
- `public.crop_varieties` (§ 5.3) — shared catalog
- `farms` in tenant schema (§ 5.4)
- `blocks` in tenant schema (§ 5.5)
- `block_crops` in tenant schema (§ 5.6)
- `farm_attachments` in tenant schema (§ 5.7)
- `block_attachments` in tenant schema (§ 5.7)

### Migrations

- `backend/migrations/public/versions/<rev>_add_crops_and_crop_varieties.py` — public catalog tables.
- `backend/migrations/tenant/versions/<rev>_add_farms_blocks_attachments.py` — tenant tables, all PostGIS indexes, all triggers.
- A separate seed migration (or a Python seed script invoked by a CLI command in `scripts/`) for the ~20 Egyptian crops. **Crop list:** wheat, maize, rice, sugarcane, sugar beet, cotton, soybean, peanut, sunflower, sesame, alfalfa (clover), tomato, potato, onion, garlic, citrus_orange, citrus_mandarin, mango, olive, date palm, banana, grape — confirm with me which 20 to seed if the data model doesn't pin them.

### PostGIS triggers (per § 5.4 / 5.5)

- `farms`: before insert/update of `boundary` → compute `boundary_utm` (transform to EPSG:32636), `centroid` (centroid of `boundary`), `area_m2` (`ST_Area(boundary_utm)`).
- `blocks`: same triggers as `farms`. Plus: re-compute `aoi_hash = encode(digest(ST_AsText(boundary_utm), 'sha256'), 'hex')` whenever `boundary` changes.
- Triggers must be implemented in SQL inside the migrations (not Python). Use plpgsql functions namespaced per schema.

### `farm_scopes` activation

`public.farm_scopes` already has a placeholder from Prompt 1 (§ 4.6). In this prompt:

- Add a service method `farms.assign_user_to_farm(user_id, farm_id, role)` that writes a row to `public.farm_scopes`.
- Enforce the cross-schema logical FK: the service must verify the `farm_id` exists in the caller's tenant schema before inserting into `public.farm_scopes`.
- Endpoint `POST /api/v1/farms/{farm_id}/members` (capability: `farm.member.assign`).
- Endpoint `DELETE /api/v1/farms/{farm_id}/members/{membership_id}` (capability: `farm.member.revoke`) — sets `revoked_at` (do not hard-delete).
- Endpoint `GET /api/v1/farms/{farm_id}/members` (capability: `farm.member.read`).

### REST endpoints

All paths under `/api/v1/`. All requests carry the JWT; tenant context comes from the JWT claim (foundation handles `SET LOCAL search_path`). All write endpoints emit audit events. RFC 7807 `application/problem+json` for errors.

| Method | Path | Capability | Purpose |
|---|---|---|---|
| `POST` | `/farms` | `farm.create` | Create farm |
| `GET` | `/farms` | `farm.read` | List farms (paginated, filterable by `status`, `governorate`, `tag`) |
| `GET` | `/farms/{farm_id}` | `farm.read` | Farm detail |
| `PATCH` | `/farms/{farm_id}` | `farm.update` | Partial update |
| `DELETE` | `/farms/{farm_id}` | `farm.archive` | Soft-archive (sets `status='archived'`, `deleted_at=now()`) |
| `POST` | `/farms/{farm_id}/blocks` | `block.create` | Create block |
| `GET` | `/farms/{farm_id}/blocks` | `block.read` | List blocks in farm |
| `GET` | `/blocks/{block_id}` | `block.read` | Block detail |
| `PATCH` | `/blocks/{block_id}` | `block.update` | Partial update |
| `DELETE` | `/blocks/{block_id}` | `block.archive` | Soft-archive |
| `POST` | `/blocks/{block_id}/crop-assignments` | `block.crop.assign` | Create new `block_crops` row; flips previous `is_current=true` to `false` atomically |
| `GET` | `/blocks/{block_id}/crop-assignments` | `block.read` | History |
| `PATCH` | `/blocks/{block_id}/crop-assignments/{id}` | `block.crop.update` | Update growth_stage, harvest dates, status |
| `POST` | `/farms/{farm_id}/blocks/auto-grid` | `block.create` | Grid-based auto-blocking — see below |

**Geometry contract:** all geometry I/O uses GeoJSON in WGS84 (`SRID 4326`). The backend transforms to UTM 36N internally via the trigger. Reject any input that is not a valid `Polygon` (blocks) or `MultiPolygon` (farms). Reject self-intersecting polygons (`ST_IsValid`). Reject geometry whose bounding box is outside Egypt (lon `24..36`, lat `22..32`) — this is a sanity guard; surface a 422 with a translatable message key.

**Grid-based auto-blocking:** given a farm `boundary` and a target block size in meters (default 500m × 500m, configurable per request), generate a grid of `Polygon`s in UTM 36N intersected with the farm boundary. Each candidate becomes a draft `Polygon` returned to the frontend. The frontend then lets the user accept/edit/discard before committing. The endpoint **only computes**; it does not insert. A separate `POST /farms/{farm_id}/blocks` call (or a batch `POST /farms/{farm_id}/blocks:batch` if you choose) commits.

### Pagination, filtering, sorting

- Cursor-based pagination using `id` (UUID v7, sortable) — `?cursor=<id>&limit=<n>` (cap `limit` at 200, default 50).
- Filtering: `status`, `governorate`, `tag` (repeatable) for farms; `farm_id`, `status`, `irrigation_system` for blocks.
- Sorting: default `created_at DESC`. Allow `?sort=name|code|created_at|area_m2` with `:asc` or `:desc`.

### RBAC

Add the following capabilities to `app/shared/rbac/capabilities.yaml`:

```
farm.create
farm.read
farm.update
farm.archive
farm.member.assign
farm.member.revoke
farm.member.read
block.create
block.read
block.update
block.archive
block.crop.assign
block.crop.update
block.attachment.read
block.attachment.write
farm.attachment.read
farm.attachment.write
```

Map these into roles in `app/shared/rbac/role_capabilities.yaml`:

| Role | Capabilities |
|---|---|
| `PlatformAdmin` | all (inherits from existing `*` rule) |
| `TenantOwner` | all of the above |
| `TenantAdmin` | all of the above |
| `FarmManager` (per-farm scope) | all *.read, *.update, block.create, block.archive, block.crop.*, *.attachment.* — but **not** `farm.create`, `farm.archive`, `farm.member.assign`/`revoke` (those are tenant-level decisions) |
| `Agronomist` (per-farm scope) | *.read, block.crop.update, *.attachment.read |
| `FieldOperator` (per-farm scope) | *.read, *.attachment.write, *.attachment.read |
| `Scout` (per-farm scope) | *.read, *.attachment.read |
| `Viewer` (per-farm scope) | *.read |

The RBAC dependency must use the three-layer order from Prompt 1: PlatformRole → TenantRole → FarmScope. For per-farm capability checks (anything with a `farm_id` in the path), it must consult `farm_scopes` by `(membership_id, farm_id)` — not just the tenant-wide role.

### Events

Define and emit (via the in-process event bus from Prompt 1) — these are dispatched as Celery tasks for any async subscribers, but in this prompt there are no subscribers yet outside of `audit`:

- `FarmCreated { farm_id, code, name, area_m2, created_by }`
- `FarmUpdated { farm_id, changed_fields, updated_by }`
- `FarmArchived { farm_id, archived_by }`
- `FarmBoundaryChanged { farm_id, prev_aoi_hash_or_null, new_centroid }` (per § 5.4 trigger note — this is the hook for imagery in Prompt 3)
- `BlockCreated { block_id, farm_id, code, area_m2, aoi_hash }`
- `BlockUpdated { block_id, changed_fields }`
- `BlockBoundaryChanged { block_id, prev_aoi_hash, new_aoi_hash }`
- `BlockArchived { block_id }`
- `BlockCropAssigned { block_id, crop_id, season_label }`
- `FarmMemberAssigned { membership_id, farm_id, role }`
- `FarmMemberRevoked { membership_id, farm_id }`

Define event schemas in `app/modules/farms/events.py` as Pydantic models (extend the empty stub from Prompt 1). Subscribe `audit.record(event)` to all of them in `app/modules/farms/__init__.py` or a `subscribers.py`.

### Audit

Every write endpoint produces one audit row via `audit.record(event_type, subject_kind, subject_id, before, after, actor_user_id, correlation_id)`. Use the interface from Prompt 1; do **not** insert directly into `audit_events`.

### Service layer + Protocol

Per `ARCHITECTURE.md` § 6.1: define a `FarmService` Protocol in `app/modules/farms/protocol.py` with the public methods. The implementation lives in `service.py`. Other modules (in later prompts) consume the Protocol, not the implementation.

### Tests

- **Unit tests** for every service method, mocking the DB session.
- **Integration tests** (`pytest` + Postgres service container) for:
  - All CRUD endpoints (200 path + 404 + 403 + 422).
  - Trigger correctness: insert a farm, verify `boundary_utm`, `centroid`, `area_m2` are populated; update boundary, verify they recompute and `aoi_hash` changes for blocks.
  - `is_current` invariant: assigning a new crop flips the prior current to `false` atomically.
  - Soft-archive behavior: archived farms don't appear in default list; can be retrieved by `?include_archived=true`.
  - RBAC: `Viewer` cannot edit; `FarmManager` on Farm A cannot edit Farm B; cross-tenant access returns 404 (not 403 — never confirm existence across tenants).
  - Egypt bounding-box guard rejects out-of-bounds geometry with 422.
  - Geometry validity: self-intersecting polygons rejected with 422.
- **Cross-tenant isolation test** (extends the one from Prompt 1): create two tenants, two users (one in each), prove user A's farm/block reads from tenant B return empty via the API and via raw SQL through the request session.

## Frontend (`frontend/src/`)

### Routes (react-router v6)

- `/farms` — farm list (table + map preview)
- `/farms/new` — farm create
- `/farms/:farmId` — farm detail (header, map, blocks list, members list, attachments tab)
- `/farms/:farmId/edit` — farm edit
- `/farms/:farmId/blocks/new` — block create (manual draw)
- `/farms/:farmId/blocks/auto-grid` — block auto-grid wizard
- `/farms/:farmId/blocks/:blockId` — block detail
- `/farms/:farmId/blocks/:blockId/edit` — block edit
- `/farms/:farmId/members` — member assignment

All routes guarded by the existing OIDC auth wrapper. Inside each route, gate UI controls by capability (use a `useCapability("farm.update", { farmId })` hook backed by the JWT claims).

### Map + draw

- MapLibre GL JS as the base map.
- `mapbox-gl-draw` (or `terra-draw`) wrapped in a thin `<Drawable>` component with rectangle, polygon, and edit modes.
- Base style: a simple OSM raster tile source for now. The vector style + tile-server integration is for Prompt 3.
- Snap-to-self for polygon closing.
- On commit: emit valid GeoJSON in WGS84 to the form state.

### AOI uploads

- GeoJSON: `application/geo+json` or `application/json` — parse, validate, render preview, allow user to accept.
- Shapefile (`.zip` containing `.shp/.shx/.dbf/.prj`): use `shpjs` to parse client-side.
- KML: use `togeojson` (Mapbox) to convert client-side.
- Reject any file >10MB. Reject geometries outside Egypt's bounding box client-side (server enforces too).
- For multi-feature uploads: present a feature picker; user selects which features become the farm boundary vs. which become candidate blocks.

### Crop assignment

- Combobox showing crop name in the active locale (`name_ar` if `i18n.language === 'ar'`, else `name_en`); fallback to `name_en`.
- Variety selector populated by crop selection (optional).
- Date pickers for planting / expected harvest start / end.
- Validation: a block can have at most one `is_current = true` row.

### i18n

- New namespace `farms` with `en/farms.json` and `ar/farms.json`.
- Strings for: every label, button, validation message, empty-state, confirmation dialog. **No hardcoded English in JSX.**
- Numerals: use `Intl.NumberFormat` with the active locale. Egypt's `ar-EG` uses Western digits in modern UX; use `ar-EG` numerals format with `useGrouping: true`.
- Direction: confirmed RTL on every page in `ar` mode. No `margin-left`/`margin-right` — logical properties only.

### Units (feddan / acre / hectare)

- Source of truth is `area_m2` from the API.
- Conversion in a single `lib/units.ts` module: 1 feddan = 4200.83 m² (Egyptian feddan); 1 acre = 4046.86 m²; 1 hectare = 10000 m².
- The user's preferred unit comes from the JWT (`preferred_unit`). The toggle in the header overrides for the session and persists to user prefs (existing `/me` endpoint already supports `preferred_unit`).
- Display areas with one decimal: `12.3 feddan`, with the unit string translated.

### Tests

- Vitest unit tests for: unit conversion, geometry validators, AOI parsers (mock files).
- React Testing Library tests per page: renders correctly in `en` and `ar`; capability gating shows/hides controls; form submission posts the correct payload.
- One Playwright test (optional but encouraged) for the gate criteria below.

# What is explicitly out of scope (do NOT build)

- Any imagery / NDVI / satellite features (Prompt 3).
- Any alert rules, recommendations, condition language (Prompt 4).
- Any weather, signal, or dashboard features (Prompt 5).
- ML-driven field detection or auto-block segmentation. **Grid-based auto-blocking only.**
- GPS perimeter walk for AOI definition (mobile work — Phase 2).
- Activity-log entry forms (Prompt 5).
- Mobile offline app.
- Bulk import via CSV (single-record CRUD plus AOI file upload only).
- Custom crops or crop varieties from tenant UI (curated catalog only — tenants request via support).

If you find yourself wanting to add something not listed in "in scope," **stop and confirm**.

# Definition of done — your gate

You are done with Prompt 2 when **all** of the following are true. Provide evidence in the final PR descriptions.

1. PR-A, PR-B, PR-C are all merged to `main`. CI is green on each. Container images for `api`, `workers`, `frontend` rebuilt and pushed.
2. ArgoCD has synced `dev`. `kubectl get pods -A` shows all pods `Running` (no crash loops). The frontend ingress serves the new pages.
3. **Farm create:** a `TenantAdmin` user signs in via the dev Keycloak, creates a farm via the UI by drawing on the map, and the farm appears in the list with the correct area in feddan.
4. **Block create:** a `FarmManager` (assigned via `farm_scopes`) on that farm creates a block by drawing on the map. The block stores correct WGS84 + UTM 36N geometries (verify in psql); `area_m2` is computed; `aoi_hash` is set.
5. **Auto-grid:** the auto-grid endpoint returns sensible candidate polygons for a 100-feddan farm; the user accepts a subset; they are committed.
6. **Crop assignment:** assigning a crop shows the Arabic crop name when the language toggle is set to `ar`; the previous `is_current` row flipped to `false` atomically.
7. **Attachments (PR-C):** uploading a 5MB photo to a farm via the UI succeeds; an entry appears in `farm_attachments` with correct `s3_key`, `content_type`, `size_bytes`. The same for blocks.
8. **RBAC enforcement:**
   - A `Viewer` on Farm A cannot edit Farm A (UI control hidden; API returns 403).
   - A `FarmManager` on Farm A cannot edit blocks of Farm B (404 — never confirm existence cross-scope).
   - A user with no scope on a farm sees the farm only if they are `TenantAdmin`/`TenantOwner`.
9. **Cross-tenant isolation:** a user in tenant T1 attempting to query farms with an arbitrary `farm_id` belonging to tenant T2 receives 404 from the API and an empty result from raw SQL through the request session. Integration test exists.
10. **Audit trail:** every state-changing action above produced an audit row visible in `audit_events` with correct `subject_kind`, `subject_id`, `actor_user_id`, `correlation_id`. Provide a sample query output.
11. **Cross-schema FK consistency-check:** the periodic Celery Beat job runs in dev; deleting a farm leaves a row in `farm_scopes` referencing the missing farm; the job logs an audit row for the orphan within one cycle.
12. **i18n + RTL:** every page in the farms namespace renders correctly in both `en` (LTR) and `ar` (RTL). No hardcoded English. Logical CSS only. Provide screenshots of farm-list, farm-detail, block-create in both locales.
13. **Tests:**
    - Backend: ≥85% line coverage on `app/modules/farms/` and the migrations. Integration tests cover all gate criteria.
    - Frontend: every page has a render test in en + ar. Unit conversion + geometry validators covered.
14. **Module boundaries:** `import-linter` passes. No reads of another module's tables. `farms` does not import from `imagery`, `alerts`, etc.
15. **OpenAPI:** `/openapi.json` includes all new endpoints with correct schemas, examples, and RFC 7807 error responses. The frontend's typed API client (regenerated from OpenAPI) compiles.

# Reporting back

In each PR description:

- Link to the issue it closes (or describe the gate item it delivers).
- Migration files changed and any irreversible changes called out.
- Screenshots for any UI work (en + ar).
- Test coverage summary.
- Any deviations from `data_model.md` or `ARCHITECTURE.md` — and the ADR opened for them.

In the final (PR-C) description, additionally:

- The full gate-criteria checklist with evidence per item.
- A short "what's next" note: anything Prompt 3 (imagery) will need that came up while building this slice.

# When to stop and ask

- A constraint in `data_model.md` § 5 conflicts with what makes UX sense.
- The Egypt bounding-box guard rejects a legitimate use case.
- `mapbox-gl-draw` vs. `terra-draw` (or any equivalent 50/50 library call).
- The `tilesserver` is unexpectedly needed for the map base style (it shouldn't be — Prompt 3 — but if you trip over it, ask).
- Any cross-module import would be the simplest way out — that's a sign the design is wrong; ask.
- A test failure that suggests a foundation bug rather than a slice bug.

I'd much rather answer five questions than rebuild a slice.

---

Begin by reading the referenced documents and the existing code under `backend/app/modules/farms/`, `backend/app/shared/`, and `frontend/src/`. Then propose the precise file plan for PR-A (which migrations, which models, which routes, which tests) and wait for my approval before writing code.
