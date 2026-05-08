# Tenant offboarding

Removing a tenant cleanly. Two paths:

- **Suspend** — keep the data, block sign-ins. Reversible. Use for
  trials that lapsed, accounts behind on billing, or customers who
  asked for a pause.
- **Delete** — irreversible (after a grace window). Use only on a
  customer's written request or after a 90-day suspended-and-silent
  policy expiry.

---

## Path A: suspend

### 1. Suspend via the admin API

```bash
curl -X POST \
  https://api.missionagre.io/api/v1/admin/tenants/<tenant-id>/suspend \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"reason": "trial expired"}'
```

The endpoint:

- flips `tenants.status='suspended'` and stamps `suspended_at`,
- writes a `platform.tenant_suspended` row to `audit_events_archive`,
- best-effort disables every Keycloak user in `tenant-<slug>`.

The auth middleware short-TTL-caches `tenants.status`, so existing
non-platform JWTs start failing closed within ~30s of the call. Beat
sweeps that walk `tenants WHERE status = 'active'` skip the tenant
automatically — no separate stop step.

### 2. Notify customer-success

Add a row in the tracker with the suspension reason + reactivation
condition. The notifications backbone does not auto-message the
customer — that's a CS choice.

### Reactivation

```bash
curl -X POST \
  https://api.missionagre.io/api/v1/admin/tenants/<tenant-id>/reactivate \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT"
```

The endpoint flips status back to `active`, clears `suspended_at`, and
re-enables Keycloak users in the group. Test by signing in as one
tenant member.

### Manual fallback (API unavailable)

```sql
UPDATE public.tenants
   SET status = 'suspended', suspended_at = now(), last_status_reason = '...'
 WHERE id = '<tenant-uuid>';
```

```bash
for u in $(kcadm.sh get users -r missionagre -q "groups=tenant-<slug>" --fields username --format csv | tail -n +2); do
  kcadm.sh update "users/$u" -r missionagre -s enabled=false
done
```

Reactivation is the inverse — flip `status` back to `'active'`, clear
`suspended_at`, re-enable each KC user.

---

## Path B: delete

### 0. Pre-conditions

- Written deletion request from a `TenantOwner` or platform legal —
  attach to the ticket.
- Suspension has been in effect for ≥ 30 days OR the request is
  explicitly "purge now".
- A backup exists (PITR + a hand-taken `pg_dump tenant_<id>` to S3
  Glacier — see `runbooks/postgres-failover.md` § "Pre-DDL snapshot"
  for the dump command).

### 1. Mark for deletion (starts the 30-day grace window)

```bash
curl -X POST \
  https://api.missionagre.io/api/v1/admin/tenants/<tenant-id>/delete \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"reason": "customer request, ticket #1234"}'
```

Flips status to `pending_delete`, stamps `deleted_at`, and writes
`platform.tenant_deletion_requested` to `audit_events_archive`. The
30-day grace window starts now; `purge_eligible_at` is on the response
body. Cancel during the window with `POST .../cancel-delete` —
rolls the tenant back to `suspended` (conservative default; reactivate
explicitly to allow logins again).

### 2. Hard-purge after the grace window

```bash
curl -X POST \
  https://api.missionagre.io/api/v1/admin/tenants/<tenant-id>/purge \
  -H "Authorization: Bearer $PLATFORM_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"slug_confirmation": "<exact-slug>"}'
```

The endpoint:

- writes `platform.tenant_purged` to `audit_events_archive` first
  (durable trail even if the DDL crashes),
- deletes the public-side rows (`tenants`, `tenant_settings`,
  `tenant_subscriptions`),
- `DROP SCHEMA tenant_<id> CASCADE`,
- best-effort deletes Keycloak users + the `tenant-<slug>` group.

Pass `"force": true` only when the urgent purge has been pre-approved
(e.g. legal request); it bypasses the grace-window check. The
`slug_confirmation` field is mandatory either way and must match the
tenant's slug exactly — guards against fat-finger purges.

### 3. Remove S3 objects

```bash
aws s3 rm "s3://missionagre-uploads/tenants/<tenant-uuid>/" --recursive
```

The S3 lifecycle policy will eventually drop them anyway, but explicit
removal closes the GDPR clock.

### Manual fallback (API unavailable)

If both the admin API and the API service are down, the original SQL +
`kcadm.sh` recipe still works:

```sql
BEGIN;
DELETE FROM public.farm_scopes
 WHERE membership_id IN (
    SELECT id FROM public.tenant_memberships WHERE tenant_id = '<tenant-uuid>'
 );
DELETE FROM public.tenant_memberships WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenant_subscriptions WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenant_settings WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenants WHERE id = '<tenant-uuid>';
DROP SCHEMA tenant_<uuid> CASCADE;
COMMIT;
```

```bash
for u in $(kcadm.sh get users -r missionagre -q "groups=tenant-<slug>" --fields id --format csv | tail -n +2); do
  kcadm.sh delete "users/$u" -r missionagre
done
kcadm.sh delete "groups/<group-id>" -r missionagre
```

Users who belong to other tenants (rare) keep their accounts; verify by
hand for any user with mixed memberships.

### 4. Audit trail

The API path writes `platform.tenant_deletion_requested` and
`platform.tenant_purged` rows to `public.audit_events_archive`
automatically. If you took the manual SQL fallback above instead,
backfill the archive yourself:

```sql
INSERT INTO public.audit_events_archive
  (occurred_at, actor_user_id, event_type, subject_kind, subject_id, details)
VALUES
  (now(), '<your-platform-admin-uuid>', 'platform.tenant_purged', 'tenant',
   '<tenant-uuid>',
   '{"slug":"<slug>","reason":"customer-request","ticket":"..."}'::jsonb);
```

Note: per-tenant `audit_events` rows are gone with the schema. The
platform-level archive table is the only durable record.

### 5. Update the customer-success tracker

Mark closed + reference the deletion-request artifact.

---

## Troubleshooting

**`DROP SCHEMA … CASCADE` errors on hypertables.** Manually drop the
hypertable chunks first:

```sql
SELECT drop_chunks(format('%I.audit_events', '<schema>')::regclass, INTERVAL '0 days');
SELECT drop_chunks(format('%I.signal_observations', '<schema>')::regclass, INTERVAL '0 days');
SELECT drop_chunks(format('%I.weather_observations', '<schema>')::regclass, INTERVAL '0 days');
SELECT drop_chunks(format('%I.weather_forecasts', '<schema>')::regclass, INTERVAL '0 days');
```

then retry the DROP.

**`DELETE FROM public.tenants` blocks on a FK.** Some join table was
missed. Find the offender:

```sql
SELECT conname, conrelid::regclass
  FROM pg_constraint
 WHERE confrelid = 'public.tenants'::regclass;
```

…then add a `DELETE FROM <table>` step above tenants. Update this
runbook so the next operator sees the table.
