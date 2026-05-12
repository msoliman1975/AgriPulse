# Runbook: seeding AWS Secrets Manager values

Terraform creates the secret resource (name, KMS key, IAM scope, tags)
but never the value. This is by design: secret material does not belong
in the Terraform state file.

See `infra/terraform/secrets-manager.tf` for the resource list. The IAM
policy attached to the External Secrets controller only grants
`GetSecretValue` on `arn:aws:secretsmanager:me-south-1:<account>:secret:agripulse/*`,
so a typo on a non-matching path will fail with `AccessDenied` rather
than `NotFound` — useful debug signal.

---

## 1. Initial seed (per env, per secret)

After `terraform apply` creates the placeholder secrets, paste each
value once:

```bash
ENV=prod   # or dev / staging

aws secretsmanager put-secret-value \
  --region me-south-1 \
  --secret-id "agripulse/$ENV/brevo-smtp-password" \
  --secret-string "<paste-actual-password>"
```

Repeat for the four other purposes:

- `agripulse/$ENV/keycloak-admin-password`
- `agripulse/$ENV/sentinel-hub-client-secret`
- `agripulse/$ENV/jwt-signing-key`
- `agripulse/$ENV/postgres-superuser-password`

After all five land, ArgoCD will reconcile the ExternalSecret resources
on the next refresh interval (`refreshInterval: 1h` by default — bump it
temporarily during the seed if waiting).

## 2. Verify the K8s secret is populated

```bash
NS=missionagre
kubectl get secret -n $NS <ext-secret-target-name> -o yaml
kubectl get secret -n $NS <ext-secret-target-name> \
  -o jsonpath='{.data.password}' | base64 -d
```

If the secret is missing, debug in this order:

1. `kubectl describe externalsecret -n $NS <name>` — look at `Status.Conditions`. `SecretSyncedError` with `AccessDeniedException` means IRSA isn't bound, or the secret path is outside the IAM policy scope.
2. `kubectl logs -n external-secrets deploy/external-secrets` — controller logs the exact SM call it made.
3. `aws secretsmanager describe-secret --secret-id <path>` from your laptop — confirms the secret exists and is in the right region.

## 3. Rotation

Same `put-secret-value` call with a new value:

```bash
aws secretsmanager put-secret-value \
  --region me-south-1 \
  --secret-id "agripulse/prod/brevo-smtp-password" \
  --secret-string "<new-password>"
```

The ExternalSecret picks the new version up within `refreshInterval`.
The K8s secret gets updated, but **Pod env vars do not reload** —
trigger a rollout if anything reads the value at startup:

```bash
kubectl rollout restart -n $NS deploy/<deployment>
```

Stamper convention: bump the Deployment's `spec.template.metadata.annotations.checksum/secrets`
if you want the rollout to happen automatically on the next reconcile.

## 4. Audit + rotation cadence

- `keycloak-admin-password`, `postgres-superuser-password`,
  `jwt-signing-key` — rotate quarterly. ADR-required if extending.
- `brevo-smtp-password`, `sentinel-hub-client-secret` — rotate when the
  upstream provider issues new credentials.

CloudTrail logs every `GetSecretValue` call to these secrets; query
`eventName = GetSecretValue` in Athena if you suspect unauthorized
access. The IAM policy is scoped to the External Secrets controller's
IRSA role and nothing else.

## 5. Dev-environment caveat

The dev compose stack (`infra/dev/compose.yaml`) keeps reading from
`.env` — not SM. Only staging + prod pull from Secrets Manager. If a
dev value drifts, edit `.env`; do not seed `agripulse/dev/*` unless you
are explicitly testing the External Secrets path.
