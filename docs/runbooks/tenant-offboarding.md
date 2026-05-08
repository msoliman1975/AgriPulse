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

### 1. Flip the tenant status

```sql
UPDATE public.tenants
   SET status = 'suspended', suspended_at = now()
 WHERE id = '<tenant-uuid>';
```

The auth middleware reads `tenants.status` per request and returns
`403 tenant-suspended` for any non-platform JWT bound to a suspended
tenant. Existing sessions fail closed within ~30s (Keycloak token TTL).

### 2. Stop scheduled work

The Beat sweeps walk `tenants WHERE status = 'active'` — suspending
auto-excludes the tenant from imagery/weather/alerts/recommendations
sweeps. No further action needed.

### 3. (Optional) Disable Keycloak users

If you want to block the OIDC layer even harder (so a renewed status
change doesn't accidentally re-enable a long-gone user):

```bash
for u in $(kcadm.sh get users -r missionagre -q "groups=tenant-<slug>" --fields username --format csv | tail -n +2); do
  kcadm.sh update "users/$u" -r missionagre -s enabled=false
done
```

Keep the group + memberships; they make re-activation a one-line
update.

### 4. Notify customer-success

Add a row in the tracker with the suspension reason + reactivation
condition. The notifications backbone won't auto-message the customer
— that's a CS choice.

### Reactivation

```sql
UPDATE public.tenants SET status = 'active', suspended_at = NULL
 WHERE id = '<tenant-uuid>';
```

Plus re-enable Keycloak users if you disabled them. Test by signing in
as one tenant member.

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

### 1. Drop the tenant schema

```sql
DROP SCHEMA tenant_<uuid> CASCADE;
```

This deletes every farm/block/alert/recommendation/observation/audit
row. There is no soft-delete fallback at the schema level — the dump
in step 0 is your only recovery path.

### 2. Cascade-delete public rows

```sql
BEGIN;

-- Farm scopes (if `tenant_memberships` references survive after schema drop,
-- the FK to farms is logical, not enforced).
DELETE FROM public.farm_scopes
 WHERE membership_id IN (
    SELECT id FROM public.tenant_memberships WHERE tenant_id = '<tenant-uuid>'
 );

DELETE FROM public.tenant_memberships WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenant_subscriptions WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenant_settings WHERE tenant_id = '<tenant-uuid>';
DELETE FROM public.tenants WHERE id = '<tenant-uuid>';

COMMIT;
```

Run this as the platform DBA, not as a normal user — there is no
RLS policy that would block a misclick from a tenant-scoped session,
but the DBA-only audit trail is what we use to reconstruct intent.

### 3. Remove S3 objects

```bash
aws s3 rm "s3://missionagre-uploads/tenants/<tenant-uuid>/" --recursive
```

The S3 lifecycle policy will eventually drop them anyway, but explicit
removal closes the GDPR clock.

### 4. Remove Keycloak users + group

Keycloak's "Delete user" cascades the role bindings:

```bash
for u in $(kcadm.sh get users -r missionagre -q "groups=tenant-<slug>" --fields id --format csv | tail -n +2); do
  kcadm.sh delete "users/$u" -r missionagre
done

kcadm.sh delete "groups/<group-id>" -r missionagre
```

Users who belong to other tenants (rare) keep their accounts; the
`for` loop only removes the group membership, not the user, when the
user has additional groups. Verify by hand for any user with mixed
memberships.

### 5. Audit the deletion

```sql
INSERT INTO public.audit_events_archive
  (occurred_at, actor_user_id, event_type, subject_kind, subject_id, details)
VALUES
  (now(), '<your-platform-admin-uuid>', 'platform.tenant_deleted', 'tenant',
   '<tenant-uuid>',
   '{"slug":"<slug>","reason":"customer-request","ticket":"..."}'::jsonb);
```

Note: per-tenant `audit_events` rows are gone with the schema. The
platform-level archive table is the only durable record.

### 6. Update the customer-success tracker

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
