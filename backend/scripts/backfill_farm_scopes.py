"""One-off backfill: project every user's active `public.farm_scopes` into
their Keycloak `farm_scopes` user attribute.

Needed once after the SMK-RBAC-BUG-01 fix ships, for users that were granted
farm-scoped roles *before* the write-side existed (their KC attribute is
empty, so the JWT `farm_scopes` claim is missing and they 403 on every farm
endpoint). New grants/revokes sync automatically via FarmService.

Run in-cluster (it needs DB + Keycloak access), e.g. in the api pod:

    python -m scripts.backfill_farm_scopes

Idempotent and safe to re-run. Aggregates scopes per Keycloak user (global
attribute), skipping not-yet-provisioned (`pending::`) subjects.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.logging import get_logger
from app.shared.db.session import AsyncSessionLocal
from app.shared.keycloak import get_keycloak_client

log = get_logger(__name__)


async def _run() -> int:
    kc = get_keycloak_client()
    synced = 0
    skipped = 0
    factory = AsyncSessionLocal()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT u.keycloak_subject AS kc,
                           fs.farm_id AS farm_id,
                           fs.role AS role
                    FROM public.farm_scopes fs
                    JOIN public.tenant_memberships m ON m.id = fs.membership_id
                    JOIN public.users u ON u.id = m.user_id
                    WHERE fs.revoked_at IS NULL
                      AND u.keycloak_subject IS NOT NULL
                    ORDER BY u.keycloak_subject
                    """
                )
            )
        ).all()

    by_user: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        if not r.kc or str(r.kc).startswith("pending::"):
            continue
        by_user.setdefault(str(r.kc), []).append({"farm_id": str(r.farm_id), "role": r.role})

    for kc_subject, scopes in by_user.items():
        try:
            await kc.set_farm_scopes(keycloak_user_id=kc_subject, scopes=scopes)
            synced += 1
            log.info("farm_scopes_backfilled", keycloak_user_id=kc_subject, count=len(scopes))
        except Exception as exc:  # best-effort per-user; continue the batch
            skipped += 1
            log.warning("farm_scopes_backfill_failed", keycloak_user_id=kc_subject, error=str(exc))

    log.info("farm_scopes_backfill_done", users_synced=synced, users_skipped=skipped)
    print(f"farm_scopes backfill: {synced} users synced, {skipped} skipped")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
