# Sunset of the rules engine (PR-F)

**Status:** Stage 1 (engine disabled, tables retained). Stage 2 (drop
tables) lands in a follow-up after dev/staging confirms alert parity.

## What changed

The rules-driven alerts sweep is removed from Celery Beat. Alerts now
flow exclusively from decision-tree leaves declared with
`kind: alert` (introduced by PR-E). The platform-shipped
`default_rules` rows are replaced 1:1 by the seed YAML tree
`backend/app/modules/recommendations/seeds/ndvi_baseline_alert_v1.yaml`,
which fires the same critical/warning alerts on the same NDVI
baseline-deviation signal — with the added benefit that tenants can
now tune the trigger thresholds via PR-C parameter overrides instead
of editing `rule_overrides` rows.

## What stays — and why

The `alerts/engine.py` module, the `alerts.evaluate_alerts_*` Celery
tasks, and the `default_rules` / `rule_overrides` / `tenant_rules`
tables are all retained in this PR. We keep them for two reasons:

1. **Parity verification.** Existing integration tests under
   `tests/integration/alerts/` exercise the rules code path. Leaving
   the engine importable means we keep the test coverage that proves
   the alerts pipeline (insert → ack → resolve → notifications fan-out)
   still works end-to-end. The tests just don't run on a schedule.
2. **Rollback.** If we discover an alert that the legacy rules used to
   fire but the tree-as-alert seed doesn't, re-enabling Beat for the
   rules sweep is a one-line edit in `workers/beat/main.py` while we
   author the missing tree branch.

The trees engine is now the only source of new alerts in scheduled
sweeps. The `tenant.alerts` table accepts both legacy rule-sourced
rows (which stay open / acknowledged through their existing
lifecycle) and new tree-sourced rows whose `rule_code` is
`tree:{tree_code}:{leaf_node_id}` (PR-E's synthesised key).

## Audit / migration for tenant data

Run `scripts/sunset-rules/audit_tenant_rules.py --schema tenant_<id>`
against each active tenant to surface their authored `tenant_rules`
rows. The script does NOT auto-translate them; output is for human
review. Common patterns:

* **Simple-threshold tenant rules** (90%+ of typical usage): translate
  manually into a tenant-authored single-node tree via the PR-D
  editor at `/settings/decision-trees/new`. Use the same predicate
  shape as `ndvi_baseline_alert_v1.yaml` with `kind: alert` on the
  leaf.
* **Multi-predicate rules** (`condition_tree` predicate kind): same
  shape, but render the multiple branches as a small tree rather
  than a one-leaf tree.

`rule_overrides` rows are usually threshold tweaks; in the new model
those become tenant `tree_parameter_overrides` rows on the platform
`ndvi_baseline_alert_v1` tree. The audit script surfaces these too.

## Stage 2 (future PR)

When dev + staging have run on tree-as-alerts for at least one full
beat cycle without missing any alerts the legacy rules used to fire:

1. Drop the `tenant.rule_overrides` and `tenant.tenant_rules` tables
   (one migration per tenant-schema; both partial unique indexes go
   with them).
2. Drop `public.default_rules` (one migration).
3. Delete `app/modules/alerts/engine.py`,
   `app/modules/alerts/tasks.py`, and the rules-related parts of
   `repository.py` / `service.py`. Keep the alerts table read +
   lifecycle code; the trees engine still writes into it.
4. Update the alerts integration test suite to use tree-as-alert
   fixtures instead of seeded `default_rules` rows.

## Re-enabling rules temporarily (parity-debug only)

If you need to compare a tree-as-alert against the legacy rule for the
same signal:

1. Uncomment the `alerts.evaluate_alerts_sweep` block in
   `backend/workers/beat/main.py`.
2. Restart the Beat container.
3. Compare new rows in `tenant.alerts`: legacy ones have
   `rule_code = 'ndvi_severe_drop'` etc.; tree-sourced ones have
   `rule_code = 'tree:ndvi_baseline_alert_v1:leaf_alert_critical'`.

Remember to disable Beat again before merging anything.
