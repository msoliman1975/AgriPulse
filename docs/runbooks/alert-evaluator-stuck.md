# Alert evaluator stuck

When operators report "alerts aren't firing" or "this block obviously has
a problem and we got nothing." The alerts engine is a Beat-driven
pull-based sweep, so "stuck" is rarely literal — usually it's "running
but producing zero candidates."

The recommendations engine runs on the same wiring (Beat + per-tenant
sweep + per-block evaluator), so the diagnosis steps below apply equally
to "no recommendations are firing." Substitute `recommendations.*`
task names where called out.

---

## 1 — Confirm the sweep is running

```bash
kubectl logs -n missionagre deploy/beat | grep "alerts.evaluate_alerts_sweep"
```

Expected cadence: every `alerts_evaluate_sweep_seconds`. Default 1800s
in production, 30 min in dev.

If silent → Beat itself is wedged. Restart:

```bash
kubectl rollout restart -n missionagre deploy/beat
```

If the line says "tenants_scanned=0", `public.tenants` has no
`status='active'` rows — or the API gateway lost its DB connection.

---

## 2 — Confirm the per-tenant evaluator runs

```bash
kubectl logs -n missionagre deploy/worker-light --tail 500 | \
  grep "alerts_tenant_sweep_done"
```

Each tenant sweep logs `blocks_processed=N alerts_opened=M`. If
`blocks_processed=0` for all tenants, the `list_active_block_ids`
query is wrong (tenant has no `status='active'` blocks) or the tenant
has no blocks at all.

If `blocks_processed > 0` but `alerts_opened=0` consistently across
many tenants, jump to § 3. If only one tenant is silent, check whether
all their `default_rules` are overridden disabled in
`tenant_<id>.rule_overrides`.

---

## 3 — Verify rules are active and candidates exist

```sql
SELECT count(*) FROM public.default_rules
 WHERE status = 'active' AND deleted_at IS NULL;
-- expect ≥ 2 (the seed ndvi_severe_drop + ndvi_warning_drop).
```

If 0 → migration 0012 didn't seed; reapply the seed manually.

For one tenant, check whether overrides are blocking everything:

```sql
SET search_path TO tenant_<uuid>, public;
SELECT rule_code, is_disabled, modified_severity
  FROM rule_overrides
 WHERE deleted_at IS NULL;
```

A row with `is_disabled = TRUE` for every default rule_code is the
evaluator's rational reason to fire nothing.

Then check the inputs the engine reads:

```sql
SELECT b.code,
       count(bia.*) AS index_rows,
       max(bia.time) AS latest_index,
       max(bia.baseline_deviation) AS max_dev,
       min(bia.baseline_deviation) AS min_dev
  FROM blocks b
  LEFT JOIN block_index_aggregates bia ON bia.block_id = b.id
 WHERE b.deleted_at IS NULL
 GROUP BY b.code
 ORDER BY latest_index DESC NULLS LAST;
```

`index_rows = 0` → nothing for the engine to evaluate. The imagery
pipeline is upstream — see `runbooks/imagery-pipeline-failure.md`.

`baseline_deviation IS NULL` for every row → no `block_index_baselines`
rows yet. Baselines need ≥ 3 historical observations per (block,
index, day_of_year). Either the data is too new (give it a few weeks
of history) or the recompute Beat task isn't running.

Force a recompute:

```bash
celery -A workers.celery call indices.recompute_baselines_sweep
```

---

## 4 — Re-fire by hand

To fire one block immediately (for a customer demo or to test a fix):

```bash
curl -X POST "https://api.missionagre.io/api/v1/blocks/$BLOCK_ID/alerts:evaluate" \
  -H "Authorization: Bearer $JWT"
```

Returns counts. If `alerts_opened > 0`, an alert row exists; verify it
fanned out via notifications:

```sql
SELECT channel, status, error
  FROM tenant_<uuid>.notification_dispatches
 WHERE alert_id IN (SELECT id FROM tenant_<uuid>.alerts WHERE created_at > now() - INTERVAL '1 minute');
```

`status='skipped'` reasons are surfaced in `error` (no recipients,
channel disabled by tenant, no email on file). `status='failed'` on the
SMTP/webhook channel logs a transport error — see
`runbooks/notifications.md`.

---

## 5 — Stuck-on-evaluation (rare)

If a worker pod is showing CPU pegged on `_evaluate_alerts_for_tenant_async`
and not making progress, suspect a runaway condition tree. The engine
caps tree-walks at 64 steps and the alerts predicate dispatcher only
runs against `default_rules` (whose conditions are hand-maintained), so
this should never happen in practice — but a malformed JSONB blob from
a tenant override could in theory loop forever in an external evaluator.

Fix: `UPDATE rule_overrides SET is_disabled = TRUE WHERE rule_code =
'<suspect>'` and restart the worker. Then audit the override JSONB
shape and tighten the `RuleOverrideUpsertRequest` validator if needed.

---

## 6 — Recommendations equivalent

Substitute task names:
- Beat schedule entry: `recommendations.evaluate_sweep`.
- Per-tenant task: `recommendations.evaluate_for_tenant`.
- Worker log marker: `recommendations_tenant_sweep_done`.

Inputs are the same NDVI aggregates plus weather + signals snapshots,
so the same § 3 query applies.

The decision-tree YAML on disk is loaded into `public.decision_trees`
on app startup. If a freshly-deployed tree isn't firing, check the
backend log for `decision_trees_sync_done` at startup:

```bash
kubectl logs -n missionagre deploy/api | grep decision_trees_sync_done
```

`versions_inserted=0` means the on-disk YAML matches the latest DB
version (idempotent). `versions_inserted=1` means a new version landed.
If neither line shows, the loader crashed; the `decision_trees_sync_failed`
warning will be in the same log.

---

## Escalation

Tag the platform on-call channel if the evaluator has been silent for >
4 sweep cycles (~2 hours in production). Customers won't notice
immediately because alerts are pull-based, but the SLA clock starts
when the first stale alert misses its expected fire window.
