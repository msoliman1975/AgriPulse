"""Cold-start platform admin bootstrap.

Per the portal-restructure design (decision Q9): on a fresh deployment
the env vars `PLATFORM_ADMIN_EMAIL` + `PLATFORM_ADMIN_FULL_NAME`
auto-seed exactly one PlatformAdmin so an operator can sign in to
/platform without running `dev_promote_platform_admin.py` by hand.

Idempotent: if `public.platform_role_assignments` already has at least
one active PlatformAdmin row, the bootstrap is a no-op. Subsequent
boots can change the env values freely; the seed never fires twice.

Failure posture: best-effort. A bootstrap failure is logged but
doesn't block app startup — operators can fix the env config and
restart, or fall back to the CLI.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import Settings
from app.modules.platform_admins.admins_service import PlatformAdminsRoleService
from app.shared.db.session import AsyncSessionLocal


async def bootstrap_platform_admin(settings: Settings) -> None:
    log = get_logger(__name__)
    email = (settings.platform_admin_email or "").strip()
    if not email:
        return  # Nothing configured; skip silently.

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        existing = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM public.platform_role_assignments
                    WHERE role = 'PlatformAdmin' AND revoked_at IS NULL
                    """
                )
            )
        ).scalar_one()
        if int(existing) > 0:
            log.info(
                "platform_admin_bootstrap_skipped",
                reason="active_platform_admin_exists",
                count=int(existing),
            )
            return

        log.info(
            "platform_admin_bootstrap_starting",
            email=email,
            full_name=settings.platform_admin_full_name,
        )
        service = PlatformAdminsRoleService(public_session=session)
        try:
            result = await service.invite_admin(
                email=email,
                full_name=settings.platform_admin_full_name,
                role="PlatformAdmin",
                actor_user_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("platform_admin_bootstrap_failed", error=str(exc))
            return
        log.info(
            "platform_admin_bootstrap_succeeded",
            user_id=str(result["user_id"]),
            keycloak_provisioning=result["keycloak_provisioning"],
        )
