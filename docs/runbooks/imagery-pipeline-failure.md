# Imagery pipeline failure

When operators report "blocks aren't getting fresh NDVI" or the imagery
config page shows red badges, this is the recovery path.

The pipeline has four moving parts. Diagnose top-down:

1. **Beat sweep** (`imagery.discover_active_subscriptions`) — finds
   subscriptions due for refresh.
2. **Heavy worker** (`imagery.discover_scenes` → `imagery.acquire_scene`)
   — calls Sentinel Hub Catalog + Process API, writes COGs to S3.
3. **Indices computation** — derives NDVI/EVI/etc., writes
   `block_index_aggregates` rows.
4. **Tile-server** — renders COGs to map tiles for the SPA.

A failure anywhere shows up as the same UX symptom (no fresh imagery),
so jumping to step 2 is tempting and usually wrong.

---

## 1 — Confirm the symptom

```sql
-- Per-block latest scene + age. Run inside the tenant schema.
SET search_path TO tenant_<uuid>, public;
SELECT b.code,
       max(s.scene_datetime) AS latest_scene,
       now() - max(s.scene_datetime) AS age
  FROM blocks b
  LEFT JOIN block_scene_links bsl ON bsl.block_id = b.id
  LEFT JOIN imagery_scenes s ON s.id = bsl.scene_id
 WHERE b.deleted_at IS NULL
 GROUP BY b.code
 ORDER BY age DESC NULLS FIRST;
```

If `age > 7 days` for every block, it's a global pipeline issue. If it's
one block, treat as a subscription issue (§ 3 below).

---

## 2 — Check Beat is enqueueing

```bash
# In dev:
docker logs --tail 200 missionagre-beat | grep imagery
# In cluster:
kubectl logs -n missionagre deploy/beat | grep imagery.discover_active
```

Expected: a line every `imagery_discover_active_subscriptions_seconds`
(default 3600s) showing "discovered N subscriptions, enqueued M".

If silent, Beat itself is wedged. Restart:

```bash
kubectl rollout restart -n missionagre deploy/beat
```

If the log says "discovered 0 subscriptions" but the imagery config
page lists active subs, the SQL filter is wrong; jump to § 3 to verify
subscription rows are healthy.

---

## 3 — Check subscriptions

```sql
SELECT b.code,
       isub.product_code,
       isub.is_active,
       isub.last_attempted_at,
       isub.last_successful_acquisition_at,
       isub.cadence_hours
  FROM imagery_aoi_subscriptions isub
  JOIN blocks b ON b.id = isub.block_id
 WHERE isub.deleted_at IS NULL
 ORDER BY isub.last_attempted_at NULLS FIRST;
```

Telltale signs:

- `last_attempted_at IS NULL` for hours after creation → Beat is silent.
- `last_attempted_at` recent but `last_successful_acquisition_at` stale
  → Sentinel Hub call is failing. Go to § 4.
- `is_active = FALSE` → operator paused it (intentional).

---

## 4 — Check the heavy worker

```bash
kubectl logs -n missionagre deploy/worker-heavy --tail 500 | \
  grep -E "imagery\.(discover|acquire)" | tail -30
```

Common failure modes:

| Log line | Meaning | Fix |
|---|---|---|
| `SentinelHubNotConfiguredError` | Empty `sentinel_hub_client_id` / `_secret` | Restore the `missionagre-sentinel-hub` ExternalSecret. |
| `429 Too Many Requests` | We exceeded the Sentinel Hub rate limit | Throttle: lower `cadence_hours` floor, or wait. The request will retry on the next sweep. |
| `403 Forbidden` from `/api/v1/process` | Account out of credits | Top up the SH balance. Imagery jobs land as `failed`; they self-heal once credits return. |
| `botocore.exceptions.ClientError: PutObject … AccessDenied` | S3 credentials drifted | Restore the `missionagre-s3-uploads` ExternalSecret, restart workers. |
| `IntegrityError uq_imagery_jobs_subscription_scene` | Duplicate-job race | Benign — the second worker was redundant. Ignore. |

If the worker isn't logging at all, it's idle: the queue's empty (Beat
silent — see § 2) or the worker pod is wedged. Restart.

---

## 5 — Check indices computation

The indices Beat task (`indices.compute_index_for_scene`) is chained
from `imagery.acquire_scene`. If imagery rows land but index aggregates
don't:

```sql
SELECT s.id, s.scene_datetime, count(bia.*) AS aggregate_count
  FROM imagery_scenes s
  LEFT JOIN block_index_aggregates bia ON bia.stac_item_id = s.stac_item_id
 WHERE s.scene_datetime > now() - INTERVAL '24 hours'
 GROUP BY s.id, s.scene_datetime
 ORDER BY s.scene_datetime DESC;
```

`aggregate_count = 0` for fresh scenes → check the worker-heavy log for
`indices.compute_index_for_scene` errors. Most common: a block
geometry that doesn't intersect the scene (the AOI lives outside the
tile bounds) — surfaces as `no_pixels_in_aoi`.

---

## 6 — Check the tile-server

If aggregates exist but the SPA still shows blank tiles:

```bash
# Hit the tile-server health endpoint directly
curl https://tiles.missionagre.io/healthz

# Tail logs
kubectl logs -n missionagre deploy/tile-server --tail 100
```

Common: an S3 read-permission drift. The tile-server uses a different
IAM role than the workers. Restore `missionagre-tile-server-s3` if so.

---

## 7 — On-demand re-run

Once the underlying issue is fixed, force a single-block refresh
without waiting for the next Beat tick:

```bash
curl -X POST "https://api.missionagre.io/api/v1/blocks/$BLOCK_ID/imagery/refresh" \
  -H "Authorization: Bearer $JWT"
```

Returns the queued task id. Watch for it in the worker log; the new
scene + aggregates land within ~2 minutes for a healthy stack.

---

## Escalation

If the pipeline is down for > 1 hour and the steps above haven't
isolated the cause, notify the platform on-call channel and start the
postmortem template at `docs/decisions/postmortems/template.md`. The
imagery pipeline is the platform's slowest external dependency, so
extended outages affect SLO; treat them as a P2 incident.
