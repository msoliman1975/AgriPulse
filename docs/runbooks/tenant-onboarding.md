# Tenant onboarding

Walk-through for spinning up a new customer tenant — from "we just signed
them" to "the first user can log in and create a farm." Covers the dev
stack and the staging/prod cluster path.

If you hit a step that's already done (e.g. their Keycloak group exists),
skip it; the steps are idempotent.

---

## 0 — What you need before starting

- Tenant slug: short URL-safe identifier, `^[a-z0-9-]{3,32}$` (e.g.
  `acme-farms`). This becomes part of the schema name and is **stable
  forever** — pick deliberately.
- Display name + legal name + tax ID (if collected).
- Initial owner: name, email, phone. The owner becomes the sole
  `TenantOwner` and can re-delegate later.
- Plan: `trial` / `growth` / `enterprise`. Determines feature flags +
  imagery quota.

---

## 1 — Create the tenant row + provision the owner in one call

Hit the platform admin endpoint with a `PlatformAdmin` JWT. Pass
`owner_email` so the same call also creates the Keycloak group, invites
the user as `TenantOwner`, and triggers the password-reset email:

```bash
curl -X POST https://api.missionagre.io/api/v1/admin/tenants \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "acme-farms",
    "name": "Acme Farms",
    "legal_name": "Acme Agribusiness LLC",
    "tax_id": "...",
    "contact_email": "billing@acme-farms.com",
    "default_locale": "en",
    "initial_tier": "standard",
    "owner_email": "owner@acme-farms.com",
    "owner_full_name": "Owner Name"
  }'
```

The endpoint:

- inserts the `public.tenants` / `tenant_settings` / `tenant_subscriptions` rows,
- creates the per-tenant schema and runs every tenant Alembic migration,
- creates the Keycloak group `tenant-<slug>` (idempotent),
- invites the owner, assigns `TenantOwner`, sends the `UPDATE_PASSWORD` email.

Two return-shape signals to check:

| Field | Meaning |
| --- | --- |
| `status: "active"` | Full success — tenant + KC provisioning landed. Hand off. |
| `status: "pending_provision"` + `provisioning_failed: true` | DB side OK, KC failed. Run § 1a. |

The Keycloak SMTP relay is the same one the notifications module uses;
in dev the email lands at MailHog (http://localhost:8025).

> **Schema name** is auto-derived as `tenant_<uuid_no_dashes>` from the
> tenant id; the slug is independent. Both are visible on the response.

### 1a — If status came back as `pending_provision`

Re-run provisioning once the underlying issue (Keycloak unreachable,
realm role missing, etc.) is resolved:

```bash
curl -X POST \
  https://api.missionagre.io/api/v1/admin/tenants/<tenant-id>/retry-provisioning \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT"
```

The retry uses the `pending_owner_email` / `pending_owner_full_name`
fields stored on the row, so no operator input is needed. On success,
status flips to `active` and those columns clear.

### 1b — `kcadm.sh` fallback (only if the API path is unavailable)

In a disaster where the admin API itself is down but Keycloak is up,
the legacy manual steps still work:

```bash
kcadm.sh create groups -r missionagre \
  -s name="tenant-acme-farms" \
  -s 'attributes={"tenant_slug":["acme-farms"]}'

kcadm.sh create users -r missionagre \
  -s username="owner@acme-farms.com" \
  -s email="owner@acme-farms.com" \
  -s firstName="..." -s lastName="..." -s enabled=true

kcadm.sh update users/<user-id>/groups/<group-id> -r missionagre
kcadm.sh add-roles -r missionagre --uusername "owner@acme-farms.com" \
  --rolename TenantOwner
kcadm.sh update users/<user-id>/execute-actions-email -r missionagre \
  -s '["UPDATE_PASSWORD"]'
```

Then once the admin API is back, hand-set `keycloak_group_id` on the
tenant row to match the group you created.

---

## 3 — Mirror the user in the platform DB

The first time the new owner logs in, the auth middleware lazy-creates
their `public.users` row. To pre-create + audit:

```sql
-- Run as the platform DBA
INSERT INTO public.users (id, keycloak_subject, email, full_name, primary_locale, status)
VALUES (gen_random_uuid(), '<keycloak-sub>', 'owner@acme-farms.com',
        '...', 'en', 'active');

INSERT INTO public.tenant_memberships (tenant_id, user_id, status)
VALUES ('<tenant-uuid>', '<user-uuid>', 'active');
```

> **Idempotency:** the auth middleware's lazy-create path catches a
> `unique_violation` and reuses the existing row. Pre-creating is purely
> for audit-log neatness.

---

## 4 — Configure tenant settings (optional, can defer)

Defaults work for most customers. Override only when explicitly asked:

```sql
UPDATE public.tenant_settings
   SET imagery_cloud_cover_max_pct = 30,                      -- override default 60
       alert_notification_channels = ARRAY['in_app','email'], -- drop webhook
       webhook_endpoint_url = NULL,
       webhook_signing_secret_kms_key = NULL
 WHERE tenant_id = '<tenant-uuid>';
```

For webhook integrations, see `runbooks/notifications.md` § "Webhook
KMS-key plumbing."

---

## 5 — Smoke-test the path

1. Owner clicks the welcome-email link → lands on Keycloak → sets password.
2. Redirect to https://app.missionagre.io/ → lands on `/me`.
3. `GET /api/v1/me` returns the right `tenant_memberships[0].role = TenantOwner`.
4. Click "New farm" → form submits → farm appears in the list.
5. (Optional) Subscribe one block to imagery; wait 15 minutes; verify a
   scene shows up. Synthetic failure modes (missing SH credentials) land
   in `imagery_jobs` with `status='failed'` and surface in the
   imagery-config page.

---

## 6 — Hand off

- Owner's password is theirs; you don't keep a copy.
- Document the tenant id + slug in the customer-success tracker.
- Note any non-default tenant_settings overrides on the customer's
  ticket so renewal-time review knows what's tuned.

---

## Troubleshooting

**"Schema already exists"** — a previous attempt failed mid-create. Run
`DROP SCHEMA tenant_<uuid> CASCADE` (after confirming no real data) and
retry the create-tenant call.

**"User can log in but `tenant_memberships` is empty"** — the Keycloak
group attribute `tenant_slug` is missing. Re-run the `create groups`
command from § 2 with the attribute.

**"Welcome email never arrives"** — check Keycloak's SMTP config under
`Realm settings → Email`; in dev the relay is MailHog. In production the
relay is in the `missionagre-smtp` ExternalSecret.
