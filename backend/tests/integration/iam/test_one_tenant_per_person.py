"""Migration 0074 — one live tenant membership per person.

Two things worth pinning. The index has to permit the case that keeps
offboarding working (an archived membership alongside a live one), and the
guard has to refuse rather than pick a tenant for somebody.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

INDEX = "uq_tenant_memberships_one_live_per_user"


async def _seed_user(session: AsyncSession, email: str):
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name, status) "
            "VALUES (:id, :kc, :e, 'Test Person', 'active')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id, "kc": f"kc-{user_id}", "e": email},
    )
    return user_id


async def _seed_tenant(session: AsyncSession, slug: str):
    tenant_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenants "
            "  (id, slug, name, status, schema_name, contact_email) "
            "VALUES (:id, :s, :s, 'active', :schema, :email)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": tenant_id,
            "s": slug,
            "schema": f"tenant_{tenant_id.hex}",
            "email": f"ops@{slug}.test",
        },
    )
    return tenant_id


async def _add_membership(session: AsyncSession, *, user_id, tenant_id, archived: bool):
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships "
            "  (id, tenant_id, user_id, status, deleted_at) "
            "VALUES (:id, :tid, :uid, :st, :del)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "tid": tenant_id,
            "uid": user_id,
            "st": "archived" if archived else "active",
            "del": datetime.now(UTC) if archived else None,
        },
    )


@pytest.mark.asyncio
async def test_the_index_exists_and_is_partial_on_deleted_at(
    admin_session: AsyncSession,
) -> None:
    row = (
        await admin_session.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
            {"n": INDEX},
        )
    ).first()
    assert row is not None, "migration 0074 did not run"
    assert "UNIQUE" in row.indexdef
    assert "deleted_at IS NULL" in row.indexdef


@pytest.mark.asyncio
async def test_a_second_live_membership_is_rejected_by_the_database(
    admin_session: AsyncSession,
) -> None:
    """The rule holds even for a writer that never learned it."""
    from sqlalchemy.exc import IntegrityError

    user_id = await _seed_user(admin_session, f"dup-{uuid4().hex[:8]}@t.test")
    tenant_a = await _seed_tenant(admin_session, f"idx-a-{uuid4().hex[:8]}")
    tenant_b = await _seed_tenant(admin_session, f"idx-b-{uuid4().hex[:8]}")
    await _add_membership(admin_session, user_id=user_id, tenant_id=tenant_a, archived=False)
    await admin_session.flush()

    # The violation surfaces on the INSERT itself, not on a later flush: the
    # index is checked by Postgres as the statement executes.
    with pytest.raises(IntegrityError):
        await _add_membership(admin_session, user_id=user_id, tenant_id=tenant_b, archived=False)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_an_archived_membership_does_not_block_a_new_tenant(
    admin_session: AsyncSession,
) -> None:
    """Offboard-then-rehire is the supported move and must stay possible."""
    user_id = await _seed_user(admin_session, f"rehire-{uuid4().hex[:8]}@t.test")
    tenant_a = await _seed_tenant(admin_session, f"idx-c-{uuid4().hex[:8]}")
    tenant_b = await _seed_tenant(admin_session, f"idx-d-{uuid4().hex[:8]}")
    await _add_membership(admin_session, user_id=user_id, tenant_id=tenant_a, archived=True)
    await _add_membership(admin_session, user_id=user_id, tenant_id=tenant_b, archived=False)
    await admin_session.flush()

    live = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM public.tenant_memberships "
                "WHERE user_id = :uid AND deleted_at IS NULL"
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id},
        )
    ).scalar_one()
    assert live == 1
    await admin_session.rollback()
