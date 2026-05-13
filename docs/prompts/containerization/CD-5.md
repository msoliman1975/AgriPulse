# CD-5 â€” Route 53 zone + ACM + ExternalDNS + cert-manager Issuers for agripulse.cloud

[Shared preamble â€” see README.md]

## Goal
Set up the DNS + TLS plumbing so any Ingress with `host: app.agripulse.cloud` (or similar) gets a public DNS record and a valid Let's Encrypt cert automatically, with zero per-host manual work.

## Files to change
- `infra/terraform/route53.tf` â€” new. Hosted zone for `agripulse.cloud` + per-env subzones if needed (probably not â€” single zone with prefixed records suffices).
- `infra/terraform/acm.tf` â€” new. Wildcard cert for `*.agripulse.cloud` and `*.dev.agripulse.cloud` and `*.staging.agripulse.cloud` via DNS-01 validation against the Route 53 zone.
- `infra/terraform/iam-irsa.tf` â€” new (or add to `iam.tf`). IRSA roles for `external-dns` (Route 53 RW on the zone) and `cert-manager` (Route 53 RW for DNS-01 solver only).
- `infra/terraform/outputs.tf` â€” add `route53_nameservers` output.
- `infra/argocd/platform-values/external-dns.yaml` â€” new (or add to platform AppSet).
- `infra/argocd/appsets/platform.yaml` â€” add `external-dns` if not already present.
- `infra/helm/shared/templates/cluster-issuers.yaml` â€” confirm DNS-01 solver is wired for Let's Encrypt prod and staging issuers, referencing the cert-manager IRSA role.
- `infra/argocd/overlays/dev/values.yaml` â€” flip `ingress.host` from the `*.agripulse.local` placeholder to `<service>.dev.agripulse.cloud`. Switch issuer to `letsencrypt-staging`.
- `infra/argocd/overlays/staging/values.yaml` â€” `<service>.staging.agripulse.cloud`, `letsencrypt-staging`.
- `infra/argocd/overlays/production/values.yaml` â€” `<service>.agripulse.cloud`, `letsencrypt-prod`.

## Tasks
1. Terraform Route 53 hosted zone (data resource if already created manually, else `aws_route53_zone`).
2. ACM cert with DNS validation; output ARN for use by ingress-nginx if you want ALB termination later (not strictly needed since cert-manager handles per-Ingress certs).
3. IRSA: `external-dns` role with `route53:ChangeResourceRecordSets` scoped to the zone's hosted zone ID. `cert-manager` role with `route53:GetChange` + `ChangeResourceRecordSets` scoped to TXT records under the zone (DNS-01).
4. ExternalDNS helm values: `provider: aws`, `domainFilters: ["agripulse.cloud"]`, `policy: upsert-only` (NOT `sync` â€” sync deletes records when Ingress is removed, which is what you eventually want but not in V1), `txtOwnerId: agripulse-eks`.
5. cert-manager ClusterIssuers: `letsencrypt-staging` and `letsencrypt-prod` both use the Route 53 DNS-01 solver with the IRSA role.
6. Overlay updates: every Ingress hostname in dev/staging/prod overlays must use the agripulse.cloud-derived hostname.
7. After Terraform apply, output the four Route 53 NS records â€” the maintainer will paste them at the domain registrar manually (one-time).

## Out of scope
- Don't migrate to ALB ingress controller. Stay on ingress-nginx for V1.
- Don't set up email DNS records (SPF/DKIM/DMARC) â€” Brevo handles theirs.
- Don't configure GitHub Pages or other non-cluster DNS targets in the zone.

## Definition of done
- `terraform plan` shows additive changes only (zone, cert, IRSA roles, outputs).
- After apply + nameserver update at registrar, `dig NS agripulse.cloud` returns the AWS NS records.
- After ArgoCD syncs ExternalDNS + cert-manager + an updated app chart, a fresh `kubectl get ingress` shows a real cert and the hostname resolves publicly.
- PR description includes the manual nameserver-update step for the maintainer.
