"""Provision the `agripulse-tenancy` Keycloak admin client for local dev.

Required by `app/shared/keycloak/client.py` so the tenancy module can
ensure_group / invite_user / etc. against the dev realm. Production uses
the same shape â€” a confidential client with `serviceAccountsEnabled=true`
and a service-account user that holds the realm-management roles.

Idempotent. Re-running:
  - reuses the existing client (no 409 errors),
  - re-prints the current secret (no rotation unless --rotate),
  - re-attaches the realm-admin role if missing.

    python -m scripts.dev_keycloak_admin_client            # provision + print
    python -m scripts.dev_keycloak_admin_client --rotate   # rotate secret

The SA user gets the composite `realm-admin` role from the
`realm-management` client. That covers every endpoint our admin client
hits (group CRUD, user CRUD, role-mapping, execute-actions-email).
Production would narrow this to `manage-users` + a couple of group
roles; for dev, realm-admin is the path of least friction.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

from scripts.dev_bootstrap import (
    KEYCLOAK_BASE_URL,
    KEYCLOAK_REALM,
    kc_admin_token,
)

CLIENT_ID = "agripulse-tenancy"
REALM_MGMT_CLIENT_ID = "realm-management"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_client_by_clientid(
    http: httpx.Client, token: str, client_id: str
) -> dict[str, Any] | None:
    resp = http.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients",
        params={"clientId": client_id},
        headers=_bearer(token),
    )
    resp.raise_for_status()
    rows = resp.json()
    return dict(rows[0]) if rows else None


def _create_admin_client(http: httpx.Client, token: str) -> str:
    body = {
        "clientId": CLIENT_ID,
        "name": "AgriPulse Tenancy Provisioning",
        "description": (
            "Service-account client used by the FastAPI backend to "
            "provision Keycloak groups + users when tenants are created."
        ),
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "protocol": "openid-connect",
    }
    resp = http.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients",
        headers=_bearer(token),
        json=body,
    )
    if resp.status_code == 409:
        existing = _get_client_by_clientid(http, token, CLIENT_ID)
        assert existing is not None
        return str(existing["id"])
    resp.raise_for_status()
    location = resp.headers.get("location") or resp.headers.get("Location")
    if not location or "/" not in location:
        again = _get_client_by_clientid(http, token, CLIENT_ID)
        if again is None:
            raise RuntimeError("client created but lookup miss")
        return str(again["id"])
    return location.rsplit("/", 1)[-1]


def _client_secret(http: httpx.Client, token: str, client_uuid: str, *, rotate: bool) -> str:
    if rotate:
        resp = http.post(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
            "/client-secret",
            headers=_bearer(token),
        )
    else:
        resp = http.get(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
            "/client-secret",
            headers=_bearer(token),
        )
    resp.raise_for_status()
    return str(resp.json()["value"])


def _service_account_user(http: httpx.Client, token: str, client_uuid: str) -> dict[str, Any]:
    resp = http.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
        "/service-account-user",
        headers=_bearer(token),
    )
    resp.raise_for_status()
    return dict(resp.json())


def _role_from_client(
    http: httpx.Client, token: str, client_uuid: str, role_name: str
) -> dict[str, Any]:
    resp = http.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
        f"/roles/{role_name}",
        headers=_bearer(token),
    )
    resp.raise_for_status()
    return dict(resp.json())


def _assigned_client_roles(
    http: httpx.Client, token: str, user_id: str, client_uuid: str
) -> set[str]:
    resp = http.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}"
        f"/role-mappings/clients/{client_uuid}",
        headers=_bearer(token),
    )
    resp.raise_for_status()
    return {r["name"] for r in resp.json()}


def _grant_client_role(
    http: httpx.Client,
    token: str,
    user_id: str,
    client_uuid: str,
    role: dict[str, Any],
) -> None:
    resp = http.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}"
        f"/role-mappings/clients/{client_uuid}",
        headers=_bearer(token),
        json=[{"id": role["id"], "name": role["name"]}],
    )
    if resp.status_code not in (204, 409):
        resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Rotate the client secret. Existing tokens become invalid.",
    )
    args = parser.parse_args()

    print(f"Provisioning Keycloak admin client {CLIENT_ID!r}")
    print(f"  realm: {KEYCLOAK_REALM} ({KEYCLOAK_BASE_URL})")

    with httpx.Client(timeout=30.0) as http:
        token = kc_admin_token(http)

        # Realm-management client UUID â€” we attach roles FROM this client TO
        # the SA user. Every realm has one; failure here = wrong realm.
        rm_client = _get_client_by_clientid(http, token, REALM_MGMT_CLIENT_ID)
        if rm_client is None:
            raise SystemExit(
                f"client {REALM_MGMT_CLIENT_ID!r} not found in realm {KEYCLOAK_REALM!r}"
            )
        rm_uuid = str(rm_client["id"])

        existing = _get_client_by_clientid(http, token, CLIENT_ID)
        if existing is None:
            client_uuid = _create_admin_client(http, token)
            print(f"  created client (uuid={client_uuid})")
        else:
            client_uuid = str(existing["id"])
            print(f"  reusing existing client (uuid={client_uuid})")

        secret = _client_secret(http, token, client_uuid, rotate=args.rotate)
        if args.rotate:
            print("  rotated client secret")

        sa_user = _service_account_user(http, token, client_uuid)
        sa_user_id = str(sa_user["id"])
        print(f"  service-account user: {sa_user['username']} ({sa_user_id})")

        realm_admin_role = _role_from_client(http, token, rm_uuid, "realm-admin")
        already = _assigned_client_roles(http, token, sa_user_id, rm_uuid)
        if "realm-admin" in already:
            print("  realm-admin role already assigned (skipped)")
        else:
            _grant_client_role(http, token, sa_user_id, rm_uuid, realm_admin_role)
            print("  granted realm-admin role to service account")

    print("\n" + "=" * 70)
    print("Set these in backend/.env (or your shell) and restart the backend:")
    print("=" * 70)
    print("KEYCLOAK_PROVISIONING_ENABLED=true")
    print(f"KEYCLOAK_BASE_URL={KEYCLOAK_BASE_URL}")
    print(f"KEYCLOAK_REALM={KEYCLOAK_REALM}")
    print(f"KEYCLOAK_ADMIN_CLIENT_ID={CLIENT_ID}")
    print(f"KEYCLOAK_ADMIN_CLIENT_SECRET={secret}")
    print("=" * 70)
    print(
        "\nThe TenantOwner role must also exist in the realm. If "
        "invite_user logs 'keycloak_role_missing', create the role:\n"
        f"  curl -X POST {KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/roles \\\n"
        '       -H "Authorization: Bearer $TOKEN" \\\n'
        "       -H 'Content-Type: application/json' \\\n"
        '       -d \'{"name":"TenantOwner"}\''
    )


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:400] if exc.response is not None else ""
        print(f"\nKeycloak request failed: {exc} body={body}", file=sys.stderr)
        raise SystemExit(2) from exc
    except Exception as exc:
        print(f"\nfailed: {exc}", file=sys.stderr)
        raise
