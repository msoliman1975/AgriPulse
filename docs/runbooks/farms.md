# Runbook: `farms` module

> **Status:** stub. Per `prompts/prompt_02_farm_management.md` § "PR-C", Prompt 6 fills this out properly. The sections here are skeletons — symptom → triage → resolution — so the on-call team has somewhere to land while we ship the rest.

For the full module reference (routes, RBAC, S3 layout, events, periodic jobs) see [`docs/modules/farms.md`](../modules/farms.md).

---

## Quick links

- Source: [`backend/app/modules/farms/`](../../backend/app/modules/farms), [`frontend/src/modules/farms/`](../../frontend/src/modules/farms)
- Capabilities: [`backend/app/shared/rbac/role_capabilities.yaml`](../../backend/app/shared/rbac/role_capabilities.yaml)
- Tenant migration: [`backend/migrations/tenant/versions/0002_farms_blocks_attachments.py`](../../backend/migrations/tenant/versions/0002_farms_blocks_attachments.py)
- S3 bucket (dev): `missionagre-uploads` (configurable via `S3_BUCKET_UPLOADS`)
- Beat schedule: [`backend/workers/beat/main.py`](../../backend/workers/beat/main.py)

---

## Common incidents

### Farm creation returns 422 "Geometry outside Egypt"

**Triage:** the API rejects any geometry whose bounding box falls outside `lon 24..36, lat 22..32`. This is a sanity guard — see `app/modules/farms/geometry.py`.

**Resolution:**
- Verify the user's GeoJSON is in WGS84 (SRID 4326), not UTM. Common mistake: a Shapefile with a non-WGS84 `.prj` will parse but yield large coordinate values.
- If a legitimate farm is being rejected (Egyptian border edge cases), open an ADR before widening the bounding box.

### Farm creation returns 422 "Geometry invalid" / "self-intersect"

**Triage:** `ST_IsValid` rejected the polygon, or `kinks()` found self-intersections in the frontend pre-check.

**Resolution:**
- Ask the user to re-draw — the most common cause is a bow-tie polygon from manual editing.
- For uploaded files, run `ST_MakeValid` in psql to inspect what Postgres sees.

### Farm shows `area_m2 = 0` after create

**Triage:** the `boundary_utm` trigger didn't fire or the geometry collapsed during the UTM 36N transform (very high-latitude polygons fall outside zone 36's projection domain).

**Resolution:**
- Confirm in psql:
  ```sql
  SET search_path TO tenant_<tenant_id>, public;
  SELECT id, area_m2, ST_Area(boundary_utm) FROM farms WHERE id = '<farm_id>';
  ```
- If `ST_Area(boundary_utm)` is non-zero but `area_m2 = 0`, the `*_at` trigger ordering is wrong — escalate, this is a migration regression.

### Auto-grid returns no candidates

**Triage:** input cell size is wider than the farm's bounding box, or the farm is irregularly shaped and no full cell intersects.

**Resolution:**
- Pick a smaller `cell_size_m` (default 500). For a 100-feddan farm (~420k m²), 200 m × 200 m gives ~10 cells.
- This isn't an error — surface it as the empty state on the auto-grid page.

### Attachment upload fails at the PUT step

**Triage:** the presigned URL was returned by `:init` but the browser PUT to S3 returned a non-2xx.

**Resolution:**
- Confirm the frontend is sending `Content-Type` and `Content-Length` headers exactly as returned by `:init`. Any drift breaks the v4 signature.
- Confirm the JWT bearer header is **not** being attached. The `apiClient` interceptor would corrupt the signature; the upload helper at `frontend/src/lib/upload.ts` uses raw `fetch()` to avoid this.
- Check MinIO/S3 logs for the bucket — common dev failure is the bucket not being provisioned. The `minio-init` sidecar in `infra/dev/compose.yaml` should create `missionagre-uploads`.

### `audit_events` rows showing `farm_scope_orphan_detected`

**Triage:** the consistency-check Beat job found a row in `public.farm_scopes` whose `farm_id` no longer exists (or is soft-deleted) in the tenant's `farms` table.

**Resolution:**
- The audit row is informational — the job intentionally does not delete. Possible causes:
  - A farm was hard-deleted in psql (should never happen — soft-archive is the contract).
  - A farm was archived in tenant A while a `farm_scope` for it lived in tenant B (cross-tenant FK leak — investigate immediately, this is a data integrity bug).
  - Schema name in `tenants.schema_name` doesn't match the actual schema.
- Inspect:
  ```sql
  SELECT * FROM public.audit_events
   WHERE event_type = 'farms.farm_scope_orphan_detected'
   ORDER BY occurred_at DESC LIMIT 50;
  ```
- Manual cleanup (after triage): `UPDATE public.farm_scopes SET revoked_at = now() WHERE id = '<orphan_id>';`

### Cross-tenant data exposure (suspected)

**Triage:** **stop and escalate.** The tenancy contract is that `SET LOCAL search_path TO tenant_<id>, public` is the only path to tenant data and that no SQL crosses schemas.

**Resolution:**
- Confirm with `app/shared/db/session.py:_set_search_path` that the request's schema was set correctly.
- Run the cross-tenant isolation integration test: `pytest backend/tests/integration/test_search_path_isolation.py`.
- If the test passes but a leak is observed, investigate the audit middleware and any code path that uses `get_admin_db_session()` (admin sessions only see `public`).

---

## Periodic job control

### Pause / resume the consistency-check job

To pause without redeploying, set the cadence high in the cluster's ConfigMap and roll the Beat pod:

```bash
kubectl set env deploy/missionagre-beat FARM_SCOPE_CONSISTENCY_CHECK_SECONDS=86400 -n missionagre
kubectl rollout restart deploy/missionagre-beat -n missionagre
```

To force a one-off run from a worker shell:

```python
from app.modules.farms.tasks import farm_scope_consistency_check
farm_scope_consistency_check.delay()
```

---

## What's not in this runbook (yet)

- Imagery pipeline failures (Slice 2).
- Alert rule misfires (Slice 4).
- Subscription / billing incidents (Slice 5+).
- DR / backup / restore (Prompt 6).

These get filled in as their slices ship.
