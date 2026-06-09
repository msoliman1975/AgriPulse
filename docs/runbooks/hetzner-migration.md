# Hetzner migration — cutover plan (v1 prod)

Status: **prep / plan**. Decided 2026-06-07 (see memory `project_deployment_footprint_hetzner_migration`). Target: leave AWS EKS for a single-node **k3s on Hetzner CPX (amd64)** + **Cloudflare R2** + a **detachable Hetzner volume** for Postgres. ~$150/mo AWS idle floor → ~$25–40/mo. HA not required (single node + restore-from-backup is acceptable for early-stage prod). Manifests stay portable (ArgoCD + Helm + CNPG), so the scale ladder back to multi-node/EKS is intact.

---

## 1. Manifest audit → VM sizing

Resource **requests** from `infra/helm/*/values.yaml`. Current dev runs HA replica counts; single-node prod drops them to 1 (no HA needed).

| Workload | Req/replica (CPU / mem) | Dev replicas | **Prod (1×)** |
|---|---|---|---|
| CNPG Postgres | 1000m / 4Gi | 2 | **1000m / 4Gi** |
| Keycloak | 250m / 1Gi | 2 | **250m / 1Gi** (drop to 1; 2 was for distributed cache) |
| Workers — heavy | 500m / 1Gi | 1 | 500m / 1Gi |
| Workers — light | 100m / 256Mi | 2 | **100m / 256Mi** |
| Workers — beat | 50m / 128Mi | 1 (singleton) | 50m / 128Mi |
| tile-server | 250m / 512Mi | 2 | **250m / 512Mi** |
| api | 100m / 256Mi | 2 | **100m / 256Mi** |
| frontend | 50m / 64Mi | 2 | **50m / 64Mi** |
| redis | 50m / 64Mi | 1 | 50m / 64Mi |
| **App subtotal (1×)** | | | **~2.4 vCPU / ~7.3 GiB** requests |

Platform infra (slimmed for one node — see §2): ArgoCD ~0.5/1Gi, Prometheus(slim) ~0.5/1.5Gi, Grafana ~0.1/256Mi, cert-manager/external-secrets/CNPG-operator ~0.3/0.5Gi, k3s system (Traefik+CoreDNS+local-path+metrics) ~0.5/1Gi → **~2 vCPU / ~4.5 GiB**.

**Total requests ≈ 4.4 vCPU / ~12 GiB.** Requests are conservative; burst headroom matters for image builds (done in CI, not on-node) and ingest spikes.

**→ VM choice: Hetzner CPX41 (8 vCPU / 16 GB / ~€27/mo)** is the sweet spot and hits the ~$30/mo target. CPX51 (16/32) if we want comfortable headroom for the first heavy tenant. **CPX, not CAX** — app images are amd64-only (`project_aws_rebuild_2026_05_16`).

**Storage:** PG data 100Gi + WAL 30Gi → one **detachable Hetzner Volume** (~150–200Gi) mounted for CNPG, so node death loses nothing. Imagery COGs + CNPG/Barman backups → **R2** (zero egress — matters for tile serving). Drop the gp3 `storageClass`; PG volume on the Hetzner volume, everything else on k3s `local-path`.

---

## 2. AWS → Hetzner component swap map

| Concern | AWS today | Hetzner target | Notes |
|---|---|---|---|
| Cluster | EKS + Karpenter | **k3s** single node | k3s bundles Traefik, ServiceLB, local-path, CoreDNS, metrics-server |
| Ingress | ingress-nginx + AWS NLB | **Traefik** (bundled) + LE | drop ingress-nginx chart + NLB |
| TLS | cert-manager + ACM | **cert-manager OR Traefik+LE** | keep cert-manager (portable) or use Traefik's built-in ACME |
| DNS | external-dns → Route53 | **Cloudflare** (manual or external-dns w/ CF provider) | move DNS to Cloudflare alongside R2 (free tile CDN). agripulse.cloud is GoDaddy→Route53 today (`project_godaddy_route53_delegation`) — re-delegate NS to Cloudflare; **lower TTL before cutover** |
| Object storage / IRSA | S3 + IRSA roles | **R2 + static creds** | net simplification — replace all IRSA wiring (`project_eks_addon_irsa`) with R2 access-key/secret in a k8s Secret/ESO |
| Block storage | EBS gp3 CSI | **Hetzner CSI / local-path** | PG on the detachable volume; rest on local-path |
| CNPG backups | Barman → S3 (inheritFromIAMRole) | **Barman → R2** | swap `barmanObjectStore` endpoint to R2 + static creds (also fixes the WAL-archive IRSA gap from `project_wal_incident`) |
| Secrets | external-secrets ← AWS SM | **plain Secrets / SOPS, or ESO w/ a different backend** | simplest: drop ESO, seed Secrets directly (or SOPS-encrypted in git) |
| Observability | kube-prometheus-stack + Loki + Promtail + **Tempo** | **slim Prometheus + Grafana**; drop Tempo; Loki optional | short retention; no tracing for v1 |
| Compute autoscale | Karpenter | **none** (fixed VM) | drop entirely |

The 4 WAL/DB follow-ups (`project_wal_incident_and_followups_2026_05_17`) **dissolve** on a fresh CNPG bring-up with R2 backup (no IRSA, correct keycloak-DB bootstrap) — fold their fixes into §3 rather than patching the dying AWS cluster.

---

## 3. Ordered bring-up (lift-and-shift)

> Steps 0–2 are scripted: `scripts/hetzner/01-provision.sh` (run locally — creates the
> CPX41 + PG volume + firewall via `hcloud`) and `scripts/hetzner/02-node-bootstrap.sh`
> (run on the box — mounts the volume, installs k3s with Traefik **off** so the existing
> ingress-nginx config is reused unchanged, points local-path at the volume, installs ArgoCD).

0. **Pre-reqs**: Hetzner project + API token + SSH key; Cloudflare account + R2 buckets (`agripulse-imagery`, `agripulse-pg-backup`) + an R2 API token; lower agripulse.cloud DNS TTL. Then `01-provision.sh`.
1. **Node**: `02-node-bootstrap.sh` (k3s + volume + ArgoCD). Decision locked: **keep ingress-nginx** (k3s Traefik disabled) so app Ingress annotations/class are unchanged — least churn, most portable.
2. **ArgoCD**: installed by the script; point at `msoliman1975/AgriPulse` (private-repo creds). New overlay `infra/argocd/overlays/hetzner/` (copy dev, strip AWS bits) — **the live-validated phase**: IRSA annotations → R2/Cloudflare static creds (api, CNPG backup, external-dns, cert-manager), `karpenter.enabled: false`, `envHost: agripulse.cloud`, CNPG `storageClass` on the volume, secrets seeded (drop or repoint ESO).
3. **CRDs + operators**: CNPG operator, cert-manager. (Drop Karpenter/EBS-CSI/external-dns appsets.)
4. **Storage classes**: ensure `local-path` default; PG `storageClass` → the Hetzner volume mount.
5. **Secrets**: seed app + keycloak + R2 secrets (drop ESO or repoint it). Keycloak DB user bootstrapped correctly this time.
6. **Postgres (CNPG)**: single instance on the volume; Barman → R2. **Migrate Keycloak at the DB level** (dump/restore its Postgres DB — NOT realm export/import, which drops smtpServer+roles+mappers per `project_keycloak26_gotchas`).
7. **Data migration**: pg_dump the AWS app DB(s) → restore into Hetzner CNPG. Imagery COGs: copy S3 → R2.
8. **App**: api / workers / tile-server / frontend / keycloak via the hetzner overlay (amd64 images already in GHCR).
9. **Ingress + TLS**: Traefik routes + LE certs for agripulse.cloud (and keycloak host).
10. **DNS cutover**: point Cloudflare records at the Hetzner IP (TTL already low).
11. **Smoke**: full login + map + plan + signals flow.

---

## 4. Cutover safety + teardown

- **Test a restore BEFORE cutover** — single node = no safety net. Validate `pg_dump → R2 → restore` round-trips, and that the detachable-volume reattach works on node replacement.
- **Rollback**: keep AWS up until Hetzner passes smoke; DNS flip back if needed (low TTL).
- **AWS teardown**: `terraform destroy`; then watch for lingering **NAT / EIP / EBS-snapshot / Route53** charges (these survive a partial destroy).

---

## 5. Open items before starting

- Confirm CPX41 vs CPX51 (headroom vs cost).
- Decide ESO-drop vs keep (R2 creds via plain Secret/SOPS is simplest for one node).
- Decide DNS: full move to Cloudflare (free tile CDN via R2) vs keep Route53 and just point A records.
- Decide observability scope for v1 (Prometheus+Grafana only? keep Loki?).
- Backend-integration migration-roundtrip fix (PR #210) should be merged first so a fresh `alembic upgrade head` + roundtrip is provably clean (relevant to the data-migration step).
