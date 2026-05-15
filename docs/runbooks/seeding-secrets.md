# Runbook: seeding AWS Secrets Manager values

Terraform creates the secret resource (name, KMS key, IAM scope, tags)
but never the value. This is by design: secret material does not belong
in the Terraform state file.

See `infra/terraform/secrets-manager.tf` for the resource list. The IAM
policy attached to the External Secrets controller only grants
`GetSecretValue` on `arn:aws:secretsmanager:eu-south-1:<account>:secret:agripulse/*`,
so a typo on a non-matching path will fail with `AccessDenied` rather
than `NotFound` â€” useful debug signal.

---

## 1. Initial seed (per env, per secret)

After `terraform apply` creates the placeholder secrets, paste each
value once:

```bash
ENV=prod   # or dev / staging

aws secretsmanager put-secret-value \
  --region eu-south-1 \
  --secret-id "agripulse/$ENV/brevo-smtp-password" \
  --secret-string "<paste-actual-password>"
```

Repeat for the five other purposes:

- `agripulse/$ENV/keycloak-admin-password`
- `agripulse/$ENV/keycloak-db-password`
- `agripulse/$ENV/keycloak-smtp` — see "keycloak-smtp JSON shape" below
- `agripulse/$ENV/sentinel-hub-client-secret`
- `agripulse/$ENV/jwt-signing-key`
- `agripulse/$ENV/postgres-superuser-password`

### keycloak-smtp JSON shape

`keycloak-smtp` is a single JSON document (one secret keeps rotation
atomic — partial rotations across host/user/password would otherwise
silently break the realm). The Keycloak realm-import substitutes each
property into `${env:KC_SMTP_*}` placeholders in
`infra/helm/keycloak/files/agripulse-realm.json`:

```bash
aws secretsmanager put-secret-value \
  --region eu-south-1 \
  --secret-id "agripulse/$ENV/keycloak-smtp" \
  --secret-string '{
    "host": "smtp-relay.brevo.com",
    "port": "587",
    "username": "<brevo-smtp-key-id>",
    "password": "<brevo-smtp-secret>",
    "from": "noreply@agripulse.cloud",
    "starttls": "true"
  }'
```

After all six land, ArgoCD will reconcile the ExternalSecret resources
on the next refresh interval (`refreshInterval: 1h` by default â€” bump it
temporarily during the seed if waiting).

## 2. Verify the K8s secret is populated

```bash
NS=agripulse

# The api + workers charts pull the per-purpose secrets into their main
# secret (api-agripulse-api-secrets / workers-agripulse-workers-secrets).
# Pick any one key to confirm the round-trip â€” `SMTP_PASSWORD` is the
# canonical smoke test because both charts include it.
kubectl get secret -n $NS api-agripulse-api-secrets -o yaml
kubectl get secret -n $NS api-agripulse-api-secrets \
  -o jsonpath='{.data.SMTP_PASSWORD}' | base64 -d
kubectl get secret -n $NS workers-agripulse-workers-secrets \
  -o jsonpath='{.data.SMTP_PASSWORD}' | base64 -d
```

The two values **must** match â€” workers send notification email too, so the
api and workers ExternalSecrets share the same `agripulse/<env>/brevo-smtp-password`
remoteRef (see `infra/helm/{api,workers}/values.yaml` â†’ `externalSecret.crossRefs`).
If they diverge, seeding was partial; rerun the `put-secret-value` in Â§1.

If the secret is missing, debug in this order:

1. `kubectl describe externalsecret -n $NS <name>` â€” look at `Status.Conditions`. `SecretSyncedError` with `AccessDeniedException` means IRSA isn't bound, or the secret path is outside the IAM policy scope.
2. `kubectl logs -n external-secrets deploy/external-secrets` â€” controller logs the exact SM call it made.
3. `aws secretsmanager describe-secret --secret-id <path>` from your laptop â€” confirms the secret exists and is in the right region.

## 3. Rotation

Same `put-secret-value` call with a new value:

```bash
aws secretsmanager put-secret-value \
  --region eu-south-1 \
  --secret-id "agripulse/prod/brevo-smtp-password" \
  --secret-string "<new-password>"
```

The ExternalSecret picks the new version up within `refreshInterval`.
The K8s secret gets updated, but **Pod env vars do not reload** â€”
trigger a rollout if anything reads the value at startup:

```bash
kubectl rollout restart -n $NS deploy/<deployment>
```

Stamper convention: bump the Deployment's `spec.template.metadata.annotations.checksum/secrets`
if you want the rollout to happen automatically on the next reconcile.

## 4. Audit + rotation cadence

- `keycloak-admin-password`, `postgres-superuser-password`,
  `jwt-signing-key` â€” rotate quarterly. ADR-required if extending.
- `brevo-smtp-password`, `sentinel-hub-client-secret` â€” rotate when the
  upstream provider issues new credentials.

CloudTrail logs every `GetSecretValue` call to these secrets; query
`eventName = GetSecretValue` in Athena if you suspect unauthorized
access. The IAM policy is scoped to the External Secrets controller's
IRSA role and nothing else.

## 5. Dev-environment caveat

The dev compose stack (`infra/dev/compose.yaml`) keeps reading from
`.env` â€” not SM. Only staging + prod pull from Secrets Manager. If a
dev value drifts, edit `.env`; do not seed `agripulse/dev/*` unless you
are explicitly testing the External Secrets path.
