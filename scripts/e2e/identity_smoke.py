#!/usr/bin/env python3
"""Live E2E smoke test for tenant provisioning + user lifecycle.

Drives the REAL stack (api.agripulse.cloud + the live Keycloak realm) through
the full identity flow with **throwaway data that purges itself**:

    provision tenant -> verify KC group+owner -> (reset owner pw via KC admin)
    -> invite user -> resend invite -> suspend -> reactivate -> delete user
    -> request-delete + purge tenant (drops schema + KC group/users)

It is a SMOKE/E2E check, not a delivery check: invite emails go through the
real Brevo relay, so we only assert the API's `keycloak_email_sent` flag and
print it — we do NOT verify a message actually landed in an inbox (reconcile
that against the Brevo dashboard separately).

No secrets are committed. Everything sensitive comes from env vars:

    E2E_PLATFORM_USER   PlatformAdmin login (e.g. dev@agripulse.local)
    E2E_PLATFORM_PASS
    E2E_KC_ADMIN_USER   Keycloak master admin (e.g. user)
    E2E_KC_ADMIN_PASS
  optional:
    E2E_API_BASE        default https://api.agripulse.cloud/api/v1
    E2E_KC_BASE         default https://keycloak.agripulse.cloud
    E2E_REALM           default agripulse
    E2E_KC_CLIENT       default agripulse-api
    E2E_EMAIL_DOMAIN    default example.com  (throwaway invite addresses)
    E2E_KEEP            if set, skip the tenant purge (leave data for inspection)

Run:  python scripts/e2e/identity_smoke.py
Exit code 0 = all steps passed; 1 = a failure (cleanup still attempted).
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

API_BASE = os.environ.get("E2E_API_BASE", "https://api.agripulse.cloud/api/v1")
KC_BASE = os.environ.get("E2E_KC_BASE", "https://keycloak.agripulse.cloud")
REALM = os.environ.get("E2E_REALM", "agripulse")
KC_CLIENT = os.environ.get("E2E_KC_CLIENT", "agripulse-api")
EMAIL_DOMAIN = os.environ.get("E2E_EMAIL_DOMAIN", "example.com")
KEEP = bool(os.environ.get("E2E_KEEP"))


@dataclass
class Run:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        print(f"  \033[32mPASS\033[0m {msg}")
        self.passed.append(msg)

    def bad(self, msg: str) -> None:
        print(f"  \033[31mFAIL\033[0m {msg}")
        self.failed.append(msg)

    def note(self, msg: str) -> None:
        print(f"  \033[36mNOTE\033[0m {msg}")
        self.notes.append(msg)

    def check(self, cond: bool, msg: str) -> bool:
        (self.ok if cond else self.bad)(msg)
        return cond


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")


def app_token(username: str, password: str) -> str:
    """Realm user token via direct grant (the app's agripulse-api client)."""
    r = httpx.post(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": KC_CLIENT,
            "username": username,
            "password": password,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def kc_admin_token() -> str:
    """Keycloak master-realm admin token (admin-cli)."""
    r = httpx.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ["E2E_KC_ADMIN_USER"],
            "password": os.environ["E2E_KC_ADMIN_PASS"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


TENANT_ROLE = os.environ.get("E2E_TENANT_ROLE", "Viewer")


def _steps(run: Run, plat: httpx.Client, kc: httpx.Client, ctx: dict[str, Any]) -> None:
    """Run the lifecycle steps, recording into `run`. `ctx['tenant_id']` is
    set as soon as the tenant exists so cleanup can always reach it. Returns
    early (no cleanup) on a blocking failure; the caller's finally cleans up."""
    slug = ctx["slug"]
    suffix = ctx["suffix"]
    owner_email = ctx["owner_email"]
    user_email = ctx["user_email"]
    owner_pw = ctx["owner_pw"]

    # ---- 1. Provision tenant -----------------------------------------------
    print("[1] Tenant provisioning")
    r = plat.post(
        "/admin/tenants",
        json={
            "slug": slug,
            "name": f"E2E {suffix}",
            "contact_email": f"contact-{suffix}@{EMAIL_DOMAIN}",
            "owner_email": owner_email,
            "owner_full_name": "E2E Owner",
            "initial_tier": "standard",
        },
    )
    if not run.check(r.status_code == 201, f"POST /admin/tenants -> {r.status_code}"):
        run.note(f"body: {r.text[:300]}")
        return
    body = r.json()
    ctx["tenant_id"] = body["id"]
    run.check(
        body["status"] == "active", f"tenant status active (got {body['status']})"
    )
    run.check(not body["provisioning_failed"], "provisioning_failed is False")
    run.check(bool(body.get("owner_user_id")), "owner_user_id populated")

    # ---- 2. Verify owner + group in Keycloak -------------------------------
    print("[2] Keycloak group + owner")
    grp = kc.get("/groups", params={"search": f"tenant-{slug}", "exact": "true"}).json()
    run.check(
        any(g["name"] == f"tenant-{slug}" for g in grp),
        f"KC group tenant-{slug} exists",
    )
    owner = kc.get("/users", params={"email": owner_email, "exact": "true"}).json()
    run.check(len(owner) == 1, f"KC owner user exists ({owner_email})")
    owner_kc_id = owner[0]["id"] if owner else None
    if owner_kc_id:
        roles = kc.get(f"/users/{owner_kc_id}/role-mappings/realm").json()
        run.check(
            any(x["name"] == "TenantOwner" for x in roles),
            "owner has TenantOwner realm role",
        )

    # ---- 3. retry-provisioning is rejected on an active tenant -------------
    print("[3] retry-provisioning guard")
    rr = plat.post(f"/admin/tenants/{ctx['tenant_id']}/retry-provisioning")
    run.check(
        rr.status_code == 409, f"retry on active tenant -> 409 (got {rr.status_code})"
    )

    # ---- 4. Make the owner usable, get a tenant token ----------------------
    print("[4] Bootstrap owner login (KC admin reset)")
    if not owner_kc_id:
        run.bad("no owner KC id — cannot continue user-lifecycle steps")
        return
    kc.put(
        f"/users/{owner_kc_id}",
        json={"enabled": True, "emailVerified": True, "requiredActions": []},
    )
    kc.put(
        f"/users/{owner_kc_id}/reset-password",
        json={"type": "password", "value": owner_pw, "temporary": False},
    )
    time.sleep(1)
    owner_client = httpx.Client(base_url=API_BASE, timeout=60)
    owner_client.headers["Authorization"] = f"Bearer {app_token(owner_email, owner_pw)}"
    run.ok("owner can obtain a tenant-scoped token")

    # ---- 5. Invite a user --------------------------------------------------
    print(f"[5] Invite user (role={TENANT_ROLE})")
    iv = owner_client.post(
        "/users:invite",
        json={"email": user_email, "full_name": "E2E User", "tenant_role": TENANT_ROLE},
    )
    if not run.check(
        iv.status_code in (200, 201), f"POST /users:invite -> {iv.status_code}"
    ):
        run.note(f"body: {iv.text[:300]}")
        owner_client.close()
        return
    ivb = iv.json()
    user_id = ivb["user_id"]
    run.check(
        ivb["keycloak_provisioning"] == "succeeded", "invite provisioning succeeded"
    )
    run.note(
        f"keycloak_email_sent={ivb['keycloak_email_sent']} "
        f"temporary_password={'<set>' if ivb.get('temporary_password') else None} "
        "(email delivery NOT verified — check Brevo logs)"
    )
    listed = owner_client.get("/users").json()
    run.check(any(u["id"] == user_id for u in listed), "invited user appears in /users")

    # ---- 6. Resend invite --------------------------------------------------
    print("[6] Resend invite")
    rs = owner_client.post(f"/users/{user_id}:resend-invite")
    run.check(rs.status_code in (200, 201), f"resend-invite -> {rs.status_code}")
    if rs.status_code in (200, 201):
        run.note(f"resend keycloak_email_sent={rs.json()['keycloak_email_sent']}")

    # ---- 7. Suspend + verify KC enabled=false ------------------------------
    print("[7] Suspend")
    sp = owner_client.post(f"/users/{user_id}:suspend")
    run.check(sp.status_code in (200, 204), f"suspend -> {sp.status_code}")
    u_kc = kc.get("/users", params={"email": user_email, "exact": "true"}).json()
    if u_kc:
        run.check(u_kc[0]["enabled"] is False, "KC user enabled=false after suspend")

    # ---- 8. Reactivate + verify KC enabled=true ----------------------------
    print("[8] Reactivate")
    ra = owner_client.post(f"/users/{user_id}:reactivate")
    run.check(ra.status_code in (200, 204), f"reactivate -> {ra.status_code}")
    u_kc = kc.get("/users", params={"email": user_email, "exact": "true"}).json()
    if u_kc:
        run.check(u_kc[0]["enabled"] is True, "KC user enabled=true after reactivate")

    # ---- 9. Delete user + verify removal -----------------------------------
    print("[9] Delete user")
    dl = owner_client.delete(f"/users/{user_id}")
    run.check(dl.status_code in (200, 204), f"delete -> {dl.status_code}")
    listed = owner_client.get("/users").json()
    run.check(
        not any(u["id"] == user_id for u in listed), "deleted user gone from /users"
    )
    u_kc = kc.get("/users", params={"email": user_email, "exact": "true"}).json()
    run.check(len(u_kc) == 0, "KC user removed after delete (single-tenant)")
    run.note(
        "Soft-delete leaves tenant_role_assignments/farm_scopes rows in the DB "
        "(known gap — verify via SQL; deferred per scope)."
    )
    owner_client.close()


def main() -> int:
    _require_env(
        "E2E_PLATFORM_USER",
        "E2E_PLATFORM_PASS",
        "E2E_KC_ADMIN_USER",
        "E2E_KC_ADMIN_PASS",
    )
    run = Run()
    suffix = secrets.token_hex(3)
    ctx: dict[str, Any] = {
        "suffix": suffix,
        "slug": f"e2e-{suffix}",
        "owner_email": f"e2e-owner-{suffix}@{EMAIL_DOMAIN}",
        "user_email": f"e2e-user-{suffix}@{EMAIL_DOMAIN}",
        "owner_pw": "E2e!" + secrets.token_urlsafe(12),
        "tenant_id": None,
    }
    print(f"\n=== Identity E2E smoke — slug={ctx['slug']} ===")
    print(f"API={API_BASE}  KC={KC_BASE}  realm={REALM}\n")

    plat = httpx.Client(base_url=API_BASE, timeout=60)
    plat.headers["Authorization"] = (
        f"Bearer {app_token(os.environ['E2E_PLATFORM_USER'], os.environ['E2E_PLATFORM_PASS'])}"
    )
    kc = httpx.Client(base_url=f"{KC_BASE}/admin/realms/{REALM}", timeout=60)
    kc.headers["Authorization"] = f"Bearer {kc_admin_token()}"

    try:
        _steps(run, plat, kc, ctx)
    except Exception as exc:  # noqa: BLE001 - surface as a failure, still clean up
        run.bad(f"unhandled error in steps: {exc}")
    return _finish(run, plat, ctx["tenant_id"], ctx["slug"], kc)


def _finish(
    run: Run,
    plat: httpx.Client | None = None,
    tenant_id: str | None = None,
    slug: str | None = None,
    kc: httpx.Client | None = None,
) -> int:
    if plat and tenant_id and slug and not KEEP:
        print("[cleanup] request-delete + purge tenant")
        try:
            plat.post(
                f"/admin/tenants/{tenant_id}/delete", json={"reason": "e2e cleanup"}
            )
            pr = plat.post(
                f"/admin/tenants/{tenant_id}/purge",
                json={"slug_confirmation": slug, "force": True},
            )
            run.check(pr.status_code in (200, 204), f"purge tenant -> {pr.status_code}")
            gone = plat.get(f"/admin/tenants/{tenant_id}")
            run.check(
                gone.status_code == 404,
                "tenant 404 after purge (schema + rows dropped)",
            )
            if kc:
                grp = kc.get(
                    "/groups", params={"search": f"tenant-{slug}", "exact": "true"}
                ).json()
                run.check(
                    not any(g["name"] == f"tenant-{slug}" for g in grp),
                    "KC group removed after purge",
                )
        except Exception as exc:  # noqa: BLE001 - cleanup best-effort
            run.bad(f"cleanup error: {exc}")
    elif KEEP and tenant_id:
        run.note(f"E2E_KEEP set — left tenant {slug} ({tenant_id}) for inspection")

    print("\n=== Summary ===")
    print(
        f"  passed: {len(run.passed)}   failed: {len(run.failed)}   notes: {len(run.notes)}"
    )
    for n in run.notes:
        print(f"   - note: {n}")
    if run.failed:
        for f in run.failed:
            print(f"   - FAIL: {f}")
        return 1
    print("  ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
