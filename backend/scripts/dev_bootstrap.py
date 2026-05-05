"""Bootstrap a tenant + dev user + Keycloak claim mappers for local dev.

What this does end-to-end so first sign-in just works:

  1. Pull `dev@missionagre.local` from Keycloak's Admin REST API and
     read its `sub` UUID.
  2. Create a tenant via the in-process tenancy service (which also
     bootstraps the per-tenant schema + runs the tenant migrations).
  3. Insert a `public.users` row whose `id` matches the Keycloak `sub`,
     plus a tenant_membership and a TenantAdmin role assignment.
  4. Patch the Keycloak user's attributes with `tenant_id` + `tenant_role`
     so the JWT carries them.
  5. Add `oidc-usermodel-attribute-mapper` protocol mappers to the
     `missionagre-api` client so those attributes appear as JWT claims.

Re-running is idempotent — each step skips if it's already done. After
running this, restart the API so its JWKS cache is fresh, then sign in
on the SPA.

Usage (from backend/ with .venv activated):

    python -m scripts.dev_bootstrap

Environment variables read:
  KEYCLOAK_BASE_URL    default http://localhost:8080
  KEYCLOAK_REALM       default missionagre
  KEYCLOAK_ADMIN       default admin
  KEYCLOAK_PASSWORD    default admin
  DEV_USER_EMAIL       default dev@missionagre.local
  DEV_TENANT_SLUG      default dev-tenant
"""

from __future__ import annotations

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


def kc_get_user(client: httpx.Client, token: str, email: str) -> dict[str, Any]:
    resp = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users",
        params={"email": email, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    users = resp.json()
    if not users:
        raise RuntimeError(f"Keycloak user {email!r} not found")
    return dict(users[0])


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
            "multivalued": "false",
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


async def upsert_user_record(
    *,
    user_id: UUID,
    email: str,
    full_name: str,
    tenant_id: UUID,
    tenant_role: str,
) -> None:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        # public.users
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

        # tenant membership (idempotent on (user_id, tenant_id))
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

        # role assignment (idempotent on (membership_id, role))
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
            # Race; try the read path again.
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


async def main() -> None:
    print(f"Bootstrapping dev environment ({DEV_USER_EMAIL} -> {DEV_TENANT_SLUG})\n")

    # 1. Tenant first — gives us a UUID to attach to the user.
    tenant = await ensure_tenant()
    print(f"  tenant: {tenant.tenant_id}  ({tenant.schema_name})")

    # 2. Keycloak admin work — fetch the user's sub, set attributes, add mappers.
    with httpx.Client(timeout=30.0) as client:
        token = kc_admin_token(client)
        kc_enable_unmanaged_attributes(client, token)
        print("  keycloak: unmanagedAttributePolicy = ENABLED")

        user = kc_get_user(client, token, DEV_USER_EMAIL)
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
            ("tenant_id-mapper", "tenant_id", "tenant_id", "String"),
            ("tenant_role-mapper", "tenant_role", "tenant_role", "String"),
        ):
            name, user_attr, claim, jt = spec
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
            )
            print(f"  keycloak mapper added: {name}")

    # 3. Insert/refresh the DB user record + role assignment.
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

    await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nbootstrap failed: {exc}", file=sys.stderr)
        raise
