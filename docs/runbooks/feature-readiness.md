# Feature readiness — bootstrap-impact checklist

Companion to the **Bootstrap impact** section of
`.github/PULL_REQUEST_TEMPLATE.md`. Each tickbox below has a failure
mode — usually one that's silent in dev (because the operator already
ran a one-time hand-patch) and loud the first time someone does a
fresh `terraform apply` + ArgoCD sync on a new account.

This runbook exists because Phase 1 of the execution plan turned up
too many "works in shared-dev, breaks fresh installs" cases.

---

## 1. Adds or renames an env var

**Failure mode:** Pod CrashLoopBackOff on import with `KeyError`, or
silently picks up `""` and behaves wrong at runtime.

**Where it has to land:**

- `infra/helm/<chart>/values.yaml` under `env:` (chart-default,
  fine for every env).
- If per-env: `infra/argocd/overlays/<env>/values.yaml` under
  `env:` (overlay-level, override per env).
- If sensitive: see "Adds or renames a secret" below — env-var rules
  don't apply, secret rules do.

**Verify:**

```powershell
helm template api infra/helm/api -f infra/argocd/overlays/dev/values.yaml | Select-String "NAME_OF_VAR"
```

The value should render correctly. Watch for `{{ .Values.x }}`
literals leaking through — usually means `tpl` wasn't used where it
should have been.

---

## 2. Adds or renames a secret

**Failure mode:** ExternalSecret stays in `SecretSyncedError`, the
target k8s Secret is empty, the pod that consumes it
CrashLoopBackOff on missing env var.

**Where it has to land:**

1. AWS Secrets Manager. Add to `scripts/deployment-data.example.yaml`
   so a fresh operator knows to seed it. Add to the seed-secrets map
   in `scripts/deploy-aws.ps1` (`Invoke-SeedSecrets`).
2. `infra/helm/<chart>/values.yaml` under
   `externalSecret.crossRefs` (chart-level wiring of SM → k8s).
3. If the value is per-env (most are): no overlay change needed —
   the `remoteKey` template uses `.Values.global.env` and resolves to
   `agripulse/dev/...` / `agripulse/staging/...` / `agripulse/prod/...`
   automatically.

**Verify:**

```powershell
kubectl -n agripulse get externalsecret agripulse-api -o yaml | Select-String -Pattern "status:" -Context 0,10
```

Should show `Ready: True`. If not, the SM secret doesn't exist or the
IRSA role for ESO lacks `secretsmanager:GetSecretValue` on that ARN.

---

## 3. Adds or modifies a database migration

**Failure mode:** Either the api pod can't start because the schema
isn't there (PreSync hook didn't run), or the previous api pod
breaks because the migration is *not* backward-compatible with the
image it's running.

**Where it has to land:**

- `backend/migrations/public/versions/<rev>_*.py` for public.
- `backend/migrations/tenant/versions/<rev>_*.py` for tenant.
- Nothing in the chart — the PreSync hook
  (`infra/helm/api/templates/migration-job.yaml`) picks up the new
  revision automatically because it runs alembic against the new
  api image.

**Verify backward-compatibility:**

Add the column, *then* dual-write, *then* read from the new column,
*then* drop the old — across three PRs minimum if you're
renaming/dropping. A `DROP COLUMN` migration that ships in the same
PR as the read-site update will break in-flight requests on the
previous ReplicaSet during the rollout.

**Tenant backfill:**

If existing tenants need the migration, the operator runs the
backfill recipe in `docs/runbooks/migrations.md`. Call this out in
the PR description so it doesn't get missed at deploy time.

---

## 4. Adds a new ServiceAccount or changes IRSA wiring

**Failure mode:** Pod gets a token for the node-role and either has
too many perms (security) or `AccessDenied` on what it actually
needs (functional).

**Where it has to land:**

- `infra/helm/<chart>/values.yaml` under `serviceAccount:` with one
  of the two opt-out markers (`# irsa: not-required` or
  `# irsa: required-from-overlay`) — required to satisfy
  `scripts/lint_irsa.py`.
- If `required-from-overlay`: add the role in
  `infra/terraform/iam-irsa.tf`, run `terraform apply`, then set the
  ARN in `infra/argocd/overlays/<env>/values.yaml` under the chart's
  `serviceAccount.annotations`.

**Verify:**

```powershell
python scripts/lint_irsa.py
```

Then in-cluster after deploy:

```powershell
kubectl -n agripulse exec deploy/agripulse-api -- aws sts get-caller-identity
```

The returned ARN should be the IRSA role, not the node role.

Full runbook: `docs/runbooks/irsa-hygiene.md`.

---

## 5. Adds a new EKS managed add-on

**Failure mode:** Add-on stuck in `CREATING` indefinitely if it
needs IRSA and you forgot `service_account_role_arn`. EBS CSI is
the canonical example — see `project_eks_addon_irsa` memory.

**Where it has to land:**

- `infra/terraform/eks.tf` `cluster_addons = {}` block.
- If it has a controller pod that hits AWS APIs: also add the addon
  name to `ADDONS_REQUIRING_IRSA` in `scripts/lint_irsa.py` and wire
  `service_account_role_arn` to a module in `iam-irsa.tf`.

**Verify:**

```powershell
python scripts/lint_irsa.py
aws eks describe-addon --cluster-name agripulse-dev --addon-name <name> --region eu-south-1
```

`status` should reach `ACTIVE`, not stay in `CREATING`.

---

## 6. Adds a new container image or changes Dockerfile

**Failure mode:** Multi-arch CI build fails (no arm64 wheel for a
Python package, or the base image is amd64-only); or the image is
built but the chart pins `nodeSelector.kubernetes.io/arch: amd64`
and you forgot to drop the pin when the image went multi-arch.

**Where it has to land:**

- The Dockerfile. Base images should be pinned by digest (`@sha256:`),
  not by tag — see BH-3 and `renovate.json`.
- `.github/workflows/ci.yml` `containers` matrix — add a new entry
  if a new image, or leave alone if just changing an existing one.
  Match the matrix's `platforms:` to what the image actually
  supports (e.g. titiler is amd64-only — see `858949d`).
- If multi-arch: drop any `nodeSelector.kubernetes.io/arch: amd64`
  in the chart values.yaml.

**Verify:**

CI green for the `containers` matrix. Then:

```powershell
docker manifest inspect ghcr.io/msoliman1975/agripulse/api:<tag> | jq '.manifests[].platform'
```

Should list both `linux/amd64` and `linux/arm64` for the multi-arch
images.

---

## 7. Adds a new Helm chart or top-level overlay change

**Failure mode:** Chart doesn't get synced because the
ApplicationSet doesn't know about it; or it syncs but with the wrong
values because the overlay's per-chart block is missing.

**Where it has to land:**

- `infra/helm/<chart>/` — the chart itself.
- `infra/argocd/appsets/agripulse-services.yaml` — add to the
  generator so the ApplicationSet creates an Application for it.
- `infra/argocd/overlays/<env>/values.yaml` for each env, even if
  the per-env block is just empty.

**Verify:**

```powershell
helm template <chart> infra/helm/<chart> -f infra/argocd/overlays/dev/values.yaml
```

Should render cleanly. Then after merge, ArgoCD UI shows the new
Application in `Synced` + `Healthy`.

---

## 8. Touches the cluster-bootstrap path

Cluster-bootstrap = anything that runs on the first sync of a fresh
cluster and is needed for the api to come up at all. Specifically:

- Keycloak realm import / promote-bootstrap Job (BH-2)
- Seed secrets script (`scripts/deploy-aws.ps1 -Phase seed-secrets`)
- PreSync migration Job (BH-5)
- CNPG Cluster CR + database/role bootstrap
  (`infra/helm/shared/templates/keycloak-db-bootstrap-job.yaml`)
- ArgoCD Application ordering (sync-waves, dependencies)

**Failure mode:** New cluster never reaches a usable state on a
fresh `terraform apply`. Hard to test pre-merge because shared-dev
already has all the bootstrap state.

**Verify:**

Either:
- Run a full bootstrap dry-run in an isolated AWS account (slow but
  authoritative).
- Or at minimum: re-render every chart + every overlay with `helm
  template`, walk the resulting manifests for the changed bootstrap
  resource by hand, and confirm the wiring still makes sense from
  zero state.

Call out the bootstrap-impact explicitly in the PR description so
the operator knows to watch the first-install path on the next fresh
deploy.

---

## When in doubt

Read `docs/runbooks/aws-fresh-install.md`. If the change you're
making would alter any step in that runbook (renumbering, reordering,
adding a step), the runbook itself must be updated in the same PR.
