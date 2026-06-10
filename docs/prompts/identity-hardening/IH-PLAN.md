# Identity Hardening — Implementation Prompt (IH-1 … IH-7)

> **Goal:** make tenant/user/role provisioning **seed- and API-driven**, remove the SMTP single-point-of-failure, kill the shipped `dev/dev` prod credential, and take the Keycloak admin console out of the day-to-day operating loop. Close gaps **G1–G11** documented in `docs/reference/identity-tenancy-roles-e2e.html`.

> **STATUS (2026-06-09, branch `feat/identity-hardening`):** IH-2 `03d2409`, IH-1 `d1d99c7`, IH-3 `4b42a94`, IH-4 `fb7a156`, IH-5 `d87bdf4`, IH-6 `3702594` — **shipped & verified** (435 backend unit tests green, mypy/ruff clean, frontend tsc/eslint clean, helm templates render). Gaps closed: G1, G2, G3, G4, G5, G6, G11. **IH-7 deferred** to a follow-up gated on a live Keycloak + Playwright e2e pass (auth-core change). G9/G10 out of scope (see below).

You are working in the **AgriPulse** monorepo (FastAPI backend + React/Vite frontend + Helm/ArgoCD infra, Keycloak 26 for auth, CNPG Postgres). This prompt is self-contained — read the referenced files before editing; do not assume anything not stated here.

---

## 0. Orient first (do this before any code)

Read these to ground yourself. Do **not** skip — the KC26 gotchas below will bite otherwise.

| Area | Path |
|---|---|
| The full E2E reference + gap list | `docs/reference/identity-tenancy-roles-e2e.html` |
| Keycloak admin client (the wrapper you'll change) | `backend/app/shared/keycloak/client.py` |
| Test fake for the above | `backend/app/shared/keycloak/fakes.py` |
| Realm definition (the seed file) | `infra/helm/keycloak/files/agripulse-realm.json` |
| Dev realm (must stay dev-only) | `infra/dev/keycloak/agripulse-realm.json` |
| Promote/bootstrap scripts | `infra/helm/keycloak/files/promote-scripts/*.py` |
| Promote Job template | `infra/helm/keycloak/templates/promote-bootstrap-job.yaml` |
| Tenant creation service | `backend/app/modules/tenancy/service.py` |
| User invite service | `backend/app/modules/iam/users_service.py` + `iam/router.py` + `iam/schemas.py` |
| Platform-admin bootstrap | `backend/app/modules/platform_admins/bootstrap.py` |
| Dev bootstrap (tenant+owner seed logic to promote) | `backend/scripts/dev_bootstrap.py` |
| Settings (flags to flip) | `backend/app/core/settings.py` |
| Users UI (invite/resend actions) | `frontend/src/modules/config/pages/UsersConfigPage.tsx` + `frontend/src/api/users.ts` |
| Helm values (where prod flags live) | `infra/helm/*/values*.yaml`, ArgoCD overlays |

### KC26 invariants — never violate these
1. **`PUT /users/{id}` is a full replace.** For an existing user, always GET → merge attributes → PUT. For a *new* user, set attributes **inline in the POST body**. (Already done in `client.py`; preserve it.)
2. **`unmanagedAttributePolicy` must be ENABLED** on the realm or custom attributes (`tenant_id`, `tenant_role`, `platform_role`, `farm_scopes`) are silently stripped.
3. **Realm import is first-boot only**, and re-import drops `smtpServer`, roles, and client mappers — which is why the promote scripts re-assert them. Anything you add to the realm JSON that must survive re-import also needs a promote-script fallback.
4. **`.local` emails** trip KC26's user-profile email validator — the seed user is `emailVerified: true` for this reason. Keep that.
5. **No `testSMTPConnection`** — it's broken in KC26; don't call it.

### Hard guardrails
- **Do not break the dev login.** `dev@agripulse.local / dev` must keep working in the **dev** profile only.
- Every change must be **idempotent** (promote scripts, seed jobs, migrations re-runnable).
- CI must stay green: backend lint/format/type (#209), integration (#210). Use `FakeKeycloakClient` for tenant/user tests — extend it, don't bypass it.
- Each IH-N below is a **separate commit/PR** with its own tests. Land them in order.

---

## The plan — 7 PRs

Severity legend from the gap doc: **HIGH** = blocks/risks prod, **MED** = friction/drift, **LOW** = polish.

---

### IH-1 — Environment-gate seed users; kill `dev/dev` in prod  *(fixes G1, partially G4)* — **HIGH**

**Problem.** `infra/helm/keycloak/files/agripulse-realm.json` ships `dev@agripulse.local / dev` (non-temporary, enabled, email-verified) and is the realm used for **all** clusters. A known git credential becomes a live prod login; `bruteForceProtected:false` compounds it.

**Do:**
1. Make the helm realm file (`infra/helm/keycloak/files/agripulse-realm.json`) **not** contain the `dev/dev` user. The dev user stays only in `infra/dev/keycloak/agripulse-realm.json`.
2. For helm/prod, seed a **bootstrap platform admin** from a Secret/ExternalSecret instead — username + a **temporary** password (`"credentials":[{"type":"password","value":"<from-secret>","temporary":true}]`), forcing `UPDATE_PASSWORD` at first login. No SMTP required. Wire the secret value via the existing ExternalSecret → realm-import mechanism (templatize the realm configmap, or have the promote script create/patch the user from env — prefer the promote-script path since import is first-boot-only).
3. Set `bruteForceProtected: true` for the non-dev realm.
4. The promote script (`promote-kc-admin.py`) should set `platform_role=PlatformAdmin` on whichever bootstrap user exists (dev user in dev, the secret-seeded admin in prod) — make the email it targets an env var, defaulting to the dev user.

**Accept:** A fresh helm install has **no** hard-coded password in git; the seeded prod admin must reset on first login; dev still logs in with `dev/dev`. Brute-force protection on outside dev.

---

### IH-2 — SMTP-independent invite fallback (copy-link + resend)  *(fixes G2)* — **HIGH**

**Problem.** Every invited user is created password-less and depends entirely on `execute-actions-email`. If Brevo is down/mis-keyed, the invite "succeeds" but the user can never log in, and there is no recovery in the UI.

**Do (backend):**
1. In `backend/app/shared/keycloak/client.py`, add a method to **generate a reset action token / link** without relying on email delivery — use the Keycloak admin API to either (a) set a temporary password and return it, or (b) create an `execute-actions` link. Prefer returning a one-time **invite link** (KC `execute-actions-email` supports `lifespan` + can be turned into a link; if not feasible on KC26, set a temporary password and return it once).
2. `invite_user()` / `invite_platform_admin()` in `users_service.py` / `admins_service.py`: keep the email attempt as best-effort, but **always** capture the fallback artifact and return it in the API response (link or temp password). Never let email failure fail the invite (already true — keep it).
3. Add `POST /v1/users/{id}:resend-invite` (capability `user.invite`) that regenerates the link / re-sends the email.

**Do (frontend):**
4. In `UsersConfigPage.tsx` + `frontend/src/api/users.ts`: on successful invite, show a **"Copy invite link"** affordance and surface whether email was sent. Add a **"Resend"** row action. Keep it i18n + RTL clean (en + ar).

**Accept:** With SMTP disabled, an admin can still onboard a user end-to-end via a copied link. Resend works. No regression to the email path when SMTP is up.

---

### IH-3 — Provisioning on by default + fail-loud  *(fixes G3)* — **HIGH**

**Problem.** `keycloak_provisioning_enabled = False` default (`settings.py:69`) wires `NoopKeycloakClient`: tenant creates silently land in `pending_provision`, nothing is provisioned. Easy to deploy "successfully" and provision nothing.

**Do:**
1. Set `keycloak_provisioning_enabled: True` in the **helm/prod** values (the tenancy client secret is already set by the promote job). Keep it overridable; dev can stay as-is or also enable.
2. Add a **startup readiness assertion**: if a **non-dev** profile resolves the `NoopKeycloakClient` (provisioning disabled or secret missing), emit a prominent `WARNING`/`ERROR` log line at boot (and surface it on the integration-health page if cheap). Do **not** crash — log loudly.
3. Document the flag + its secret dependency inline in `settings.py` and the keycloak runbook.

**Accept:** Fresh prod deploy provisions KC users/groups on tenant create (status `active`, not `pending_provision`). A misconfigured cluster logs an obvious warning rather than silently no-op'ing.

---

### IH-4 — Seed realm roles; stop lazy auto-create  *(fixes G5)* — **MED**

**Problem.** Realm roles (TenantOwner, TenantAdmin, BillingAdmin, Viewer, PlatformAdmin, PlatformSupport) are created lazily on first assignment (`_assign_realm_role` in `client.py`). A freshly imported realm has an empty role list, and a mistyped role name silently invents a new role.

**Do:**
1. Add a `roles.realm[]` block to **both** realm JSONs listing the platform + tenant roles. (Remember: re-import drops roles — so also have a promote-script step that ensures they exist, idempotently.)
2. Change `_assign_realm_role()` to **look up only** and raise a clear error if the role is missing (no auto-create). Keep idempotent assignment.
3. Update `FakeKeycloakClient` to pre-register the same role set so tests match real behavior, and add a test asserting an unknown role name now **fails** instead of being created.

**Accept:** Imported realm shows all app roles in the KC console; assigning a typo'd role raises, not creates.

---

### IH-5 — Production tenant seed job  *(fixes G4)* — **MED**

**Problem.** Day-one prod has only the bootstrap admin and zero tenants. The tenant+owner logic exists but lives in `dev_bootstrap.py` (dev only).

**Do:**
1. Promote the tenant+owner seed logic into a **guarded, idempotent seed entrypoint** (reuse the tenancy service — do **not** duplicate provisioning logic). Drive it from env/Secret: `SEED_TENANT_SLUG`, `SEED_TENANT_NAME`, `SEED_OWNER_EMAIL`, `SEED_OWNER_FULL_NAME`. No-op if the slug already exists or the vars are empty.
2. Run it as an ArgoCD PostSync Job (same pattern as the promote job — reuse the api image) **after** the platform-admin bootstrap.
3. The seeded owner uses the IH-2 fallback (temp password / link) so it works without SMTP.

**Accept:** Setting the seed env vars brings up a new environment with one real tenant + working owner login, zero console clicks. Re-running the job is a no-op.

---

### IH-6 — DB → Keycloak reconciler  *(fixes G6, G11)* — **MED**

**Problem.** Roles live in 3 places (KC attribute, KC realm role, DB `tenant_role_assignments`) with no reconciliation. DB changes are stale in the JWT until KC is also updated + token refresh (≤15 min). DB soft-deletes don't reliably disable the KC login.

**Do:**
1. Add a reconciler (Celery beat task or idempotent management command) that treats the **DB as truth**: for each active membership/role assignment, ensure the KC user's `tenant_id`/`tenant_role` attributes and `enabled` flag match; for soft-deleted/suspended rows, disable the KC user.
2. Trigger it **post-write** on role/membership changes (cheap path) **and** on a periodic sweep (drift catch). Make every KC write go through the existing client (GET-merge-PUT for attributes).
3. Emit an audit event on any correction it makes. Log a summary count per run.

**Accept:** Flip a role in the DB → within one reconcile cycle the KC attribute matches; soft-delete a user → KC login disabled. Reconciler is idempotent and logs corrections.

---

### IH-7 — Multi-tenant claim + tenant switcher  *(fixes G7)* — **MED** *(largest; schedule last)*

**Problem.** `tenant_memberships` models a person in many tenants, but the JWT carries a single `tenant_id`/`tenant_role`. A multi-tenant user is pinned to one tenant; no switcher.

**Do:**
1. Decide the claim shape: either make `tenant_id`/`tenant_role` multivalued, **or** add a `memberships` claim (array of `{tenant_id, role}`). Prefer an explicit `memberships` claim + a single "active tenant" selector to avoid ambiguity in the search-path middleware.
2. Update the protocol mapper(s) in the realm JSON + `add-tenant-mappers.py` + the client attribute writes accordingly. Update `RequestContext` (`auth/context.py`) and the middleware to resolve the **active** tenant (header or token claim) and validate it against the membership set.
3. Frontend: tenant-switcher in the shell; re-fetch on switch. i18n + RTL.

**Accept:** A user in two tenants can switch in-app; search-path + RBAC follow the active tenant; a user cannot select a tenant they aren't a member of.

---

## Cross-cutting acceptance

- [ ] G1–G7 closed; G9/G10/G11 noted (G9 key-rotation restart + G10 RBAC-matrix UI remain out of scope — call them out in the PR description as intentionally deferred).
- [ ] Dev login `dev@agripulse.local / dev` still works in the dev profile.
- [ ] No hard-coded password in git for any non-dev artifact.
- [ ] Onboarding works **with SMTP off** (copy-link path).
- [ ] CI green: backend lint/format/type + integration; new tests use/extend `FakeKeycloakClient`.
- [ ] Promote scripts, seed jobs, migrations, reconciler all idempotent (re-runnable).
- [ ] Runbook updated: `docs/runbooks/keycloak-*.md` — new flags, seed env vars, fallback-link flow.
- [ ] Update `docs/reference/identity-tenancy-roles-e2e.html` gap table to mark closed gaps.

## Suggested commit order
`IH-2 → IH-1 → IH-3 → IH-4 → IH-5 → IH-6 → IH-7`
(IH-2 first so IH-1/IH-5's seeded admins/owners can rely on the SMTP-free fallback.)

## Out of scope (state explicitly in PRs)
- **G9** JWKS auto-reload on key rotation (still a manual `rollout restart`).
- **G10** in-app RBAC matrix / farm-scope review UI (tracked under role-admin parking).
- Any change to the `farm_scopes` model — farm-tier roles stay DB+JWT-only as designed.
