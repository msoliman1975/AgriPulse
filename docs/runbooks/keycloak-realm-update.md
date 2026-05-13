# Keycloak realm update

CD-13. How to change the production Keycloak realm in a reproducible way.
Pairs with `keycloak-reset.md` (full-realm recovery) and
`seeding-secrets.md` (admin / DB password rotation).

The realm JSON is **committed** at
`infra/helm/keycloak/files/agripulse-realm.json`. The shared chart's
`realm-configmap.yaml` template renders it into a ConfigMap; the bitnami
keycloak sub-chart mounts it at `/opt/bitnami/keycloak/data/import` and
starts with `--import-realm`.

The catch: `--import-realm` runs only on Keycloak boot. Editing the
ConfigMap on a running pod does **nothing** until the pod restarts.

## Edit the realm via JSON (preferred for additive changes)

1. Open `infra/helm/keycloak/files/agripulse-realm.json` on a feature
   branch.
2. Apply the change. Any `secret`-bearing field on a client must be a
   reference to a SM secret, not a literal â€” see "Sanitizing secrets"
   below.
3. Open a PR. Reviewer checks the diff and (for production) that the
   change has been smoke-tested on dev.
4. Merge. ArgoCD syncs the ConfigMap.
5. **Force a rolling restart** so the import runs:

   ```bash
   kubectl rollout restart statefulset/agripulse-keycloak -n agripulse
   ```

   For HA you'll briefly drop to one replica during the rollout; sessions
   stay alive because Infinispan replicates them across the surviving pod.

## Edit the realm via admin API (for interactive changes)

For one-off edits that need to land before the next deploy window:

1. `kubectl port-forward -n agripulse svc/agripulse-keycloak 8080:80`
2. Log in at `http://localhost:8080/admin` as the bootstrap admin (creds
   in SM at `agripulse/<env>/keycloak-admin-password`).
3. Make the change in the UI.
4. **Export back to JSON** and commit so the next pod restart doesn't
   roll the change back:
   ```bash
   kubectl exec -n agripulse agripulse-keycloak-0 -- \
     /opt/bitnami/keycloak/bin/kc.sh export \
     --realm agripulse --file /tmp/realm.json
   kubectl cp agripulse/agripulse-keycloak-0:/tmp/realm.json \
     infra/helm/keycloak/files/agripulse-realm.json
   ```
5. Sanitize secrets (next section), PR, merge.

## Adding a client or role

Same procedure as above. Two gotchas:

- **Clients** with a `secret` field (confidential clients) â€” set the
  field to a placeholder in the JSON; the actual secret is reset via
  the admin API after deploy and stashed in SM. Don't commit a real
  client secret.
- **Roles** can be committed verbatim. The `composites` block is
  evaluated at import; ordering inside the JSON does not matter.

## Rotating the bootstrap admin password

1. `aws secretsmanager put-secret-value --secret-id agripulse/<env>/keycloak-admin-password --secret-string '<new>'`
2. Wait `refreshInterval` (1h) or force a sync:
   ```bash
   kubectl annotate externalsecret -n agripulse agripulse-keycloak-admin \
     force-sync=$(date +%s) --overwrite
   ```
3. Rolling restart the statefulset (the bitnami chart only reads the
   admin secret on boot).

## Sanitizing secrets before commit

Strip these fields from the JSON if `kc.sh export` left them populated:

- `clients[*].secret` â€” confidential client secret. Replace with `""`
  or remove; reset via admin UI/API after deploy.
- `users` â€” never commit users. The runbook for dev seeds them via
  `keycloak-reset.md`.
- `smtpServer.password` â€” replace with `""`; SMTP creds live in SM at
  `agripulse/<env>/brevo-smtp-password` and are wired through the realm
  via a Keycloak SPI.

A quick check before pushing:

```bash
grep -E '"(secret|password)"\s*:\s*"[^"]+"' \
  infra/helm/keycloak/files/agripulse-realm.json && echo "FOUND SECRETS - DO NOT COMMIT"
```

## Recovering from a corrupted realm

If the JSON is broken and Keycloak refuses to start:

1. Scale to zero: `kubectl scale statefulset/agripulse-keycloak --replicas=0 -n agripulse`
2. Drop the `keycloak` database:
   ```bash
   kubectl exec -n agripulse agripulse-pg-1 -- \
     psql -U postgres -c 'DROP DATABASE keycloak;'
   ```
3. CNPG's `Database` CR will recreate it on the next reconcile (or
   `kubectl annotate database/agripulse-pg-keycloak cnpg.io/reconciliationLoop=now`).
4. Scale Keycloak back up. `--import-realm` re-imports from the
   ConfigMap into the empty database.

This **wipes user data** along with the realm config â€” for production
this is a last resort. Prefer `git revert` of the bad JSON commit and
let the import re-run.
