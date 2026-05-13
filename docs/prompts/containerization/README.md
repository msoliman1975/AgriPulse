# Containerization & AWS deployment prompts (CD-1 … CD-15)

Each `CD-N.md` file is a self-contained prompt you can paste into a fresh Claude Code session. It assumes nothing about prior conversation context.

Use one per PR. They are designed to be **mergeable + revertable independently**. Order matters for dependencies (CD-6 must land before CD-7; CD-9 before CD-10; CD-11 before CD-12 makes the CI auth boundary cleaner) but you can re-order within each group.

Strategy of record: `docs/proposals/app-containerization-strategy.md`.

## Groups
- **CD-1 … CD-4** — docs + local-dev parity + observability gaps. Low risk.
- **CD-5 … CD-7** — DNS, S3, CNPG backup. Together they make a real cloud Postgres viable.
- **CD-8 … CD-10** — Karpenter, External Secrets, ArgoCD bootstrap. After CD-10 the cluster is GitOps-managed.
- **CD-11 … CD-12** — CI auth + image-bump fix. Removes static keys + closes the tile-server gap.
- **CD-13 … CD-15** — Keycloak prod hardening + production promotion runbook + cost guardrails.

## Shared preamble (already inside each prompt)
```
You are working on the MissionAgre (Agri.Pulse) repo. Strategy of record:
docs/proposals/app-containerization-strategy.md. Target platform: EKS +
ArgoCD + Helm in AWS me-south-1, single account, three K8s namespaces
(dev/staging/prod). In-cluster CNPG + Redis; S3 for objects; GHCR for
images; Brevo for SMTP; cert-manager + Let's Encrypt for TLS;
ExternalDNS + Route 53 for DNS (zone agripulse.cloud); Karpenter for
compute; self-hosted observability.

Do ONLY the work below. Stop and ask if any assumption seems wrong.
Open the PR against `main`.
```
