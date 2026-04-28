"""Integration test: creating a tenant bootstraps schema, runs migrations,
and writes an audit event.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_tenant_bootstraps_schema_and_audits(
    admin_session: AsyncSession,
) -> None:
    from app.modules.tenancy.service import get_tenant_service
    from app.shared.db.ids import schema_name_for

    service = get_tenant_service(admin_session)

    actor = uuid4()
    result = await service.create_tenant(
        slug="acme-test",
        name="Acme Test",
        contact_email="ops@acme.test",
        actor_user_id=actor,
    )

    assert result.schema_name == schema_name_for(result.tenant_id)
    assert result.status == "active"

    # Tenant row, settings row, current subscription should all exist.
    row = (
        await admin_session.execute(
            text("SELECT slug, schema_name, status FROM public.tenants WHERE id = :tid"),
            {"tid": result.tenant_id},
        )
    ).one()
    assert row.slug == "acme-test"

    settings_count = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.tenant_settings WHERE tenant_id = :tid"),
            {"tid": result.tenant_id},
        )
    ).scalar_one()
    assert settings_count == 1

    sub_count = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM public.tenant_subscriptions "
                "WHERE tenant_id = :tid AND is_current = TRUE"
            ),
            {"tid": result.tenant_id},
        )
    ).scalar_one()
    assert sub_count == 1

    # Tenant schema exists with the audit_events hypertable.
    schema_exists = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM information_schema.schemata WHERE schema_name = :s"
            ),
            {"s": result.schema_name},
        )
    ).scalar_one()
    assert schema_exists == 1

    audit_table = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = :s AND table_name = 'audit_events'"
            ),
            {"s": result.schema_name},
        )
    ).scalar_one()
    assert audit_table == 1

    # Audit event written to the new tenant's audit_events.
    await admin_session.execute(text(f"SET LOCAL search_path TO {result.schema_name}, public"))
    audit_count = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE event_type = 'tenancy.tenant_created' AND subject_id = :tid"
            ),
            {"tid": result.tenant_id},
        )
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.asyncio
async def test_duplicate_slug_rejected(admin_session: AsyncSession) -> None:
    from app.modules.tenancy.service import SlugAlreadyExistsError, get_tenant_service

    service = get_tenant_service(admin_session)

    await service.create_tenant(
        slug="dup-slug-test",
        name="First",
        contact_email="a@a.test",
    )
    with pytest.raises(SlugAlreadyExistsError):
        await service.create_tenant(
            slug="dup-slug-test",
            name="Second",
            contact_email="b@b.test",
        )
