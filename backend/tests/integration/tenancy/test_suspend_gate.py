"""Suspend gate: the auth middleware blocks non-platform JWTs whose tenant
is suspended or pending_delete, while platform staff continue to pass.

The gate is implemented as a short-TTL DB read in
`app.shared.auth.tenant_status`. We exercise that helper directly here —
end-to-end JWT plumbing is covered by the wider auth test suite.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.tenant_status import (
    clear_cache,
    get_tenant_status,
    invalidate,
)

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_status_reflects_lifecycle_transitions(
    admin_session: AsyncSession,
) -> None:
    # `tenant_status.get_tenant_status` opens its own session, which only
    # sees committed data. The admin_session fixture doesn't auto-commit,
    # so we commit explicitly between transitions.
    clear_cache()
    service = get_tenant_service(admin_session)
    created = await service.create_tenant(
        slug=f"gate-{uuid4().hex[:8]}",
        name="Gate",
        contact_email="ops@gate.test",
        actor_user_id=uuid4(),
    )
    await admin_session.commit()
    assert await get_tenant_status(created.tenant_id) == "active"

    await service.suspend_tenant(created.tenant_id, actor_user_id=uuid4())
    await admin_session.commit()
    invalidate(created.tenant_id)
    assert await get_tenant_status(created.tenant_id) == "suspended"

    await service.reactivate_tenant(created.tenant_id, actor_user_id=uuid4())
    await admin_session.commit()
    invalidate(created.tenant_id)
    assert await get_tenant_status(created.tenant_id) == "active"

    await service.request_delete(created.tenant_id, actor_user_id=uuid4())
    await admin_session.commit()
    invalidate(created.tenant_id)
    assert await get_tenant_status(created.tenant_id) == "pending_delete"


@pytest.mark.asyncio
async def test_status_missing_for_purged_tenant(admin_session: AsyncSession) -> None:
    clear_cache()
    service = get_tenant_service(admin_session)
    created = await service.create_tenant(
        slug=f"purge-{uuid4().hex[:8]}",
        name="Purge",
        contact_email="ops@purge.test",
        actor_user_id=uuid4(),
    )
    await service.request_delete(created.tenant_id, actor_user_id=uuid4())
    await service.purge_tenant(
        created.tenant_id,
        slug_confirmation=created.slug,
        force=True,
        actor_user_id=uuid4(),
    )
    await admin_session.commit()

    invalidate(created.tenant_id)
    assert await get_tenant_status(created.tenant_id) == "missing"
