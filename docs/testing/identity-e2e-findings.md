# Identity E2E testing — findings & plan

**Date:** 2026-06-14 · Effort: E2E + integration + smoke testing of tenant
provisioning, user invite (send / resend / suspend), and user delete.

Driver: a self-cleaning live smoke script — `scripts/e2e/identity_smoke.py`
(throwaway tenant, real Keycloak + Brevo, purges itself). With a valid role it
runs **23/23 green** end-to-end on the live Hetzner stack.

---

## 🔴 Critical bug — default-role invites 500 (matches "some users didn't get invited")

Inviting a user with role **`Viewer`** returns **500 and the user is never
created**. `Viewer` is the **default** role: the API schema
(`UserInviteRequest.tenant_role`) and the UI dropdown
(`UsersConfigPage.tsx` → `useState("Viewer")`) both default to it.

Two independent defects compound here:

1. **DB CHECK constraint omits `Viewer`.** `migrations/public/versions/0003_iam_tables.py`:
   ```
   CheckConstraint("role IN ('TenantOwner','TenantAdmin','BillingAdmin')",
                   name="ck_tenant_role_assignments_role")
   ```
   Inserting `tenant_role_assignments.role = 'Viewer'` violates it →
   `CheckViolationError` → 500. (Keycloak's own "role Viewer missing" failure is
   *caught* → pending; it is **not** the 500. The 500 is this DB CHECK.)

2. **Realm roles incomplete.** The realm JSON ships `Viewer` + `TenantAdmin` +
   `TenantOwner` (`infra/helm/keycloak/files/agripulse-realm.json`), but the
   live (and local) realm is **missing `Viewer`** — the "realm-import-drops-roles"
   gotcha. `BillingAdmin` is offered in the UI + allowed by the CHECK but is **not
   in the realm JSON at all**, so BillingAdmin invites land `pending`.

Result per role (verified live):

| Invite role | DB CHECK | Realm role seeded | Outcome |
|---|---|---|---|
| `TenantAdmin` | ✅ | ✅ | **201 succeeded**, KC user + email_sent=true |
| `TenantOwner` | ✅ | ✅ | succeeds |
| `BillingAdmin` | ✅ | ❌ | lands `pending` (KC role missing) |
| **`Viewer` (default)** | ❌ | ❌ | **500 — no user created** |

**Why the existing tests miss it:** the integration tests use a CHECK-valid role
+ `FakeKeycloakClient` (which doesn't enforce the realm-role lookup or the DB
CHECK the prod stack does). Classic E2E-only gap.

**Recommended fix (small, high-impact):**
- Migration: extend the CHECK to include `'Viewer'` (and decide on `BillingAdmin`).
- Realm: ensure the `promote ensure-roles` step seeds all tenant roles
  (`Viewer`, `BillingAdmin`, `TenantAdmin`, `TenantOwner`) so KC assignment
  succeeds instead of degrading to `pending`.
- Add a regression test that invites with **each** role against a real DB (not a
  mock) and asserts 201 + the role lands.

---

## Email delivery (API-flags + Brevo-logs scope)

- The live realm **does** have `smtpServer` configured (Brevo relay,
  `from: admin@agripulse.tech`, auth on) — so this is **not** a "no SMTP" problem.
- Successful invites (e.g. `TenantAdmin`) return `keycloak_email_sent=true` —
  i.e. Keycloak handed the message to Brevo (HTTP 204). That is **not** proof of
  delivery.
- The "some users didn't get an email" symptom is mostly **the Viewer-500 above**
  (no user, so obviously no email). A *secondary* axis is Brevo silently dropping
  recipients when the sender domain `agripulse.tech` isn't verified or the account
  is sandbox/free-tier limited to verified recipients.
- **To close it:** check the Brevo dashboard (Transactional → logs) for the
  `keycloak_email_sent=true` invites — accepted vs blocked per recipient — and
  verify the `agripulse.tech` sender (SPF/DKIM).

---

## Delete — soft-delete leaves orphans (fix deferred per scope)

`TenantUsersService.delete_user` soft-deletes the membership only. Confirmed
behavior (live DB at head `0033`, so the FK-rekey bug is **not** live — that error
was a local pre-0028 DB artifact):

- `tenant_role_assignments` + `farm_scopes` **survive** (`revoked_at IS NULL`) —
  the soft membership delete never fires the `ON DELETE CASCADE`.
- `platform_role_assignments` is **never revoked** on a tenant-user delete.
- Keycloak user delete is **best-effort** — if KC is down the account is only
  disabled later by the reconciler, never actually deleted.

The E2E confirms the *happy* path (single-tenant delete removes the KC user and
hides the user from `/users`); the residual DB rows are the known gap. **Fix
deferred** by decision — to be addressed separately.

---

## What's verified green (live)

`provision tenant → KC group + owner + TenantOwner role → owner login →
invite (valid role) → resend → suspend (KC enabled=false) → reactivate (KC
enabled=true) → delete (KC user removed) → purge tenant (schema + KC group
gone)` — 23/23 assertions.

Run it:
```
E2E_PLATFORM_USER=dev@agripulse.local E2E_PLATFORM_PASS=… \
E2E_KC_ADMIN_USER=user E2E_KC_ADMIN_PASS=… \
E2E_TENANT_ROLE=TenantAdmin \
python scripts/e2e/identity_smoke.py
```
Set `E2E_TENANT_ROLE=Viewer` (the default) to reproduce the critical bug; set
`E2E_API_BASE=http://localhost:8000/api/v1 E2E_KC_BASE=http://localhost:8080`
(+ admin/admin, dev/dev) to run against the local dev stack.

---

## Next steps (test + document first; fixes on green-light)

- [ ] Integration regression: invite with each tenant role against a real DB →
      assert 201 + role lands (would have caught the Viewer-500).
- [ ] Integration regression: login-rekey (`upsert_from_jwt` Case 2) succeeds +
      `pg_constraint` assertion that each user-referencing FK is single + ON UPDATE
      CASCADE (guards the 0023/0028 regression).
- [ ] Document (not yet fix) the delete orphans as xfail/documented tests.
- [ ] Brevo dashboard review for the email-delivery axis.
- [ ] **Decide:** green-light the Viewer CHECK + realm-roles fix (actively breaks
      default invites in prod).
