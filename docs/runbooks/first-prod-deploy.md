# Runbook: first production deploy

The first push of AgriPulse to the production EKS cluster. After this
runbook, prod promotions follow `docs/runbooks/promotion-procedure.md`.

The whole flow takes ~60â€“90 minutes wall time, most of which is waiting
on cert issuance, DNS propagation, and the ArgoCD sync waves. Do not
parallelise the steps below â€” each gates the next.

---

## 0. Pre-flight (do not skip)

- [ ] Dev and staging have been **Healthy + Synced** for 24h continuous.
  `argocd app list -l agripulse.cloud/env in (dev,staging)` â€” every row green.
- [ ] No active alerts in GlitchTip or kube-prometheus-stack for either env.
- [ ] CNPG `Cluster` in staging shows `phase: Cluster in healthy state` and
  the most recent `ScheduledBackup` succeeded:
  `kubectl -n agripulse get backups -l cnpg.io/cluster=agripulse-pg`.
- [ ] The image tags you intend to promote have been running in staging
  for â‰¥ 24h. Note the four SHAs (`api`, `workers`, `frontend`,
  `tile-server`) â€” you will set them in step 3.
- [ ] On-call engineer is reachable and knows production is going live now.
- [ ] You have console access to the prod AWS account and `argocd` CLI
  context set to the prod cluster.

If any box stays unchecked, stop. Fix it in staging first.

---

## 1. Seed production secrets in AWS Secrets Manager

Production secrets are not in Terraform state â€” they are seeded by hand
once per environment. Follow `docs/runbooks/seeding-secrets.md` Â§ 1
with `ENV=prod`. The five values you need before sync:

- `agripulse/prod/brevo-smtp-password`
- `agripulse/prod/keycloak-admin-password`
- `agripulse/prod/sentinel-hub-client-secret`
- `agripulse/prod/jwt-signing-key`
- `agripulse/prod/postgres-superuser-password`

Verify each is set (not just declared) before continuing:

```bash
for s in brevo-smtp-password keycloak-admin-password \
         sentinel-hub-client-secret jwt-signing-key \
         postgres-superuser-password; do
  aws secretsmanager describe-secret --region me-south-1 \
    --secret-id "agripulse/prod/$s" \
    --query 'VersionIdsToStages' --output text
done
```

Every line should print at least one version ID. A blank result means
the secret resource exists but has no value â€” Pods will crash-loop.

---

## 2. Confirm prod ApplicationSet is wired but not auto-syncing

```bash
argocd app list -l agripulse.cloud/env=production
```

Each row should show `Sync Policy: <none>` (manual). The
`syncPolicy.automated` block is intentionally absent for production in
`infra/argocd/appsets/services.yaml` â€” staff promote prod by hand.

If any row shows `Auto-Sync: Enabled` for prod, **abort** and audit the
AppSet diff before continuing.

---

## 3. Open the tag-bump PR

Edit `infra/argocd/overlays/production/values.yaml`, set the four image
tags to the SHAs that have soaked in staging:

```yaml
global:
  images:
    api:        { tag: "<sha>" }
    workers:    { tag: "<sha>" }
    frontend:   { tag: "<sha>" }
    tileServer: { tag: "<sha>" }
```

Push as a PR titled `chore(prod): bump images to <short-sha>`. CODEOWNERS
require two approvals before merge (see promotion runbook).

After merge, ArgoCD detects the new commit on `main` within the
default 3-minute reconcile.

---

## 4. First sync

Watch the prod Applications. Order matters â€” the shared chart must
land before the workload charts (ClusterIssuers, CNPG Cluster,
ClusterSecretStore are prerequisites):

```bash
argocd app sync shared-production
argocd app wait shared-production --health --timeout 600

# Then services, in any order:
for app in api-production workers-production tile-server-production \
           frontend-production keycloak-production; do
  argocd app sync "$app"
done

argocd app wait -l agripulse.cloud/env=production \
  --health --timeout 1800
```

If `wait` times out, drop into:

```bash
argocd app get <name> --show-operation
kubectl -n agripulse describe pod -l app.kubernetes.io/name=<name>
```

Common first-time hangs:

- ExternalSecret stuck `SecretSyncedError` â†’ secrets weren't seeded
  (back to Â§ 1) or IRSA isn't bound on the controller's ServiceAccount.
- CNPG primary not electing â†’ check `kubectl logs -n cnpg-system
  deploy/cnpg-controller-manager`; usually IRSA on the cluster's SA.
- cert-manager `Order` in `pending` for > 5 minutes â†’ ExternalDNS
  hasn't published the `_acme-challenge` TXT record yet. Tail
  `kubectl logs -n external-dns deploy/external-dns`.

---

## 5. Confirm the migration Job ran

The api chart's PreSync hook runs `alembic upgrade head` against the
prod CNPG cluster before the api Deployment rolls. If the Job fails,
the sync stops and the previous version stays up.

```bash
kubectl -n agripulse get jobs -l app.kubernetes.io/component=migrations
kubectl -n agripulse logs job/<migration-job-name>
```

Expect `INFO [alembic.runtime.migration] Running upgrade ...` ending in
the most recent revision and a `0` exit code. If it failed, see
`docs/runbooks/failed-migration-recovery.md` â€” migrations are forward-only,
so a manual `alembic downgrade` is the recovery path if the rollout
itself needs reverting.

---

## 6. Smoke tests

The first command must return 200 before any of the rest are meaningful.

```bash
# 6a. API health
curl -fsSL https://api.agripulse.cloud/health
# â†’ 200, body: {"status":"ok"}

# 6b. Keycloak discovery
curl -fsSL https://keycloak.agripulse.cloud/realms/agripulse/.well-known/openid-configuration | jq .issuer
# â†’ "https://keycloak.agripulse.cloud/realms/agripulse"

# 6c. Frontend served
curl -fsI https://app.agripulse.cloud/ | head -1
# â†’ HTTP/2 200

# 6d. Tile server health
curl -fsSL https://tiles.agripulse.cloud/healthz
# â†’ 200
```

Then in the browser, walk one happy-path through each module:

- Log in via Keycloak as the seeded platform-admin user.
- Create a test tenant from `/platform/tenants`.
- Inside the tenant: create a farm + one block (smoke imagery path).
- Trigger one weather refresh; confirm a recommendation appears.
- Create one custom signal threshold; confirm a notification fires.

Tear down the test tenant before declaring done (or leave it parked as
`prod-smoke-<date>` for the next deploy's regression check â€” team
preference; just be consistent).

---

## 7. DNS + TLS warm-up

Route 53 records for prod ship with a 300s TTL. After the first sync
they propagate within ~5 minutes worldwide, but resolvers caching the
older NXDOMAIN can lag. **Wait 5 full minutes before claiming green**,
even if your own dig is happy:

```bash
dig +short api.agripulse.cloud @1.1.1.1
dig +short api.agripulse.cloud @8.8.8.8
```

cert-manager issues prod certs from the `letsencrypt-prod` issuer (rate
limit: 50/week per registered domain). If you see a staging cert in the
browser, the overlay didn't override `cluster-issuer` â€” re-check
`infra/argocd/overlays/production/values.yaml`.

---

## 8. Rollback

The promotion knob is the image-tag bump in the overlay. Reverting is
two commits, not a kubectl operation.

```bash
git revert <merge-sha-from-step-3>
git push
```

ArgoCD reconciles the previous SHA on the next sync. Manual trigger:

```bash
argocd app sync api-production
```

**Caveat â€” migrations are forward-only.** If the rolled-back image
needs a schema older than what just ran, you have to downgrade by hand:

```bash
kubectl -n agripulse exec -it deploy/api -- \
  alembic -c alembic.ini downgrade <revision>
```

The runbook for chained-failure recovery is
`docs/runbooks/failed-migration-recovery.md`. Most rollbacks do not
need this â€” the prod release cadence keeps migrations small and
forward-compatible by policy.

---

## 9. Sign-off

When all of:

- ArgoCD shows every prod app Healthy + Synced.
- The four smoke endpoints return 200.
- One browser walkthrough of the five module flows completed.
- GlitchTip is empty for the last 15 minutes.
- DNS has had â‰¥ 5 minutes since the first record published.

â€¦post in the deploys channel with the four image SHAs, the PR link, and
the timestamp. That is the deploy record.
