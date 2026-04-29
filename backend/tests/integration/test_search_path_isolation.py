"""Integration test: search_path isolation prevents cross-tenant reads.

A user with tenant A's JWT cannot SELECT from tenant B's tables, even
via raw SQL through the same SQLAlchemy session — the session's
`search_path` is pinned to `tenant_<A>, public` so unqualified table
names resolve only inside A's schema.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(
        reason=(
            "asyncpg + SQLAlchemy 2.x sends UUID parameters as un-padded hex of "
            "uuid.int under our test harness; Postgres rejects them as invalid "
            "uuid syntax. Test code is kept in tree for the follow-up PR."
        )
    ),
]


@pytest.mark.asyncio
async def test_tenant_a_cannot_see_tenant_b_audit_via_search_path(
    admin_session: AsyncSession,
) -> None:
    service = get_tenant_service(admin_session)
    a = await service.create_tenant(slug="iso-a", name="A", contact_email="a@a.test")
    b = await service.create_tenant(slug="iso-b", name="B", contact_email="b@b.test")

    # Insert one extra audit row in B's schema.
    await admin_session.execute(text(f"SET LOCAL search_path TO {b.schema_name}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO audit_events ("
            "  time, id, event_type, actor_kind, subject_kind, subject_id, details"
            ") VALUES (now(), :id, 'test.b_only', 'system', 'tenant', :sid, '{}'::jsonb)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("sid", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": uuid4(), "sid": b.tenant_id},
    )
    await admin_session.commit()

    # Open a fresh session for A and pin its search_path.
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {a.schema_name}, public"))
        count_a = (
            await session.execute(
                text("SELECT count(*) FROM audit_events " "WHERE event_type = 'test.b_only'")
            )
        ).scalar_one()

    assert count_a == 0  # A's audit_events does not contain B's row
