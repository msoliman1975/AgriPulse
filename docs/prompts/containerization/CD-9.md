# CD-9 — External Secrets + AWS Secrets Manager bootstrap

[Shared preamble — see README.md]

## Goal
The Helm charts already reference `ExternalSecret` resources (`infra/helm/api/templates/externalsecret.yaml`, `infra/helm/workers/templates/externalsecret.yaml`) and `infra/helm/shared/templates/cluster-secret-store.yaml` exists — but there's no actual `ClusterSecretStore` wired to AWS Secrets Manager, and the SM entries themselves don't exist. This PR closes that loop.

## Files to change
- `infra/terraform/secrets-manager.tf` — new. SM secrets (empty placeholders + lifecycle.ignore_changes on `value`) per env:
  - `agripulse/<env>/brevo-smtp-password`
  - `agripulse/<env>/keycloak-admin-password`
  - `agripulse/<env>/sentinel-hub-client-secret`
  - `agripulse/<env>/jwt-signing-key`
  - `agripulse/<env>/postgres-superuser-password`
- `infra/terraform/iam-irsa.tf` — IRSA role for the `external-secrets` ServiceAccount with `secretsmanager:GetSecretValue` scoped to `arn:aws:secretsmanager:eu-south-1:<account>:secret:agripulse/*`.
- `infra/argocd/platform-values/external-secrets.yaml` — already exists; verify `serviceAccount.annotations` references the IRSA role.
- `infra/helm/shared/templates/cluster-secret-store.yaml` — confirm it's a `ClusterSecretStore` (not namespaced) with `provider.aws.region: eu-south-1` and `auth.jwt.serviceAccountRef` pointing at `external-secrets`.
- `infra/helm/api/templates/externalsecret.yaml` — verify `secretStoreRef.name` matches the ClusterSecretStore and `data` lists each SM key.
- `infra/helm/workers/templates/externalsecret.yaml` — same; **must include the same SMTP secret** (codebase gotcha — workers send email too).
- `docs/runbooks/seeding-secrets.md` — new, ~30 lines.

## Tasks
1. Terraform: SM secrets created with `lifecycle { ignore_changes = [secret_string] }` so Terraform owns the resource but a human pastes the value via AWS Console / CLI. Outputs the ARN list.
2. IRSA scoped tightly — no `*` resource on the IAM policy.
3. ClusterSecretStore checks: one store, all three envs use it. Per-env namespacing happens via the `ExternalSecret`'s `target.name` and `dataFrom.extract.key` paths (`agripulse/dev/...` vs `agripulse/prod/...`).
4. Runbook covers:
   - Initial seed via `aws secretsmanager put-secret-value --secret-id agripulse/prod/brevo-smtp-password --secret-string "<value>"`.
   - Rotation procedure (put new value → ExternalSecret picks up within `refreshInterval: 1h` → restart pods if needed).
   - How to verify the K8s secret is populated: `kubectl get secret -n <ns> <name> -o yaml`.

## Out of scope
- Don't migrate existing dev `.env` values into SM yet — dev can keep using local `.env`. Prod and staging seed via the runbook.
- Don't add SM access to the api Deployment directly. The External Secrets controller is the only thing that touches SM; apps read the K8s secret.
- Don't rotate any existing credentials in this PR.

## Definition of done
- `terraform apply` creates all 15 secrets (5 × 3 envs) with empty placeholders.
- ClusterSecretStore is Healthy in the ArgoCD UI.
- After seeding one secret manually, `kubectl get secret -n dev brevo-smtp -o jsonpath='{.data.password}' | base64 -d` returns the value within an hour.
- Runbook reviewed.
