# Database migrations (in-cluster)

## TL;DR

| Migration kind     | When it runs                                                 | Mechanism                                                                 |
| ------------------ | ------------------------------------------------------------ | ------------------------------------------------------------------------- |
| `public` schema    | Every ArgoCD sync of the `api` chart                         | ArgoCD **PreSync hook Job** — `infra/helm/api/templates/migration-job.yaml` |
| `tenant_<uuid>` schema, **new tenant** | When the api creates a tenant                  | In-process — `app/modules/tenancy/bootstrap.py` runs `alembic upgrade head` against the new schema before the create call returns |
| `tenant_<uuid>` schema, **backfill to existing tenants** | Operator-driven, after a tenant schema-changing migration lands | `kubectl exec` against the api pod — recipe below                  |

Three rules:

1. **One PR per schema-changing migration.** Never bundle a `public` migration with a `tenant` migration in the same PR; the deploy ordering becomes ambiguous.
2. **Public migrations must be backward-compatible with the previous api image** — the PreSync hook runs *before* the new ReplicaSet, so old pods are still serving traffic for ~30s while the new pods roll. Drop-column / rename-column require a two-PR sequence (add-and-dual-write → cut-over → drop).
3. **Tenant migrations are not run by the chart.** A new tenant gets `head` automatically, but existing tenants do *not* — the operator runs the backfill recipe below.

---

## How the PreSync hook works

`migrationJob.enabled: true` in `infra/helm/api/values.yaml` (default `true`) renders a `Job` annotated:

```yaml
argocd.argoproj.io/hook: PreSync
argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
argocd.argoproj.io/sync-wave: "-1"
```

On every ArgoCD sync ArgoCD:

1. Creates the `…-migrate` Job (sync-wave `-1`).
2. Waits for it to reach `Succeeded` (or `Failed`).
3. Only on success does it proceed to apply the rest of the `api` manifests, including the new `Deployment` ReplicaSet.

The Job uses **the new image** (the one ArgoCD is about to deploy), the same `envFrom` as the `Deployment`, plus `DATABASE_PASSWORD` from the CNPG-managed `agripulse-pg-app` Secret. It runs:

```
/opt/venv/bin/alembic -c /app/alembic.ini -n public upgrade head
```

`hook-delete-policy: BeforeHookCreation` keeps a failed Job's Pod around for inspection until the *next* sync — so when a migration fails, the Pod logs are still grep-able. Delete it manually after debugging:

```powershell
kubectl -n agripulse delete job agripulse-api-migrate
```

### What you see in ArgoCD when it fails

The `api` Application stays at the *previous* revision and shows `OutOfSync`. The Job appears in the Application tree with status `Failed`. The `Deployment` is **not** rolled. This is intentional — broken migrations don't kill the running api.

---

## Authoring a public migration

1. Generate the revision:
   ```powershell
   cd backend
   uv run alembic -c alembic.ini -n public revision -m "add foo to bar"
   ```
2. Edit `backend/migrations/public/versions/<rev>_add_foo_to_bar.py`. Keep `upgrade()` idempotent where reasonable (`IF NOT EXISTS`); `downgrade()` is not invoked by the hook but the test suite asserts both directions parse.
3. Validate locally:
   ```powershell
   cd backend
   uv run pytest tests/integration/test_migrations.py -q
   ```
4. Open the PR. The bootstrap-impact checkbox **Adds/modifies a database migration** must be ticked; see `feature-readiness.md`.

---

## Authoring a tenant migration

1. Same `revision` command but `-n tenant`:
   ```powershell
   uv run alembic -c alembic.ini -n tenant revision -m "add bar to foo (tenant)"
   ```
2. The runtime resolves `tenant_<uuid>` at execution time via the `-x schema=…` arg; the migration body **must not** hard-code schema names — use the `current_schema()` pattern (see `migrations/tenant/versions/0003_imagery_subscriptions_and_indices.py` for the canonical example).
3. New tenants created after merge will pick up the migration automatically.
4. **Existing tenants must be backfilled manually** — see next section.

---

## Backfilling a tenant migration to existing tenants

This is the *only* path that needs operator action after a tenant-migration PR merges.

### 1. Confirm the new revision is on the running api image

After the api chart syncs the new image, exec into a pod:

```powershell
$pod = kubectl -n agripulse get pod -l app.kubernetes.io/name=api -o jsonpath='{.items[0].metadata.name}'
kubectl -n agripulse exec $pod -- /opt/venv/bin/alembic -c /app/alembic.ini -n tenant heads
```

You should see the new revision listed. If you don't, the image hasn't rolled — wait for ArgoCD or hard-refresh the `api` Application.

### 2. List tenant schemas

```powershell
kubectl -n cnpg exec -it agripulse-pg-1 -- psql -U agripulse -d agripulse -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%' ORDER BY schema_name;"
```

### 3. Run the migration per tenant

For each tenant schema, exec into the api pod and run alembic against it:

```powershell
$pod = kubectl -n agripulse get pod -l app.kubernetes.io/name=api -o jsonpath='{.items[0].metadata.name}'
$tenants = @('tenant_aaaa…', 'tenant_bbbb…')  # from step 2
foreach ($t in $tenants) {
  Write-Host "==> upgrading $t"
  kubectl -n agripulse exec $pod -- /opt/venv/bin/alembic -c /app/alembic.ini -n tenant -x schema=$t upgrade head
}
```

A migration that fails for one tenant **does not** roll back the others. Log the failed schema, fix the issue (usually a data-shape assumption the migration didn't guard against), and re-run for just that schema.

### Why this isn't automated yet

Fan-out across all tenant schemas is a known gap. The blockers are:

- Tenant migrations sometimes need data-shape decisions per tenant (e.g. backfill defaults that depend on what the tenant already has).
- A blanket Job that runs alembic across every schema would either succeed-or-fail atomically (rollback-everything is rarely what you want) or partially-succeed (which needs reporting that doesn't exist yet).
- The schema list comes from postgres at runtime; a chart-rendered Job can't enumerate it without an init-container that queries pg first.

Track this in the backlog as `scripts/migrate_tenants.py` (referenced from `backend/alembic.ini`); not in scope for Phase 1.

---

## Verifying the flow on shared-dev

Used as the Phase 1 BH-5 exit-gate validation. Run after any change to the migration hook or alembic config:

```powershell
# 1. Confirm PreSync hook ran on last sync
kubectl -n agripulse get jobs -l app.kubernetes.io/component=migrate -o custom-columns=NAME:.metadata.name,SUCCEEDED:.status.succeeded,FAILED:.status.failed,AGE:.metadata.creationTimestamp

# 2. Confirm public schema is at head
$pod = kubectl -n agripulse get pod -l app.kubernetes.io/name=api -o jsonpath='{.items[0].metadata.name}'
kubectl -n agripulse exec $pod -- /opt/venv/bin/alembic -c /app/alembic.ini -n public current

# 3. Confirm at least one tenant schema is at head
$schemas = kubectl -n cnpg exec agripulse-pg-1 -- psql -U agripulse -d agripulse -tAc "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%' LIMIT 1;"
kubectl -n agripulse exec $pod -- /opt/venv/bin/alembic -c /app/alembic.ini -n tenant -x schema=$schemas current
```

All three should show the heads at the revisions you expect.

---

## Recovery recipes

### Migration failed, ReplicaSet didn't roll, need to bisect

```powershell
kubectl -n agripulse logs job/agripulse-api-migrate --tail=200
```

Fix forward in a new PR (don't `--amend` a merged migration). If the failure is transient (e.g. lock timeout), re-trigger a sync from ArgoCD — `BeforeHookCreation` deletes the old Job and creates a fresh one.

### Migration succeeded but is wrong; need to roll back

`alembic downgrade` is **not** wired into the hook (intentional — auto-downgrade hides bugs). Manual procedure:

1. Open a new PR that introduces a forward-fix revision (preferred). Merge + sync.
2. If a forward-fix is impossible, exec into the api pod and `alembic downgrade -1` against the relevant section; then revert the offending PR.

### Schema drift between code and DB ("can't find column X" at runtime)

Almost always means the api pod is *ahead* of the DB schema — i.e. a deploy happened without the migration Job (e.g. `migrationJob.enabled` was set to `false`, or the Job was manually deleted mid-sync). Re-enable, hard-refresh the Application in ArgoCD, and the next sync will run the hook.
