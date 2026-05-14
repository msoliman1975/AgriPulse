"""Lifecycle tests for the tenancy service: suspend, reactivate, delete, purge.

Each test starts from a freshly created tenant (so it owns its own
schema) and walks the state machine. The audit_events_archive table is
verified at the end, since it is the durable trail that survives a
schema drop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import (
    InvalidStatusTransitionError,
    PurgeNotEligibleError,
    SlugConfirmationMismatchError,
    TenantNotFoundError,
    get_tenant_service,
)

pytestmark = [pytest.mark.integration]


def _slug(prefix: str) -> str:
    # Slug must match ^[a-z0-9-]{3,32}$ — keep the suffix short.
    return f"{prefix}-{uuid4().hex[:8]}"


async def _create(session: AsyncSession, *, slug: str | None = None):
    service = get_tenant_service(session)
    return await service.create_tenant(
        slug=slug or _slug("life"),
        name="Lifecycle Test",
        contact_email="ops@life.test",
        owner_email="owner@life.test",
        owner_full_name="Lifecycle Owner",
        actor_user_id=uuid4(),
    )


async def _archive_count(session: AsyncSession, *, event_type: str, tenant_id) -> int:
    return (
        await session.execute(
            text(
                "SELECT count(*) FROM public.audit_events_archive "
                "WHERE event_type = :et AND subject_id = :tid"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"et": event_type, "tid": tenant_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_suspend_then_reactivate(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)

    suspended = await service.suspend_tenant(
        created.tenant_id, reason="trial expired", actor_user_id=uuid4()
    )
    assert suspended.status == "suspended"
    assert suspended.suspended_at is not None
    assert suspended.last_status_reason == "trial expired"

    reactivated = await service.reactivate_tenant(created.tenant_id, actor_user_id=uuid4())
    assert reactivated.status == "active"
    assert reactivated.suspended_at is None
    assert reactivated.last_status_reason is None

    assert (
        await _archive_count(
            admin_session, event_type="platform.tenant_suspended", tenant_id=created.tenant_id
        )
        == 1
    )
    assert (
        await _archive_count(
            admin_session,
            event_type="platform.tenant_reactivated",
            tenant_id=created.tenant_id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_double_suspend_rejected(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)

    await service.suspend_tenant(created.tenant_id, actor_user_id=uuid4())
    with pytest.raises(InvalidStatusTransitionError):
        await service.suspend_tenant(created.tenant_id, actor_user_id=uuid4())


@pytest.mark.asyncio
async def test_reactivate_active_rejected(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)
    with pytest.raises(InvalidStatusTransitionError):
        await service.reactivate_tenant(created.tenant_id, actor_user_id=uuid4())


@pytest.mark.asyncio
async def test_request_delete_then_cancel(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)

    pending = await service.request_delete(
        created.tenant_id, reason="customer leaving", actor_user_id=uuid4()
    )
    assert pending.status == "pending_delete"
    assert pending.deleted_at is not None
    assert pending.purge_eligible_at is not None
    assert pending.purge_eligible_at > datetime.now(UTC) + timedelta(days=29)

    cancelled = await service.cancel_delete(created.tenant_id, actor_user_id=uuid4())
    # Conservative default — cancellation returns to suspended, not active.
    assert cancelled.status == "suspended"
    assert cancelled.deleted_at is None


@pytest.mark.asyncio
async def test_purge_requires_pending_delete(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)
    with pytest.raises(InvalidStatusTransitionError):
        await service.purge_tenant(
            created.tenant_id,
            slug_confirmation=created.slug,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_purge_requires_slug_confirmation(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)
    await service.request_delete(created.tenant_id, actor_user_id=uuid4())
    with pytest.raises(SlugConfirmationMismatchError):
        await service.purge_tenant(
            created.tenant_id,
            slug_confirmation="not-the-slug",
            force=True,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_purge_blocked_inside_grace_window(admin_session: AsyncSession) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)
    await service.request_delete(created.tenant_id, actor_user_id=uuid4())
    with pytest.raises(PurgeNotEligibleError):
        await service.purge_tenant(
            created.tenant_id,
            slug_confirmation=created.slug,
            force=False,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_meta_lists_pickers(admin_session: AsyncSession) -> None:
    # _meta is a router-level endpoint, but its body is plain Python — we
    # invoke the function directly to avoid spinning up a full ASGI app.
    from app.modules.tenancy.router import tenant_meta
    from app.modules.tenancy.service import PURGE_GRACE_DAYS

    response = await tenant_meta(context=None)  # type: ignore[arg-type]
    assert "active" in response.statuses
    assert "pending_provision" in response.statuses
    assert "pending_delete" in response.statuses
    assert "free" in response.tiers
    assert "ar" in response.locales
    assert response.unit_systems == ["feddan", "acre", "hectare"]
    assert response.purge_grace_days == PURGE_GRACE_DAYS


@pytest.mark.asyncio
async def test_purge_force_drops_schema_and_public_rows(
    admin_session: AsyncSession,
) -> None:
    service = get_tenant_service(admin_session)
    created = await _create(admin_session)
    await service.request_delete(created.tenant_id, actor_user_id=uuid4())

    await service.purge_tenant(
        created.tenant_id,
        slug_confirmation=created.slug,
        force=True,
        actor_user_id=uuid4(),
    )

    # Tenant row is gone.
    with pytest.raises(TenantNotFoundError):
        await service.get_tenant(created.tenant_id)

    # Schema is dropped (the migrator runs against a separate engine which
    # commits independently — the row is therefore visible across sessions).
    schema_exists = (
        await admin_session.execute(
            text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": created.schema_name},
        )
    ).scalar_one()
    assert schema_exists == 0

    # The platform-archive trail still has the purge record.
    purged = await _archive_count(
        admin_session,
        event_type="platform.tenant_purged",
        tenant_id=created.tenant_id,
    )
    assert purged == 1
