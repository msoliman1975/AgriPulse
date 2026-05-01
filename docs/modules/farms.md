# `farms` module

**Slice:** Slice 1 (Prompt 2 in [`prompts/roadmap.md`](../../prompts/roadmap.md)).
**Schema:** mostly tenant (`farms`, `blocks`, `block_crops`, `*_attachments`); two shared catalog tables in `public` (`crops`, `crop_varieties`) and the cross-schema scope table (`public.farm_scopes`).
**Source:** [`backend/app/modules/farms/`](../../backend/app/modules/farms), [`frontend/src/modules/farms/`](../../frontend/src/modules/farms).

For binding constraints see [`docs/data_model.md` § 5](../data_model.md#5-farms-module) and [`docs/ARCHITECTURE.md` § 6.1](../ARCHITECTURE.md#61-module-boundaries--enforced).

---

## Routes

All paths under `/api/v1/`. Tenant resolution from JWT, never from URL. Errors are RFC 7807 `application/problem+json`.

### Farms

| Method | Path | Capability | Notes |
|---|---|---|---|
| `POST` | `/farms` | `farm.create` | Create. Boundary is a GeoJSON `MultiPolygon` (SRID 4326). |
| `GET` | `/farms` | `farm.read` | Cursor-paginated (`?cursor=&limit=`, default 50, max 200). Filterable by `status`, `governorate`, `tag`. |
| `GET` | `/farms/{farm_id}` | `farm.read` | Detail with full boundary. |
| `PATCH` | `/farms/{farm_id}` | `farm.update` | Geometry changes re-trigger boundary triggers (UTM, centroid, area). |
| `DELETE` | `/farms/{farm_id}` | `farm.delete` | Soft-archive: sets `status='archived'`, `deleted_at=now()`. |

### Blocks

| Method | Path | Capability | Notes |
|---|---|---|---|
| `POST` | `/farms/{farm_id}/blocks` | `block.create` | Boundary is a GeoJSON `Polygon`. |
| `GET` | `/farms/{farm_id}/blocks` | `block.read` | Cursor-paginated. |
| `GET` | `/blocks/{block_id}` | `block.read` | Detail. |
| `PATCH` | `/blocks/{block_id}` | `block.update_geometry` (if boundary changes) and/or `block.update_metadata` | Capability split per [data_model](../data_model.md#15-cross-cutting-concerns). |
| `DELETE` | `/blocks/{block_id}` | `block.delete` | Soft-archive. |
| `POST` | `/farms/{farm_id}/blocks/auto-grid` | `block.create` | Returns candidate `Polygon`s tiled in UTM 36N. **Computes only — does not insert.** |

### Crop assignments

| Method | Path | Capability | Notes |
|---|---|---|---|
| `POST` | `/blocks/{block_id}/crop-assignments` | `crop_assignment.create` | Atomically flips any prior `is_current=true` to `false` before insert. |
| `GET` | `/blocks/{block_id}/crop-assignments` | `block.read` | History. |

### Crops catalog (read-only)

| Method | Path | Capability | Notes |
|---|---|---|---|
| `GET` | `/crops` | tenant-scoped JWT | Optional `?category=`. Returns `name_en` + `name_ar` for locale switching. |
| `GET` | `/crops/{crop_id}/varieties` | tenant-scoped JWT | |

### Members (per-farm RBAC)

| Method | Path | Capability | Notes |
|---|---|---|---|
| `POST` | `/farms/{farm_id}/members` | `role.assign_farm` | Inserts into `public.farm_scopes`. |
| `DELETE` | `/farms/{farm_id}/members/{farm_scope_id}` | `role.assign_farm` | Sets `revoked_at`; does **not** hard-delete. |
| `GET` | `/farms/{farm_id}/members` | `farm.member.read` | |

### Attachments (PR-C)

| Method | Path | Capability | Notes |
|---|---|---|---|
| `POST` | `/farms/{farm_id}/attachments:init` | `farm.attachment.write` | Returns presigned PUT URL + `attachment_id`. 25 MB cap. |
| `POST` | `/farms/{farm_id}/attachments` | `farm.attachment.write` | Finalize after the S3 PUT. Server `head_object`s and verifies size + content-type. |
| `GET` | `/farms/{farm_id}/attachments` | `farm.attachment.read` | List with presigned download URLs (15 min expiry). |
| `DELETE` | `/farms/attachments/{attachment_id}` | `farm.attachment.write` | Soft-deletes the row + removes the S3 object. |

Same shape for `/blocks/{block_id}/attachments`.

---

## RBAC capability matrix

Authoritative source: [`backend/app/shared/rbac/role_capabilities.yaml`](../../backend/app/shared/rbac/role_capabilities.yaml). This is a summary of the farms capabilities only.

| Capability | TenantOwner | TenantAdmin | FarmManager | Agronomist | FieldOperator | Scout | Viewer |
|---|---|---|---|---|---|---|---|
| `farm.create` | ✅ | ✅ | — | — | — | — | — |
| `farm.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `farm.update` | ✅ | ✅ | ✅ | — | — | — | — |
| `farm.delete` | ✅ | ✅ | — | — | — | — | — |
| `farm.member.read` | ✅ | ✅ | ✅ | — | — | — | — |
| `role.assign_farm` | ✅ | ✅ | ✅ | — | — | — | — |
| `block.create` | ✅ | ✅ | ✅ | — | — | — | — |
| `block.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `block.update_geometry` | ✅ | ✅ | ✅ | — | — | — | — |
| `block.update_metadata` | ✅ | ✅ | ✅ | — | — | — | — |
| `block.delete` | ✅ | ✅ | ✅ | — | — | — | — |
| `crop_assignment.create` | ✅ | ✅ | ✅ | — | — | — | — |
| `crop_assignment.update` | ✅ | ✅ | ✅ | ✅ | — | — | — |
| `crop_assignment.delete` | ✅ | ✅ | ✅ | — | — | — | — |
| `farm.attachment.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `farm.attachment.write` | ✅ | ✅ | ✅ | — | ✅ | — | — |
| `block.attachment.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `block.attachment.write` | ✅ | ✅ | ✅ | — | ✅ | — | — |

`PlatformAdmin` grants all capabilities (`*`); `PlatformSupport` grants the read-only subset listed in the role yaml.

Resolution order at request time is **PlatformRole → TenantRole → FarmScope** (first match wins). For routes that take a `farm_id`, the per-farm scope is consulted; for tenant-wide routes (`POST /farms`, `GET /farms`, etc.) only the platform/tenant roles apply.

---

## S3 object layout

Bucket: configurable via `S3_BUCKET_UPLOADS`; defaults to `missionagre-uploads`. Single bucket shared across tenants — isolation is enforced by the key prefix.

```
tenants/<tenant_uuid>/farms/<farm_uuid>/attachments/<attachment_uuid>/<safe_filename>
tenants/<tenant_uuid>/blocks/<block_uuid>/attachments/<attachment_uuid>/<safe_filename>
```

Filenames are sanitized to `[A-Za-z0-9._-]` and truncated to 80 chars (preserving extension). The row's `original_filename` carries the human-friendly name for display.

Upload protocol is two-step (insert-on-finalize):
1. `POST .../attachments:init` → server returns presigned PUT URL + headers. The frontend uses raw `fetch()` (not the axios client) so the JWT bearer header doesn't poison the v4 signature.
2. Browser PUTs the bytes directly to S3.
3. `POST .../attachments` → server `head_object`s the upload, verifies size + content-type match what was declared, inserts the row, audits.

Orphan blobs (init without finalize) are a known follow-up — a janitor Beat job will reap them.

---

## Periodic jobs

### `farms.farm_scope_consistency_check`

Defense-in-depth backstop for the **logical** FK from `public.farm_scopes.farm_id` into each tenant's `farms` table. Postgres can't enforce that across schemas, so this job runs hourly:

1. Loads every active (non-revoked) `farm_scope` joined to `tenants.schema_name`.
2. Groups by tenant schema (sanitized through `sanitize_tenant_schema()`).
3. Per schema, runs one bulk `SELECT id FROM <schema>.farms WHERE deleted_at IS NULL AND id = ANY(:ids)`.
4. Per orphan, writes one `audit_events` row with `subject_kind=farm_scope_orphan`, `event_type=farms.farm_scope_orphan_detected`.

**Never deletes the orphan.** Observation only — ops or a future janitor decides what to do with the audit signal.

Cadence: tunable via `FARM_SCOPE_CONSISTENCY_CHECK_SECONDS` (default 3600). Routed to the `light` Celery queue. Source: [`backend/app/modules/farms/consistency_check.py`](../../backend/app/modules/farms/consistency_check.py).

---

## Domain events

Defined in [`backend/app/modules/farms/events.py`](../../backend/app/modules/farms/events.py). Subscribed by `audit` (sync, in-request); imagery and alerts will subscribe in later slices.

| Event | When | Notable payload |
|---|---|---|
| `FarmCreatedV1` | `POST /farms` succeeds | `farm_id`, `code`, `name`, `area_m2` |
| `FarmUpdatedV1` | `PATCH /farms/{id}` | `farm_id`, `changed_fields` |
| `FarmArchivedV1` | `DELETE /farms/{id}` | `farm_id` |
| `FarmBoundaryChangedV1` | Boundary replaced | `farm_id`, new centroid (lon, lat) — imagery hooks here in Slice 2 |
| `BlockCreatedV1` | `POST /farms/{id}/blocks` | `block_id`, `farm_id`, `code`, `area_m2`, `aoi_hash` |
| `BlockUpdatedV1` / `BlockArchivedV1` | | |
| `BlockBoundaryChangedV1` | Block boundary replaced | `prev_aoi_hash`, `new_aoi_hash` — imagery cache invalidation |
| `BlockCropAssignedV1` / `BlockCropUpdatedV1` | Crop assignment lifecycle | `block_crop_id`, `block_id`, `crop_id` |
| `FarmMemberAssignedV1` / `FarmMemberRevokedV1` | Per-farm role grants | |
| `Farm/BlockAttachmentUploadedV1` | Attachment finalize | `attachment_id`, `kind`, `size_bytes`, `content_type` |
| `Farm/BlockAttachmentDeletedV1` | Attachment soft-delete | `attachment_id` |

---

## Frontend routes

All under `/farms`. Guarded by the OIDC auth wrapper; controls within each route are gated by the [`useCapability(name, { farmId? })`](../../frontend/src/rbac/useCapability.ts) hook.

```
/farms                                       # list
/farms/new                                   # create
/farms/:farmId                               # detail (map preview, blocks list, attachments tab)
/farms/:farmId/edit
/farms/:farmId/members                       # member assignment
/farms/:farmId/blocks/new                    # manual draw
/farms/:farmId/blocks/auto-grid              # grid wizard
/farms/:farmId/blocks/:blockId               # block detail (crop assignment, attachments tab)
/farms/:farmId/blocks/:blockId/edit
```

i18n: `en` and `ar` namespaces under [`frontend/src/i18n/locales/{en,ar}/farms.json`](../../frontend/src/i18n/locales). All strings are translated; logical CSS only (no `margin-left/right`); Latin numerals in Arabic UI per ARCHITECTURE.md § 11.

Areas come back from the API in `m²`; the frontend converts to the user's preferred unit (feddan / acre / hectare) at the presentation layer via [`frontend/src/lib/units.ts`](../../frontend/src/lib/units.ts).

---

## Geometry handling

- All input geometries are GeoJSON in **WGS84 (SRID 4326)**.
- `farms.boundary` is a `MultiPolygon`; `blocks.boundary` is a `Polygon`.
- Triggers in the tenant migration (`0002_farms_blocks_attachments.py`) compute `boundary_utm` (transform to **UTM 36N / EPSG:32636**), `centroid`, and `area_m2 = ST_Area(boundary_utm)` on every insert/update. For blocks, the trigger also recomputes `aoi_hash = sha256(ST_AsText(boundary_utm))` so imagery can key cached scenes by geometry identity.
- The API rejects (422) any input that is not a valid Polygon/MultiPolygon, that self-intersects (`ST_IsValid`), or whose bounding box falls outside Egypt (lon `24..36`, lat `22..32`).

---

## Tests

- **Backend unit:** `backend/tests/unit/farms/` — events, geometry helpers, auto-grid, attachment service, consistency-check.
- **Backend integration:** `backend/tests/integration/farms/` — currently `@pytest.mark.skip` on a known asyncpg + UUID encoding issue. Restore once the upstream fixture is fixed.
- **Frontend unit:** vitest under `frontend/src/**/*.test.{ts,tsx}` — units, geometry, AOI parsers, RBAC hook, every page in en + ar, AttachmentsTab.
- **End-to-end:** **not yet implemented.** Tracked as a follow-up.

---

## Known gaps and follow-ups

- Playwright E2E covering the full happy path (sign in → farm → block → crop → attachment → ar locale).
- Orphan-blob janitor for attachment uploads that init but never finalize.
- A janitor that revokes orphaned `farm_scopes` (today the consistency-check job only audits).
- Backend integration suite re-enable (asyncpg/UUID issue).
- Frontend bundle code-split — MapLibre + Turf + shpjs push the initial chunk to ~1.5 MB ungzipped.
