# Keycloak reset

Recovery procedures for Keycloak in dev and production. Most "Keycloak
problems" are actually:
- Stale JWKS cache after a key rotation.
- A user's email/username collision blocking login.
- The realm import drifted from `infra/keycloak/realm-export.json`.

True "reset everything" is rare; the steps below isolate the cheaper
paths first.

---

## 1 — JWKS cache + JWT refresh

When users see "401 Invalid token" right after a Keycloak deploy:

```bash
# Backend caches the JWKS for `keycloak_jwks_cache_ttl_seconds`
# (default 1h). Force a refetch by restarting the API:
kubectl rollout restart -n missionagre deploy/api
```

Users then need to re-login. The frontend OIDC client refreshes tokens
on its own once the user's session cookie still validates against the
new keys.

---

## 2 — A specific user can't log in

### "Account is disabled"

```bash
kcadm.sh update users/<user-id> -r missionagre -s enabled=true
```

### "Invalid username or password" but the user swears it's right

```bash
# Reset their password to a temporary value + email link
kcadm.sh update users/<user-id>/execute-actions-email -r missionagre \
  -s '["UPDATE_PASSWORD"]'
```

### "User exists with email" on signup

A duplicate user with the same email under a different username is
blocking. Find + remove the orphan:

```bash
kcadm.sh get users -r missionagre -q "email=<email>"
# If two rows: delete the older one (check createdTimestamp).
kcadm.sh delete users/<orphan-id> -r missionagre
```

### Group/role drift (user lost their TenantAdmin)

Re-grant:

```bash
kcadm.sh add-roles -r missionagre --uusername "<email>" \
  --rolename TenantAdmin
kcadm.sh update users/<user-id>/groups/<tenant-group-id> -r missionagre
```

The platform DB row in `public.tenant_memberships` should already
exist (created on first login); if missing, see § 3 of
`runbooks/tenant-onboarding.md`.

---

## 3 — Realm export / import drift

When a Keycloak feature flag or theme change in
`infra/keycloak/realm-export.json` doesn't show up in the running
realm, you have to re-import. **This rotates the realm's signing keys
unless you carry them over** — schedule a maintenance window.

```bash
# 1. Export the live realm (so we can diff)
kcadm.sh get realms/missionagre -r master > /tmp/realm-live.json

# 2. Diff against the file in repo
diff <(jq -S . infra/keycloak/realm-export.json) <(jq -S . /tmp/realm-live.json) | head

# 3. If you want the file to win:
kc.sh import --file infra/keycloak/realm-export.json --override true

# 4. Restart Keycloak to pick up theme/SPI changes
kubectl rollout restart -n keycloak statefulset/keycloak

# 5. Restart the API so the JWKS cache repopulates from the new keys
kubectl rollout restart -n missionagre deploy/api
```

Tell users to log out + back in — refresh tokens minted against the
old keys will fail.

---

## 4 — Full reset (dev only)

In local dev, the realm lives in `infra/dev/compose.yaml`'s Keycloak
service. To wipe and rebootstrap:

```bash
docker compose -f infra/dev/compose.yaml down keycloak
docker volume rm missionagre_keycloak_h2  # the H2 db volume name
docker compose -f infra/dev/compose.yaml up -d keycloak

# Re-run the dev bootstrap to recreate the missionagre realm + dev user
python backend/scripts/dev_bootstrap.py
```

Sign back in at http://localhost:8080/admin (admin/admin) to verify.

> Never run this in staging/production. There is no full reset there
> — recovery goes through § 3 (realm re-import) or § 5 (DR).

---

## 5 — DR: Keycloak DB lost

Keycloak's storage in production is on the same CNPG cluster (separate
schema). PITR for the Keycloak schema follows the same procedure as
`runbooks/postgres-failover.md` § 5; recovery time is identical.

After PITR:

1. Restart Keycloak so it reconnects to the recovered DB.
2. Verify the admin login works (master realm is in the same backup).
3. Re-issue tokens for any users whose sessions were active during the
   restore — easiest path is "Sign out all sessions" under
   `Realm settings → Sessions`.

---

## 6 — Verifying after any reset

```bash
# JWKS endpoint responds with the live keys
curl -fsS https://keycloak.missionagre.io/realms/missionagre/protocol/openid-connect/certs | jq '.keys[].kid'

# A test user can log in (use the playwright suite if available)
playwright test tests/auth-smoke.spec.ts

# Backend accepts the resulting JWT
TOKEN=$(get-test-jwt)
curl -fsS -H "Authorization: Bearer $TOKEN" https://api.missionagre.io/api/v1/me
```

Document the change in the platform-on-call channel even for routine
resets — Keycloak is the auth root of trust, and silent fixes are how
the next operator gets surprised.
