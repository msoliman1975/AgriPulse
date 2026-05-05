"""Bootstrap a tenant + user(s) + Keycloak claim mappers for local dev.

Two run modes:

  1. **Default** — creates the dev-tenant + the seeded `dev@missionagre.local`
     as TenantAdmin. Idempotent. Run this once after `compose up`.

         python -m scripts.dev_bootstrap

  2. **Add user** — creates an additional Keycloak user and attaches it
     to the dev-tenant with a chosen tenant role and/or farm-scoped role.
     Useful for testing per-farm RBAC paths (Viewer can't refresh,
     Agronomist can't manage subscriptions, etc.).

         python -m scripts.dev_bootstrap \\
             --user-email alice@local --password alice \\
             --tenant-role Agronomist

         python -m scripts.dev_bootstrap \\
             --user-email bob@local --password bob \\
             --farm-id 019df... --farm-role Viewer

Notes
-----

There is no production admin frontend yet for user management — that
ships in a later prompt. Until then this script is the canonical
"create another user" path on the dev cluster. Production is expected
to wire SCIM / a self-serve invite flow against Keycloak; the realm's
sign-up form is disabled deliberately.

What each mode does
~~~~~~~~~~~~~~~~~~~

Default mode:

  1. Creates a tenant via the in-process tenancy service (which also
     bootstraps the per-tenant schema + runs the tenant migrations).
  2. Reads `dev@missionagre.local`'s Keycloak `sub` UUID via the Admin
     REST API.
  3. Inserts a `public.users` row matching the sub plus
     `tenant_memberships` + `tenant_role_assignments` (TenantAdmin).
  4. Flips `unmanagedAttributePolicy` to ENABLED on the realm so
     custom attributes survive Keycloak 26's user-profile filter.
  5. Sets `tenant_id` and `tenant_role` user attributes.
  6. Adds two `oidc-usermodel-attribute-mapper` protocol mappers to
     the `missionagre-api` client.

Add-user mode performs only the user-side steps (2-5) plus the new
`farm_scopes` row when `--farm-id` is provided. The realm-level config
is assumed to be in place from a prior default run.

Environment variables (all optional):

  KEYCLOAK_BASE_URL    default http://localhost:8080
  KEYCLOAK_REALM       default missionagre
  KEYCLOAK_ADMIN       default admin
  KEYCLOAK_PASSWORD    default admin
  DEV_USER_EMAIL       default dev@missionagre.local
  DEV_TENANT_SLUG      default dev-tenant
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.modules.tenancy.service import (
    SlugAlreadyExistsError,
    TenantCreatedResult,
    get_tenant_service,
)
from app.shared.db.session import AsyncSessionLocal, dispose_engine

KEYCLOAK_BASE_URL = os.getenv("KEYCLOAK_BASE_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "missionagre")
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_PASSWORD = os.getenv("KEYCLOAK_PASSWORD", "admin")
DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev@missionagre.local")
DEV_TENANT_SLUG = os.getenv("DEV_TENANT_SLUG", "dev-tenant")
CLIENT_ID = "missionagre-api"

VALID_TENANT_ROLES = {"TenantOwner", "TenantAdmin", "BillingAdmin"}
VALID_FARM_ROLES = {"FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer"}


# --- Keycloak Admin API helpers --------------------------------------------


def kc_admin_token(client: httpx.Client) -> str:
    resp = client.post(
        f"{KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": KEYCLOAK_ADMIN,
            "password": KEYCLOAK_PASSWORD,
        },
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def kc_get_user(client: httpx.Client, token: str, email: str) -> dict[str, Any] | None:
    resp = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users",
        params={"email": email, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    users = resp.json()
    return dict(users[0]) if users else None


def kc_create_user(
    client: httpx.Client,
    token: str,
    *,
    email: str,
    password: str,
    full_name: str,
) -> dict[str, Any]:
    """Create a new realm user with credentials. Returns the created user dict."""
    body = {
        "username": email,
        "email": email,
        "emailVerified": True,
        "enabled": True,
        "firstName": full_name.split()[0] if full_name else "Dev",
        "lastName": " ".join(full_name.split()[1:]) or "User",
        "credentials": [{"type": "password", "value": password, "temporary": False}],
    }
    resp = client.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    if resp.status_code not in (201, 409):
        resp.raise_for_status()
    # 409 means the user exists; fall through to fetch.
    found = kc_get_user(client, token, email)
    if found is None:  # defensive
        raise RuntimeError(f"Could not create or find Keycloak user {email!r}")
    return found


def kc_enable_unmanaged_attributes(client: httpx.Client, token: str) -> None:
    """Allow arbitrary custom attributes on users.

    Keycloak 26 ships with the new User Profile feature on by default;
    custom attributes (anything beyond username/email/firstName/lastName)
    are rejected silently unless the realm's unmanaged-attribute policy
    is set to ENABLED. We can't store `tenant_id` or `tenant_role` on
    the user without flipping this.
    """
    config_url = f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/profile"
    resp = client.get(config_url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    profile = resp.json()
    profile["unmanagedAttributePolicy"] = "ENABLED"
    put = client.put(
        config_url,
        headers={"Authorization": f"Bearer {token}"},
        json=profile,
    )
    put.raise_for_status()


def kc_set_user_attributes(
    client: httpx.Client,
    token: str,
    user_id: str,
    attrs: dict[str, list[str]],
) -> None:
    # Fetch current state, merge, PUT.
    resp = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    user = resp.json()
    user.setdefault("attributes", {})
    user["attributes"].update(attrs)
    put = client.put(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
        json=user,
    )
    put.raise_for_status()


def kc_get_client_uuid(client: httpx.Client, token: str) -> str:
    resp = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients",
        params={"clientId": CLIENT_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    clients = resp.json()
    if not clients:
        raise RuntimeError(f"Keycloak client {CLIENT_ID!r} not found")
    return str(clients[0]["id"])


def kc_existing_mappers(client: httpx.Client, token: str, client_uuid: str) -> set[str]:
    resp = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
        "/protocol-mappers/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return {m["name"] for m in resp.json()}


def kc_add_attribute_mapper(
    client: httpx.Client,
    token: str,
    client_uuid: str,
    *,
    name: str,
    user_attribute: str,
    claim_name: str,
    json_type: str = "String",
    multivalued: bool = False,
) -> None:
    body = {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": user_attribute,
            "claim.name": claim_name,
            "jsonType.label": json_type,
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
            "multivalued": "true" if multivalued else "false",
        },
    }
    resp = client.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_uuid}"
        "/protocol-mappers/models",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    if resp.status_code not in (201, 409):
        resp.raise_for_status()


# --- DB writers -------------------------------------------------------------


async def upsert_user_record(
    *,
    user_id: UUID,
    email: str,
    full_name: str,
    tenant_id: UUID,
    tenant_role: str | None,
    farm_id: UUID | None = None,
    farm_role: str | None = None,
) -> None:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        # public.users — keycloak_subject mirrors id (same UUID).
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, keycloak_subject, email, full_name)
                VALUES (:id, :sub, :email, :name)
                ON CONFLICT (id) DO UPDATE
                SET email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name
                """
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": user_id, "sub": str(user_id), "email": email, "name": full_name},
        )

        # tenant_memberships
        existing_mem = (
            await session.execute(
                text(
                    "SELECT id FROM public.tenant_memberships "
                    "WHERE user_id = :uid AND tenant_id = :tid"
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )
        ).scalar_one_or_none()

        if existing_mem is None:
            membership_id = uuid4()
            await session.execute(
                text(
                    "INSERT INTO public.tenant_memberships "
                    "(id, user_id, tenant_id, status) "
                    "VALUES (:mid, :uid, :tid, 'active')"
                ).bindparams(
                    bindparam("mid", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"mid": membership_id, "uid": user_id, "tid": tenant_id},
            )
        else:
            membership_id = UUID(str(existing_mem))

        if tenant_role is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO public.tenant_role_assignments (membership_id, role)
                    VALUES (:mid, :role)
                    ON CONFLICT DO NOTHING
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id, "role": tenant_role},
            )

        if farm_id is not None and farm_role is not None:
            existing_scope = (
                await session.execute(
                    text(
                        "SELECT id FROM public.farm_scopes "
                        "WHERE membership_id = :mid AND farm_id = :fid"
                    ).bindparams(
                        bindparam("mid", type_=PG_UUID(as_uuid=True)),
                        bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"mid": membership_id, "fid": farm_id},
                )
            ).scalar_one_or_none()
            if existing_scope is None:
                await session.execute(
                    text(
                        "INSERT INTO public.farm_scopes "
                        "(id, membership_id, farm_id, role) "
                        "VALUES (:sid, :mid, :fid, :role)"
                    ).bindparams(
                        bindparam("sid", type_=PG_UUID(as_uuid=True)),
                        bindparam("mid", type_=PG_UUID(as_uuid=True)),
                        bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    ),
                    {
                        "sid": uuid4(),
                        "mid": membership_id,
                        "fid": farm_id,
                        "role": farm_role,
                    },
                )


async def ensure_tenant() -> TenantCreatedResult:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        existing = (
            await session.execute(
                text(
                    "SELECT id, slug, name, schema_name, contact_email, "
                    "default_locale, default_unit_system, status, created_at "
                    "FROM public.tenants WHERE slug = :slug"
                ),
                {"slug": DEV_TENANT_SLUG},
            )
        ).one_or_none()
        if existing is not None:
            return TenantCreatedResult(
                tenant_id=existing.id,
                slug=existing.slug,
                name=existing.name,
                schema_name=existing.schema_name,
                contact_email=existing.contact_email,
                default_locale=existing.default_locale,
                default_unit_system=existing.default_unit_system,
                status=existing.status,
                created_at=existing.created_at,
            )

    factory2 = AsyncSessionLocal()
    async with factory2() as session, session.begin():
        service = get_tenant_service(session)
        try:
            return await service.create_tenant(
                slug=DEV_TENANT_SLUG,
                name="Dev Tenant",
                contact_email="ops@dev-tenant.local",
            )
        except SlugAlreadyExistsError:
            existing = (
                await session.execute(
                    text(
                        "SELECT id, slug, name, schema_name, contact_email, "
                        "default_locale, default_unit_system, status, created_at "
                        "FROM public.tenants WHERE slug = :slug"
                    ),
                    {"slug": DEV_TENANT_SLUG},
                )
            ).one()
            return TenantCreatedResult(
                tenant_id=existing.id,
                slug=existing.slug,
                name=existing.name,
                schema_name=existing.schema_name,
                contact_email=existing.contact_email,
                default_locale=existing.default_locale,
                default_unit_system=existing.default_unit_system,
                status=existing.status,
                created_at=existing.created_at,
            )


# --- Top-level flows --------------------------------------------------------


async def bootstrap_default() -> None:
    print(f"Bootstrapping dev environment ({DEV_USER_EMAIL} -> {DEV_TENANT_SLUG})\n")

    tenant = await ensure_tenant()
    print(f"  tenant: {tenant.tenant_id}  ({tenant.schema_name})")

    with httpx.Client(timeout=30.0) as client:
        token = kc_admin_token(client)
        kc_enable_unmanaged_attributes(client, token)
        print("  keycloak: unmanagedAttributePolicy = ENABLED")

        user = kc_get_user(client, token, DEV_USER_EMAIL)
        if user is None:
            raise RuntimeError(
                f"Keycloak user {DEV_USER_EMAIL!r} not found — re-import the realm "
                f"or run with --user-email <email> to create one."
            )
        kc_user_id = user["id"]
        user_uuid = UUID(kc_user_id)
        print(f"  keycloak sub: {kc_user_id}")

        kc_set_user_attributes(
            client,
            token,
            kc_user_id,
            {
                "tenant_id": [str(tenant.tenant_id)],
                "tenant_role": ["TenantAdmin"],
            },
        )
        print("  keycloak attributes: tenant_id, tenant_role set")

        client_uuid = kc_get_client_uuid(client, token)
        existing = kc_existing_mappers(client, token, client_uuid)
        for spec in (
            ("tenant_id-mapper", "tenant_id", "tenant_id", "String", False),
            ("tenant_role-mapper", "tenant_role", "tenant_role", "String", False),
        ):
            name, user_attr, claim, jt, mv = spec
            if name in existing:
                continue
            kc_add_attribute_mapper(
                client,
                token,
                client_uuid,
                name=name,
                user_attribute=user_attr,
                claim_name=claim,
                json_type=jt,
                multivalued=mv,
            )
            print(f"  keycloak mapper added: {name}")

    await upsert_user_record(
        user_id=user_uuid,
        email=DEV_USER_EMAIL,
        full_name="Dev User",
        tenant_id=tenant.tenant_id,
        tenant_role="TenantAdmin",
    )
    print("  db: users / tenant_memberships / tenant_role_assignments upserted")

    print(
        "\nDone. Sign out from any active SPA session, then sign in again so "
        "the new claim mappers populate the access token."
    )


async def bootstrap_extra_user(
    *,
    email: str,
    password: str,
    full_name: str,
    tenant_role: str | None,
    farm_id: UUID | None,
    farm_role: str | None,
) -> None:
    print(f"Provisioning extra user: {email}")
    if tenant_role is not None and tenant_role not in VALID_TENANT_ROLES:
        raise SystemExit(
            f"--tenant-role={tenant_role!r}; expected one of {sorted(VALID_TENANT_ROLES)}"
        )
    if farm_role is not None and farm_role not in VALID_FARM_ROLES:
        raise SystemExit(f"--farm-role={farm_role!r}; expected one of {sorted(VALID_FARM_ROLES)}")
    if farm_role is not None and farm_id is None:
        raise SystemExit("--farm-role requires --farm-id")

    # Read the dev-tenant; fail loudly if the operator hasn't run the
    # default bootstrap first (we need a tenant + the realm-level
    # config to be in place).
    tenant = await ensure_tenant()
    print(f"  tenant: {tenant.tenant_id}")

    with httpx.Client(timeout=30.0) as client:
        token = kc_admin_token(client)
        user = kc_create_user(
            client,
            token,
            email=email,
            password=password,
            full_name=full_name,
        )
        kc_user_id = user["id"]
        user_uuid = UUID(kc_user_id)
        print(f"  keycloak sub: {kc_user_id}")

        attrs: dict[str, list[str]] = {"tenant_id": [str(tenant.tenant_id)]}
        if tenant_role is not None:
            attrs["tenant_role"] = [tenant_role]
        kc_set_user_attributes(client, token, kc_user_id, attrs)
        print(f"  keycloak attributes set: {sorted(attrs)}")

    await upsert_user_record(
        user_id=user_uuid,
        email=email,
        full_name=full_name,
        tenant_id=tenant.tenant_id,
        tenant_role=tenant_role,
        farm_id=farm_id,
        farm_role=farm_role,
    )
    print("  db: users / tenant_memberships / role assignments upserted")
    print(
        f"\nDone. Sign in as {email} / {password!r} to test "
        f"(remember to fully sign out the previous user via the SPA's user menu)."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--user-email", help="Add an extra user with this email.")
    p.add_argument("--password", default="dev", help="Password for the new user (default: dev).")
    p.add_argument("--full-name", default="Test User", help="Display name for the new user.")
    p.add_argument(
        "--tenant-role",
        choices=sorted(VALID_TENANT_ROLES),
        help="Tenant-wide role for the new user.",
    )
    p.add_argument(
        "--farm-id",
        type=lambda s: UUID(s),
        help="Grant a farm-scoped role on this farm UUID.",
    )
    p.add_argument(
        "--farm-role",
        choices=sorted(VALID_FARM_ROLES),
        help="Farm-scoped role to grant on --farm-id.",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    if args.user_email is None:
        await bootstrap_default()
    else:
        await bootstrap_extra_user(
            email=args.user_email,
            password=args.password,
            full_name=args.full_name,
            tenant_role=args.tenant_role,
            farm_id=args.farm_id,
            farm_role=args.farm_role,
        )
    await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nbootstrap failed: {exc}", file=sys.stderr)
        raise
