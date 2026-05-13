# Application containerization + AWS deployment strategy — Agri.Pulse

Status: **active strategy of record.** Replaces the prior ECS Fargate proposal (2026-05-09), which is now obsolete. Locked 2026-05-12 after a 1:1 review of the on-disk infra state with the maintainer.

This document is the source of truth for how Agri.Pulse is containerized and how it deploys to AWS. Per-PR runnable prompts live in `docs/prompts/containerization/CD-{1..15}.md`.

---

## 1. Locked decisions

| Area | Choice | Rationale |
| --- | --- | --- |
| Platform | **EKS + ArgoCD + Helm** | 60–70 % of the scaffolding already exists in `infra/`. Pivoting to ECS would discard weeks of work. |
| Region | **me-south-1 (Bahrain)** | Lowest latency to MENA/Gulf customers. ~10–20 % pricier than eu-west-1; trade accepted. |
| Accounts / envs | **One AWS account, three Kubernetes namespaces** (`dev`, `staging`, `prod`) | Cheapest option. Blast-radius isolation is weaker than separate accounts — compensated by `terraform plan` review and ArgoCD dry-runs. |
| Postgres | **In-cluster CloudNativePG** (already templated in `infra/helm/shared/`) | Cost + cloud-provider portability. User accepts the ops burden. |
| Postgres backups | **S3 + Barman Cloud, 30-day PITR** | The only credible DR story for in-cluster Postgres. |
| Redis | **In-cluster** | Celery broker; brief loss is recoverable. Portable. |
| Object storage | **S3** (MinIO dev-only) | S3 is the one AWS-managed service that stays portable via the S3-compatible API. |
| Observability | **Self-hosted: kube-prometheus + Loki + Tempo + GlitchTip** (already charted in `infra/argocd/platform-values/`) | Portability. Consistent with the in-cluster data-plane decision. |
| Domain | **`agripulse.cloud`** (user-owned) | Route 53 + cert-manager + Let's Encrypt + ExternalDNS. |
| Compute | **Karpenter on a small managed-node baseline + EC2 spot** | Best cost/elasticity ratio. Industry default for new EKS. |
| Email | **Brevo SMTP** (unchanged) | Already working. SES adds DNS work + sandbox-removal lag for marginal cost savings at current volume. |
| Container registry | **GHCR** (unchanged) | Already wired in CI. Portable across clouds. |
| CI → AWS auth | **GitHub OIDC + scoped IAM role** | No static keys, no rotation burden. |

The portability preference is captured in auto-memory `feedback-aws-portability` so future sessions don't re-litigate the RDS-vs-CNPG debate.

---

## 2. What's already built

A previous push (commits not yet tagged) laid out most of the EKS GitOps story. Concretely:

**Containers**
- `backend/Dockerfile` — multi-stage with `uv`, `python:3.12-slim-bookworm`, non-root uid 10001, `tini` PID 1. **One image runs api / workers-light / workers-heavy / beat** via `command` override in the Helm chart.
- `frontend/Dockerfile` — multi-stage `node:22-alpine` build → `nginxinc/nginx-unprivileged:1.29-alpine` runtime serving the SPA on :8080.
- `tile-server/Dockerfile` — wraps `ghcr.io/developmentseed/titiler:0.21.1` with our env defaults and a healthcheck shim.
- `infra/dev/compose.yaml` — Postgres + Redis + MinIO + MailHog + Keycloak for local dev.

**Helm charts** (`infra/helm/*`)
- `api`, `workers`, `frontend`, `tile-server`, `keycloak`, `shared` (CNPG cluster + cluster-issuer + cluster-secret-store + shared configmap).
- HPA, PDB, ServiceMonitor, ExternalSecret, Ingress, ServiceAccount templates in each app chart.

**ArgoCD** (`infra/argocd/*`)
- AppSets: `bootstrap`, `platform`, `services`, `observability`.
- Overlays: `dev`, `staging`, `production`.
- Platform values for: cert-manager, CNPG, External Secrets, GlitchTip, ingress-nginx, kube-prometheus-stack, Loki, Promtail, Tempo.

**Terraform** (`infra/terraform/*`)
- VPC, EKS (with `aws-ebs-csi-driver`, `vpc-cni`, `coredns`, `kube-proxy` add-ons; one managed node group), IAM, KMS (cluster secrets encryption), S3 (bucket stubs).

**CI**
- `.github/workflows/ci.yml` — pre-commit, backend tests, frontend tests, helm lint/template, terraform fmt/validate, **containers matrix build + push to `ghcr.io/<owner>/missionagre/{api,workers,tile-server,frontend}` tagged with the short SHA on push to `main`** (GHA cache scoped per image).
- `.github/workflows/argocd-sync.yml` — auto-opens a PR bumping `image.tag` in `infra/argocd/overlays/dev/values.yaml` after each main push.

---

## 3. Gaps blocking first cloud deploy

1. No repo-root `docker-compose.yaml` that exercises the prod-shaped containers locally.
2. No Alembic migrations Job (ArgoCD PreSync hook) — migrations still need to be run manually.
3. No `ServiceMonitor` for `workers`, `tile-server`, `frontend` — observability blind spots.
4. Terraform missing: Route 53 zone for `agripulse.cloud`, ACM cert, IRSA roles (ExternalDNS, cert-manager, External Secrets, Karpenter, CNPG backup-S3), application S3 buckets (imagery, Postgres backups per env), Secrets Manager entries, GitHub OIDC provider + role.
5. ArgoCD itself isn't bootstrapped — no `helm_release` in Terraform.
6. `argocd-sync.yml` has a known bug: only bumps a single global `image.tag`, missing the tile-server tag.
7. The CNPG `Cluster` template **has the `backup:` block but `backup.enabled` defaults aren't wired** in env overlays — needs S3 destination + IRSA role + a `ScheduledBackup` resource.
8. No Karpenter NodePool / EC2NodeClass / controller install.
9. Keycloak prod realm isn't documented; the dev overlay still references `*.missionagre.local` placeholder hostnames.
10. No cost guardrails (Budgets alarm, EBS sweeper, idle-pod Prometheus rules).

---

## 4. PR sequence (CD-1 … CD-15)

CD-0 (a no-op `infra/` refactor that splits collision-prone files so CD-1..CD-15 can be authored in parallel) is the prerequisite and must land before any other CD-N PR.

Each PR is mergeable + revertable independently. CD-1..CD-7 unblock first dev deploy. CD-8..CD-12 are the cloud-native polish. CD-13..CD-15 graduate dev → prod.

| # | Title | Net effect |
| --- | --- | --- |
| CD-1 | `chore(docs): replace ECS proposal with EKS strategy of record` | This document. Zero code. |
| CD-2 | `feat(compose): repo-root prod-shaped docker-compose for local smoke` | `docker-compose.yaml` runs the four built images against `infra/dev/compose.yaml` infra. Reproduces a deploy on your laptop. |
| CD-3 | `feat(helm): alembic migrations as a pre-sync ArgoCD Job` | Migrations Job annotated `argocd.argoproj.io/hook: PreSync`. No more manual `alembic upgrade head`. |
| CD-4 | `feat(helm): ServiceMonitors for workers, tile-server, frontend` | Closes observability blind spots. Workers expose a Celery prometheus exporter sidecar. |
| CD-5 | `feat(infra): Route 53 zone + ACM + ExternalDNS + cert-manager Issuers for agripulse.cloud` | Terraform zone + IRSA. Helm ClusterIssuer with DNS-01 solver. Outputs nameservers. |
| CD-6 | `feat(infra): S3 buckets + IRSA — imagery, Postgres backups` | Per-env buckets, lifecycle, KMS encryption. IRSA bindings for the api SA (imagery RW) and CNPG SA (backup RW). |
| CD-7 | `feat(helm): CNPG Cluster backup wiring + 30-day PITR + ScheduledBackup` | Wires the existing `backup:` template block + adds `ScheduledBackup`. Adds `docs/runbooks/postgres-restore.md`. |
| CD-8 | `feat(infra): Karpenter — controller, NodePool, EC2NodeClass` | Replaces the current `eks_managed_node_groups.default` with a minimal baseline; Karpenter scales the rest with spot priority. |
| CD-9 | `feat(infra): External Secrets + AWS Secrets Manager bootstrap` | Secrets Manager entries, IRSA, ClusterSecretStore. Existing ExternalSecret templates start resolving. |
| CD-10 | `feat(infra): ArgoCD bootstrap via Terraform + AppSets sync` | `helm_release "argocd"` + apply the 4 AppSets. UI at `argocd.agripulse.cloud`. |
| CD-11 | `feat(ci): GitHub OIDC role for Terraform apply + image push` | Replaces any static keys. New CI job `infra-tf-apply` runs `terraform apply` on main merge with environment approval. |
| CD-12 | `fix(ci): argocd-sync bumps per-image tags (incl. tile-server)` | Audit + fix `argocd-sync.yml` regex. |
| CD-13 | `feat(infra): Keycloak prod realm + HA + stable issuer URL` | `auth.agripulse.cloud`. HA mode, dedicated DB, realm JSON ConfigMap. |
| CD-14 | `feat(infra): production overlay smoke + first-prod-deploy runbook` | Finalise `infra/argocd/overlays/production/values.yaml`. Manual promotion procedure. Smoke checklist. |
| CD-15 | `chore(infra): cost guardrails — budget alarm, EBS sweeper, idle-pod alerts` | AWS Budgets at $300/mo with SNS → Slack. Lambda EBS sweeper. Prometheus idle-pod rules. |

---

## 5. Default subdomain layout

All under `agripulse.cloud` (one Route 53 hosted zone). Per-env prefix for non-prod.

| Hostname | Service | Notes |
| --- | --- | --- |
| `app.agripulse.cloud` | frontend | Prod. Dev: `app.dev.agripulse.cloud`. |
| `api.agripulse.cloud` | backend api | |
| `tiles.agripulse.cloud` | tile-server | |
| `auth.agripulse.cloud` | Keycloak | Stable across envs in V1 (single realm with per-env clients). Revisit if multi-realm needed. |
| `argocd.agripulse.cloud` | ArgoCD UI | Locked to maintainer IP via ingress annotation initially. |
| `grafana.agripulse.cloud` | Grafana | SSO via Keycloak in V2. |
| `errors.agripulse.cloud` | GlitchTip | |

---

## 6. Day-zero bootstrap (one-time, manual)

1. Create AWS account, IAM admin user, set MFA, configure CloudTrail.
2. From a workstation with admin creds: `cd infra/terraform && terraform init && terraform apply` — creates VPC, EKS, KMS, S3 (imagery + backups), Route 53 zone, OIDC provider, IRSA roles, Karpenter, Secrets Manager entries.
3. Update `agripulse.cloud` nameservers at the registrar to Route 53's NS records (output by Terraform).
4. Pre-seed AWS Secrets Manager with: `BREVO_SMTP_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `SENTINEL_HUB_CLIENT_SECRET`, JWT signing key, CNPG superuser password.
5. Terraform installs ArgoCD via `helm_release` and applies the bootstrap AppSet (CD-10).
6. ArgoCD takes over from here. Every other resource (cert-manager, ExternalDNS, External Secrets, CNPG operator, kube-prometheus stack, ingress-nginx, Karpenter NodePools, the four apps, Keycloak) is GitOps-synced from this repo.
7. Verify by visiting `argocd.agripulse.cloud` → 12+ Applications all Healthy + Synced.

Expected time: ½ day if Terraform applies cleanly; 1–2 days if IAM permission boundaries surface (they always do).

---

## 7. Day-N loops

**App change**
```
push to main
  → ci.yml builds & pushes images to GHCR (~6 min)
  → argocd-sync.yml opens dev-tag-bump PR (~30 s)
  → merge PR (auto-merge optional)
  → ArgoCD detects change, runs migrations PreSync, rolls Deployments (~3 min)
total: ~10 min from push → dev live
```

**Infra change**
```
PR with infra/terraform/* changes
  → ci.yml runs terraform plan, posts as PR comment
  → reviewer merges
  → infra-apply.yml runs terraform apply with environment approval
total: 2–10 min depending on resource
```

**Promotion to staging / prod**
- Intentionally manual: human-authored PR bumping `infra/argocd/overlays/{staging,production}/values.yaml` `image.tag`.
- ArgoCD picks up on merge.

**Postgres restore**
- `kubectl apply` a CNPG `Cluster` manifest with `bootstrap.recovery.recoveryTarget.targetTime: <UTC ISO timestamp>` pointing at the S3 backup.
- Runbook: `docs/runbooks/postgres-restore.md` (added in CD-7).

**Incident triage**
- Logs: Loki via `grafana.agripulse.cloud`.
- Traces: Tempo via Grafana.
- Metrics: kube-prometheus dashboards.
- Errors: GlitchTip at `errors.agripulse.cloud`.
- Cost: AWS Budgets + Cost Explorer.

---

## 8. Open questions deferred past CD-15

- **EKS multi-AZ posture** — `me-south-1` has 3 AZs; CNPG cluster `instances: 3` would survive an AZ outage but doubles EBS cost. Decide based on actual customer SLA.
- **Multi-region DR** — out of scope. CNPG cross-region replication via Barman Cloud is possible; revisit when there's a customer with a contractual DR clause.
- **Keycloak per-tenant realm** — currently single realm with per-env clients. Multi-realm requires resolver work and is owned by the admin-portals epic, not containerization.
- **Blue/green** — ArgoCD rolling updates are sufficient for V1. Argo Rollouts when customer SLAs demand it.
- **Account split** — single account is a known weakness. Migration path: AWS Organization + Control Tower, move prod into its own account, leave dev+staging in the original. Revisit when a paying customer signs an MSA with strong isolation language.

---

## 9. Codebase-specific gotcha (carried over from the old proposal)

The EventBus subscribers in `backend/app/modules/notifications/subscribers.py` register at app startup and run **inline in the publisher's call stack**. This means:

- Subscribers fire inside whichever process publishes the event — usually a Celery worker.
- **Celery worker containers need the same SMTP env vars as the API container** — `send_email()` is called by the worker, not the API.
- Codified by sharing the same `ExternalSecret` across the `api` and `workers` charts. Verify on every PR that touches notifications.

(Originally discovered during the Brevo SMTP rollout on 2026-05-09 — the API restart picked up the change but Celery workers had to be restarted separately.)
