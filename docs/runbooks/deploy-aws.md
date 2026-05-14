# AgriPulse â€” AWS Deployment Guide

End-to-end deployment guide that maps directly to what's already in this repo
(`infra/terraform/`, `infra/helm/`, `infra/argocd/`). Follow it top-to-bottom
for a fresh `dev` environment in AWS; staging and production are the same flow
with different overlays.

---

## 0. What you'll end up with

- One AWS account hosting one EKS cluster (`agripulse-dev`) in `eu-south-1`
  (Milan â€” Italian/EU data residency per ARCHITECTURE.md
  Â§ 3.2).
- VPC + private subnets, KMS CMK, three S3 buckets (`imagery-raw`,
  `imagery-cogs`, `exports`), five IRSA roles.
- Cluster operators: ingress-nginx, cert-manager, External Secrets,
  CloudNativePG, kube-prometheus-stack, Loki, Tempo, GlitchTip, ArgoCD.
- Application services: `api`, `workers` (light + heavy + beat), `tile-server`,
  `frontend`, `keycloak`, `shared` (CNPG cluster, ClusterIssuers,
  ClusterSecretStore).
- Container images on GHCR: `ghcr.io/msoliman1975/agripulse/{api,workers,tile-server,frontend}`.
- ArgoCD reconciling everything from `main`.

---

## 1. Prerequisites (one-time, on your laptop)

Install:

- AWS CLI v2, `aws configure sso` against the target account.
- Terraform â‰¥ 1.7 (matches `infra/terraform/versions.tf`).
- `kubectl` matching the `cluster_version` (default `1.31`).
- `helm` â‰¥ 3.14, `argocd` CLI, `jq`, `yq`.
- `gh` CLI logged in to GitHub.

Confirm caller identity and region:

```powershell
aws sts get-caller-identity
$env:AWS_REGION = "eu-south-1"
```

In the AWS account, you'll also need:

- A Route 53 public hosted zone you own (e.g. `agripulse.example`). Used for
  `*.dev.agripulse.example`, etc.
- ACM is **not** required â€” cert-manager + Let's Encrypt handles certs (per
  ARCHITECTURE.md Â§ 3.2).
- Quotas: at least 6 Ã— `t3.large` On-Demand vCPU headroom in the region; check
  `Service Quotas â†’ EC2`.

---

## 2. Bootstrap the Terraform state backend (per AWS account, once)

The backend block in `infra/terraform/versions.tf` is intentionally empty; you
supply the values via `-backend-config`. Create the bucket + lock table first:

```powershell
$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$BUCKET  = "agripulse-tfstate-$ACCOUNT"

aws s3api create-bucket `
  --bucket $BUCKET `
  --region eu-south-1 `
  --create-bucket-configuration LocationConstraint=eu-south-1
aws s3api put-bucket-versioning --bucket $BUCKET --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket $BUCKET --server-side-encryption-configuration `
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration `
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

aws dynamodb create-table `
  --table-name agripulse-tfstate-lock `
  --attribute-definitions AttributeName=LockID,AttributeType=S `
  --key-schema AttributeName=LockID,KeyType=HASH `
  --billing-mode PAY_PER_REQUEST `
  --region eu-south-1
```

Cross-check with `docs/runbooks/bootstrap-aws-account.md` if it exists â€” it's
the canonical version of this step.

---

## 3. Provision the substrate with Terraform

```powershell
Set-Location infra\terraform

terraform init `
  -backend-config="bucket=$BUCKET" `
  -backend-config="key=dev/terraform.tfstate" `
  -backend-config="region=eu-south-1" `
  -backend-config="encrypt=true" `
  -backend-config="dynamodb_table=agripulse-tfstate-lock"

terraform plan -var environment=dev -out=dev.tfplan
terraform apply dev.tfplan
```

What this creates (one resource per file in `infra/terraform/`):

- `vpc.tf` â€” VPC `10.30.0.0/16`, three AZs, public + private subnets, single
  NAT for dev.
- `eks.tf` â€” EKS `agripulse-dev`, managed node group (`t3.large` Ã— 3,
  autoscale 2â€“6), OIDC provider for IRSA.
- `kms.tf` â€” customer-managed CMK used for EBS, S3 SSE, and Secrets Manager.
- `s3.tf` â€” `imagery-raw`, `imagery-cogs`, `exports` buckets with the 90-day â†’
  Glacier IR lifecycle rule from ARCHITECTURE.md Â§ 9.
- `iam.tf` â€” five IRSA roles consumed by workloads (API, workers, tile-server,
  External Secrets, CloudNativePG backups).

Capture the outputs you'll need:

```powershell
terraform output -json > ..\..\dev.outputs.json
```

You'll use `cluster_name`, `oidc_provider_arn`, the IRSA role ARNs, and the
bucket names below.

---

## 4. Get cluster access

```powershell
aws eks update-kubeconfig --name agripulse-dev --region eu-south-1
kubectl get nodes
```

Map your IAM principal to a Kubernetes group via the EKS access entry API (the
Terraform module already enables it; if your principal isn't an admin yet, add
an access entry with the `AmazonEKSClusterAdminPolicy` association).

---

## 5. Seed AWS Secrets Manager

External Secrets Operator (installed in step 7) pulls everything below. Create
them once per environment under the path prefix `agripulse/dev/`:

| Secret name | Keys | Used by |
|---|---|---|
| `agripulse/dev/postgres/superuser` | `username`, `password` | CloudNativePG cluster bootstrap |
| `agripulse/dev/postgres/app` | `username`, `password`, `database` | API, workers (Alembic + runtime) |
| `agripulse/dev/keycloak/admin` | `username`, `password` | Keycloak chart |
| `agripulse/dev/keycloak/oidc` | `client_id`, `client_secret` | API JWT verification |
| `agripulse/dev/sentinelhub` | `client_id`, `client_secret` | Imagery provider adapter |
| `agripulse/dev/smtp` | `host`, `port`, `username`, `password` | Notifications |
| `agripulse/dev/webhook-signing-key` | `key` | Outbound webhook HMAC |
| `agripulse/dev/argocd/repo` | `url`, `username`, `password` (or SSH key) | ArgoCD repo creds (private repo) |

Example:

```powershell
aws secretsmanager create-secret --name agripulse/dev/postgres/app `
  --secret-string '{"username":"agripulse","password":"<generated>","database":"agripulse"}' `
  --kms-key-id $(terraform output -raw kms_key_arn)
```

The IRSA role names you'll bind in the Helm values are in `terraform output`.

---

## 6. Install ArgoCD (one-shot, before the AppSets take over)

```powershell
kubectl create namespace argocd
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd `
  --namespace argocd `
  --version 7.6.* `
  --values infra\argocd\overlays\dev\values.yaml
```

Add the repo credential (private repo) and bootstrap:

```powershell
kubectl -n argocd apply -f infra\argocd\appsets\bootstrap.yaml
```

`bootstrap.yaml` is an AppOfApps that creates the four ApplicationSets in
`infra/argocd/appsets/`:

- `platform.yaml` â€” cert-manager, external-secrets, ingress-nginx, CloudNativePG
- `observability.yaml` â€” kube-prometheus-stack, Loki, Tempo, Promtail, GlitchTip
- `services.yaml` â€” api, workers, tile-server, frontend, keycloak, shared
- All values from `infra/argocd/platform-values/*.yaml` and
  `infra/argocd/overlays/dev/values.yaml`.

Watch them go green:

```powershell
argocd login <argocd-host> --sso
argocd app list
argocd app wait -l environment=dev --health --timeout 1200
```

Order of convergence (ArgoCD enforces sync waves; if you break it, this is the
order):

1. cert-manager â†’ ClusterIssuers (in `shared` chart) â†’ External Secrets â†’
   ClusterSecretStore.
2. ingress-nginx (provisions an AWS NLB).
3. CloudNativePG operator â†’ `shared` chart's `Cluster` CR â†’ primary + standby
   running.
4. observability stack.
5. keycloak (waits on Postgres ready).
6. api, workers, tile-server, frontend.

---

## 7. DNS, TLS, and ingress

Once `ingress-nginx` is up, capture the NLB hostname:

```powershell
kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

In Route 53, create ALIAS records pointing to that hostname for the dev names
(these match the ingress hosts in `infra/argocd/overlays/dev/values.yaml`):

- `app.dev.agripulse.example` â†’ frontend
- `api.dev.agripulse.example` â†’ api
- `tiles.dev.agripulse.example` â†’ tile-server
- `auth.dev.agripulse.example` â†’ keycloak
- `argocd.dev.agripulse.example` â†’ argocd
- `grafana.dev.agripulse.example` â†’ grafana

cert-manager reads the `letsencrypt-prod` ClusterIssuer from the `shared` chart
and issues certs automatically. Watch:

```powershell
kubectl get certificate -A
```

---

## 8. Application image pipeline

Images come from `.github/workflows/ci.yml`. To enable pushes:

1. In GitHub repo settings, the `containers` job pushes to
   `ghcr.io/msoliman1975/agripulse/<name>` on merges to `main`. No additional
   setup if you own that GHCR namespace.
2. Make the GHCR packages either **public** (simplest for dev) or create an
   `imagePullSecret` and reference it in each Helm values file:

   ```powershell
   kubectl -n agripulse-dev create secret docker-registry ghcr-pull `
     --docker-server=ghcr.io --docker-username=<gh-user> --docker-password=$env:GHCR_PAT
   ```

3. The `argocd-sync.yml` workflow opens a follow-up PR on every successful main
   build, bumping `image.tag` in `infra/argocd/overlays/dev/values.yaml`.
   Auto-merge this PR for dev; require review for staging/production.

To deploy a build manually before that loop is wired:

```powershell
yq -i '.api.image.tag = "abcdef1"' infra\argocd\overlays\dev\values.yaml
git add . ; git commit -m "chore(dev): bump api to abcdef1" ; git push
```

---

## 9. Database initialization

Postgres comes up empty. You need to:

1. **Install required extensions** (CNPG won't add `pgstac` itself). The
   `shared` chart includes a post-create Job; if it didn't run, exec in:

   ```powershell
   kubectl -n agripulse-dev exec -it agripulse-pg-1 -- psql -d agripulse -c `
     "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS timescaledb; CREATE EXTENSION IF NOT EXISTS pgaudit; CREATE EXTENSION IF NOT EXISTS pgstac CASCADE;"
   ```

2. **Run public-schema migrations** â€” Alembic from the API image:

   ```powershell
   kubectl -n agripulse-dev run alembic-public --rm -it --restart=Never `
     --image=ghcr.io/msoliman1975/agripulse/api:<sha> `
     --env="DATABASE_URL=$(kubectl -n agripulse-dev get secret app-db -o jsonpath='{.data.url}' | base64 -d)" `
     -- alembic -c alembic.ini -x schema=public upgrade head
   ```

3. **Seed reference data** â€” crops, decision trees, capability YAMLs:

   ```powershell
   kubectl -n agripulse-dev exec deploy/api -- python -m app.scripts.seed_reference_data
   ```

4. **Configure Keycloak** â€” the realm JSON in
   `infra/helm/keycloak/files/agripulse-realm.json` is imported on first
   start. Sanity check:
   - Realm: `agripulse`, single client with `tenant_id` mapper.
   - Set the OIDC client secret to match `agripulse/dev/keycloak/oidc`.

---

## 10. Onboarding the first tenant

```powershell
# 1. Provision the tenant row + schema (custom runner from scripts/)
kubectl -n agripulse-dev exec deploy/api -- python -m app.scripts.create_tenant `
  --slug acme --display-name "ACME Farms" --owner-email owner@acme.com

# 2. Apply tenant-schema migrations to that one tenant
kubectl -n agripulse-dev exec deploy/api -- python -m app.scripts.tenant_migrate --tenant acme

# 3. Keycloak: create the TenantOwner user, set initial password
```

The runner is in `backend/scripts/` (and applies migrations from
`backend/migrations/tenant/`). All future tenant migrations are applied by the
same runner in lockstep across all tenants.

---

## 11. Smoke tests

Before declaring "deployed":

```powershell
# Auth flow
curl -i https://auth.dev.agripulse.example/realms/agripulse/.well-known/openid-configuration

# API health
curl -i https://api.dev.agripulse.example/healthz
curl -i https://api.dev.agripulse.example/api/v1/me -H "Authorization: Bearer <jwt>"

# Tile server
curl -i https://tiles.dev.agripulse.example/healthz

# SSE
curl -N https://api.dev.agripulse.example/api/v1/me/alerts/stream -H "Authorization: Bearer <jwt>"

# Frontend
curl -I https://app.dev.agripulse.example/
```

Then trigger an end-to-end satellite path:

1. Create a farm + block via the UI or POST.
2. Trigger an on-demand imagery refresh.
3. Confirm a Celery heavy task ran (`kubectl logs deploy/workers-heavy`), a
   COG was written to the `imagery-cogs` bucket, a STAC item appeared in
   pgstac, and the block-detail timeseries returns a non-empty array.

---

## 12. Observability sign-off

In Grafana:

- `kube-prometheus-stack` dashboards show all pods Ready.
- The FastAPI RED dashboard shows `request_duration_seconds_bucket` for
  `/api/v1/*`.
- Loki has structured JSON logs with `correlation_id`, `tenant_id`.
- Tempo shows traces from the request through Celery into Postgres.
- GlitchTip is empty (no errors).

Alerts wired by `kube-prometheus-stack` defaults: node pressure, pod
crashloop, cert expiry, ingress 5xx rate. Add AgriPulse-specific alert rules
in a follow-up ADR.

---

## 13. Promote to staging and production

The path is the same â€” switch overlays:

```powershell
terraform workspace new staging   # or: -backend-config="key=staging/terraform.tfstate"
terraform apply -var environment=staging
# repeat ArgoCD bootstrap with infra\argocd\overlays\staging\values.yaml
```

Differences enforced by `infra/argocd/overlays/`:

- Staging: auto-sync + smoke-test gate.
- Production: manual sync, prune disabled, restricted hosts, GitHub Environment
  approval before image bump PRs auto-merge.

For production also:

- Multi-AZ NAT (set `single_nat_gateway=false` in TF vars).
- CloudNativePG: 1 primary + 2 standbys, PITR retention 14 days.
- Larger node group; consider `c6i.xlarge` for heavy workers and a dedicated
  taint.
- AWS WAF + Shield Standard on the NLB (via WAFv2 web ACL â†’ ALB ingress, or
  move to ALB controller for L7 WAF).
- Backup the KMS CMK and the Terraform state bucket cross-region.

---

## 14. Day-2 essentials

- **Backups.** CNPG runs continuous WAL archiving to the `imagery-raw` sibling
  bucket (or a dedicated `pg-backups` bucket if you add one). Verify a restore
  quarterly per `docs/runbooks/`.
- **Secrets rotation.** Rotate `keycloak/oidc`, `webhook-signing-key`, and
  `postgres/app` annually. External Secrets re-syncs within `refreshInterval`.
- **Branch protection.** Once the repo is on a paid GitHub plan or public, run
  `scripts/setup-branch-protection.sh`.
- **Cost guardrails.** Enable AWS Budgets at the account level; tag everything
  (`Project=agripulse`, `Environment=dev`) â€” `providers.tf` already does
  this.
- **DR test.** Once per quarter: `terraform destroy` a sandbox env and rebuild
  from scratch using this guide. The whole point of the Terraform/ArgoCD split
  is that this works.

---

That's the whole loop: Terraform brings up the substrate, ArgoCD brings up the
platform and the apps, and the GitHub Actions image-bump PR keeps `dev`
tracking `main`. If anything fails along the way, the runbooks in
`docs/runbooks/` are the first place to look; the second is
`argocd app diff <app>` and `kubectl events -A --sort-by .lastTimestamp`.
