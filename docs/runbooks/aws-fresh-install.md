# AWS dev cluster — fresh-install bootstrap

This runs after `terraform apply` + ArgoCD bootstrap have brought the
cluster up and ArgoCD has synced the platform / shared / app charts
once. Everything below is now covered by the chart code — the runbook
is the recovery path if you wipe + redeploy.

What the charts do automatically:

- Shared chart provisions `agripulse-redis` (Celery broker + cache)
  and the CNPG `agripulse-pg` Cluster with `postInitSQL` that creates
  every Postgres extension we need (`postgis`, `postgis_topology`,
  `timescaledb`, `pgcrypto`, `citext`, `pgaudit`, `btree_gist`) and
  grants `agripulse` role `CREATEROLE` (pgstac needs it).
- api chart ships a PreSync hook Job that runs
  `alembic -c /app/alembic.ini -n public upgrade head` against the
  public schema before any new api ReplicaSet rolls.
- Keycloak chart's realm import seeds the `agripulse-api` client (with
  PKCE + the four claim mappers `platform_role`, `tenant_id`,
  `tenant_role`, `farm_scopes`) and the `agripulse-tenancy`
  service-account client shell.
- frontend chart bakes the OIDC + API URLs into the Vite bundle at
  build time via `frontend/.env.production`.

What still needs ONE-TIME post-install action because it depends on
runtime secrets / live KC state:

## 1. Fill secrets in `scripts/deployment-data.yaml`

The values that need real content:

- `keycloak.client_secret` — generate with `openssl rand -hex 32`.
  Becomes the `agripulse-tenancy` client secret.
- `keycloak.db_password` — generate with
  `openssl rand -base64 32`.
- `brevo.password` — the SMTP API key from the Brevo dashboard.

## 2. `terraform apply` (CloudShell)

Creates / refreshes the SM secrets (including any new ones).

## 3. `./scripts/deploy-aws.ps1 -Phase seed-secrets`

Pushes the values from `deployment-data.yaml` into SM. External Secrets
Operator syncs them into k8s Secrets within ~1 hr (or force-refresh
the ExternalSecret CRs).

## 4. Bootstrap Keycloak runtime config (one-shot)

The realm import can't carry these — KC won't expose them via JSON
import (`unmanagedAttributePolicy` lives at User Profile, not realm
attributes; `smtpServer` needs the Brevo password from SM; the
tenancy client secret must match SM, not the placeholder).

Pipe the existing helper from inside the api pod (it ships
`scripts/dev_bootstrap.py` and has cluster DNS to keycloak):

```powershell
$env:AWS_PROFILE = "agripulse"
$pod = (kubectl get pods -n agripulse `
        -l app.kubernetes.io/name=agripulse-api `
        --no-headers -o custom-columns=N:.metadata.name | Select-Object -First 1).Trim()

$tenancySecret = aws secretsmanager get-secret-value `
    --secret-id agripulse/dev/keycloak-client-secret `
    --region eu-south-1 --query SecretString --output text

$brevoPw = aws secretsmanager get-secret-value `
    --secret-id agripulse/dev/brevo-smtp-password `
    --region eu-south-1 --query SecretString --output text

# Copy the standalone helpers into the pod and run them.
Get-Content scripts/promote-kc-admin.py -Raw |
  kubectl exec -i -n agripulse $pod -- sh -c "cat > /tmp/p1.py"
Get-Content scripts/promote-kc-tenancy.py -Raw |
  kubectl exec -i -n agripulse $pod -- sh -c "cat > /tmp/p2.py"
Get-Content scripts/add-tenant-mappers.py -Raw |
  kubectl exec -i -n agripulse $pod -- sh -c "cat > /tmp/p3.py"

# p1 — unmanagedAttributePolicy + platform_role attr/mapper for dev user.
kubectl exec -n agripulse $pod -- sh -c "PYTHONPATH=/app /opt/venv/bin/python /tmp/p1.py"

# p2 — create agripulse-tenancy client (secret = SM value), grant realm-mgmt roles, set realm smtpServer.
kubectl exec -n agripulse $pod -- sh -c "
  TENANCY_CLIENT_SECRET='$tenancySecret' `
  BREVO_LOGIN='aac72b001@smtp-brevo.com' `
  BREVO_PASSWORD='$brevoPw' `
  BREVO_FROM_EMAIL='admin@agripulse.tech' `
  /opt/venv/bin/python /tmp/p2.py
"

# p3 — tenant_id, tenant_role, farm_scopes mappers on agripulse-api client
# (idempotent; safe to re-run; realm import already includes these so this
# is only needed if the import was applied before the JSON was updated).
kubectl exec -n agripulse $pod -- sh -c "PYTHONPATH=/app /opt/venv/bin/python /tmp/p3.py"
```

## 5. Fix the ingress-nginx admission webhook `caBundle`

The platform-ingress-nginx chart's admission-patch Job runs on first
install only. If the webhook config gets re-rendered (e.g. chart
version bump) the `caBundle` field goes empty and every Ingress sync
errors with `x509: certificate signed by unknown authority`. One-liner
re-fill from the controller's TLS Secret:

```powershell
$ca = kubectl get secret -n ingress-nginx platform-ingress-nginx-admission `
        -o jsonpath='{.data.ca}'
kubectl patch validatingwebhookconfiguration platform-ingress-nginx-admission `
  --type='json' `
  -p="[{`"op`":`"add`",`"path`":`"/webhooks/0/clientConfig/caBundle`",`"value`":`"$ca`"}]"
```

## 6. Backfill the seed dev user's `users.id` ↔ Keycloak subject

The api uses the JWT `sub` claim directly as `public.users.id`. The
bootstrap-on-first-boot inserts `dev@agripulse.local` with a fresh
uuid_generate_v7 — which then mismatches the KC subject UUID. Only
matters if you want `dev@agripulse.local` to be the actor on
`invited_by` columns (creating tenants, etc.).

```sql
-- pick up the KC subject UUID from the agripulse realm first
-- then realign:
DELETE FROM public.users WHERE email = 'dev@agripulse.local';
INSERT INTO public.users (id, keycloak_subject, email, email_verified, full_name, status)
VALUES ('<kc-sub-uuid>', '<kc-sub-uuid>', 'dev@agripulse.local', true, 'Dev User', 'active');
INSERT INTO public.platform_role_assignments (user_id, role)
VALUES ('<kc-sub-uuid>', 'PlatformAdmin');
```

## 7. Smoke test

```powershell
./scripts/deploy-aws.ps1 -Phase smoke
```

(Note: the smoke script has three known issues — it tests
`api.../healthz` instead of `api/.../api/health`, `auth.dev` instead
of `keycloak.dev`, and `argocd.dev` instead of `argocd.agripulse.cloud`.
These false-failures don't reflect cluster health. Open the dev URLs
in a browser to actually validate.)

## Why some of this isn't fully chart-automated

A few of these steps need credentials that have to come from SM at
runtime + reach Keycloak's admin REST endpoints — neither realm
imports nor Helm ConfigMaps can do that cleanly. A real fix is either:

- a post-install Job per chart that mounts the relevant ExternalSecret
  and runs the kcadm REST calls itself, or
- replacing realm JSON with the Keycloak Operator's
  `KeycloakRealmImport` CR (which can interpolate Secret values).

Either is significant work for a one-shot bootstrap that fires once
per fresh KC install. Documented here so it isn't forgotten.
