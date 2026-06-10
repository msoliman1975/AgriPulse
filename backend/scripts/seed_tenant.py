"""IH-5: idempotent production tenant seed.

Brings a fresh environment up with one real tenant + owner without any
Keycloak-console clicks. Reuses the tenancy service so it shares the
exact create path the API uses (schema bootstrap, Keycloak owner invite,
audit, events) — no duplicated provisioning logic.

Driven entirely by env (all optional; empty SEED_TENANT_SLUG = no-op):

  SEED_TENANT_SLUG          tenant slug (3-32 [a-z0-9-]); empty -> skip
  SEED_TENANT_NAME          display name (default: slug)
  SEED_TENANT_CONTACT_EMAIL contact email (default: owner email or
                            ops@<slug>.local)
  SEED_OWNER_EMAIL          first TenantOwner's email (default: none ->
                            owner-less tenant)
  SEED_OWNER_FULL_NAME      owner display name
  SEED_TENANT_TIER          subscription tier (default: free)

Idempotent: no-op when the slug already exists. For SMTP-free
environments (keycloak_smtp_enabled=False) it prints the owner's
one-time temporary password so an operator can hand it off — the owner
is still forced to set their own password on first login.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.tenancy.service import SlugAlreadyExistsError, get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.keycloak import KeycloakError, get_keycloak_client

log = get_logger(__name__)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


async def _tenant_exists(slug: str) -> bool:
    factory = AsyncSessionLocal()
    async with factory() as session:
        row = (
            await session.execute(text("SELECT 1 FROM public.tenants WHERE slug = :s"), {"s": slug})
        ).first()
    return row is not None


async def _print_owner_credential(owner_email: str) -> None:
    """SMTP-free hand-off: mint + print a one-time temp password for the
    seeded owner so a fresh env has a working login with zero clicks."""
    factory = AsyncSessionLocal()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT keycloak_subject FROM public.users WHERE email = :e"),
                {"e": owner_email},
            )
        ).first()
    subject = row.keycloak_subject if row is not None else None
    if not subject or subject.startswith("pending::"):
        log.warning("seed_owner_credential_unavailable", owner_email=owner_email)
        return
    try:
        cred = await get_keycloak_client().resend_invite(keycloak_user_id=subject)
    except KeycloakError as exc:
        log.warning("seed_owner_credential_failed", owner_email=owner_email, error=str(exc))
        return
    if cred.temporary_password:
        print("=" * 64)
        print(f"OWNER TEMPORARY PASSWORD for {owner_email}:")
        print(f"    {cred.temporary_password}")
        print("Forces UPDATE_PASSWORD on first login. Rotate after hand-off.")
        print("=" * 64)


async def seed() -> None:
    slug = _env("SEED_TENANT_SLUG")
    if not slug:
        print("SEED_TENANT_SLUG is empty — nothing to seed.")
        return

    owner_email = _env("SEED_OWNER_EMAIL") or None
    owner_name = _env("SEED_OWNER_FULL_NAME") or None
    name = _env("SEED_TENANT_NAME") or slug
    contact = _env("SEED_TENANT_CONTACT_EMAIL") or owner_email or f"ops@{slug}.local"
    tier = _env("SEED_TENANT_TIER") or "free"

    if await _tenant_exists(slug):
        print(f"tenant {slug!r} already exists — no-op.")
        return

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        service = get_tenant_service(session)
        try:
            result = await service.create_tenant(
                slug=slug,
                name=name,
                contact_email=contact,
                owner_email=owner_email,
                owner_full_name=owner_name,
                initial_tier=tier,
            )
        except SlugAlreadyExistsError:
            print(f"tenant {slug!r} already exists (race) — no-op.")
            return

    print(f"seeded tenant {slug!r} id={result.tenant_id} status={result.status}")
    if result.status == "pending_provision":
        log.warning("seed_tenant_pending_provision", slug=slug)
        print("  Keycloak provisioning is offline — finish via the runbook.")
        return

    if owner_email and not get_settings().keycloak_smtp_enabled:
        await _print_owner_credential(owner_email)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
