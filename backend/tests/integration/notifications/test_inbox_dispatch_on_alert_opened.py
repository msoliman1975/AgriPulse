"""When an alert fires, the notifications subscriber must:

  * Insert one ``in_app_inbox`` row per scoped user.
  * Insert ``notification_dispatches`` rows for each (user, channel)
    pair the tenant has enabled — sent for in_app, skipped for email
    and webhook (their senders land in PR-D / PR-E).

The test goes through the real Beat-equivalent path: the alerts service
publishes ``AlertOpenedV1``, which the registered notifications
subscriber picks up synchronously.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.service import get_alerts_service
from app.modules.notifications.subscribers import register_subscribers
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.eventbus import get_default_bus
from tests.integration.alerts.test_alerts_pipeline import _seed_block_with_ndvi_row
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _attach_user_to_farm(
    admin: AsyncSession, *, tenant_id: UUID, user_id: UUID, farm_id: UUID
) -> None:
    """Reuse the membership created by ``_create_user_in_tenant`` and
    grant it a farm_scope on the target farm.
    """
    row = (
        await admin.execute(
            text(
                "SELECT id FROM public.tenant_memberships "
                "WHERE user_id = :uid AND tenant_id = :tid"
            ).bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
            ),
            {"uid": user_id, "tid": tenant_id},
        )
    ).first()
    assert row is not None
    membership_id = row.id
    await admin.execute(
        text(
            "INSERT INTO public.farm_scopes (membership_id, farm_id, role) "
            "VALUES (:mid, :fid, 'FarmManager')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "fid": farm_id},
    )
    await admin.commit()


@pytest.mark.asyncio
async def test_alert_open_creates_inbox_item_and_skipped_dispatches(
    admin_session: AsyncSession,
) -> None:
    register_subscribers(get_default_bus())

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4b-inbox",
        name="PR-S4-B inbox",
        contact_email="ops@pr-s4b.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )
    await _attach_user_to_farm(
        admin_session, tenant_id=tenant.tenant_id, user_id=user_id, farm_id=farm_id
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            summary = await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
    assert summary["alerts_opened"] == 1

    # ---- inbox row ---------------------------------------------------
    inbox_rows = (
        (
            await admin_session.execute(
                text(
                    f"SELECT id, user_id, alert_id, severity, title, body, link_url, read_at "
                    f'FROM "{tenant.schema_name}".in_app_inbox WHERE user_id = :uid'
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(inbox_rows) == 1
    item = dict(inbox_rows[0])
    assert item["severity"] == "critical"
    assert item["read_at"] is None
    assert "/alerts/" in item["link_url"]
    assert item["title"]  # non-empty rendered subject
    assert item["body"]

    # ---- dispatch rows: in_app=sent, email=sent (MailHog), webhook=skipped --
    rows = (
        (
            await admin_session.execute(
                text(
                    f'SELECT channel, status FROM "{tenant.schema_name}".notification_dispatches '
                    f"WHERE recipient_user_id = :uid OR recipient_user_id IS NULL "
                    f"ORDER BY channel"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    by_channel = {r["channel"]: r["status"] for r in rows}
    assert by_channel.get("in_app") == "sent"
    # PR-D wires the email channel to MailHog (compose stack); PR-E
    # will flip webhook from skipped to sent.
    assert by_channel.get("email") == "sent"
    assert by_channel.get("webhook") == "skipped"


@pytest.mark.asyncio
async def test_alert_open_with_no_recipients_emits_no_inbox(
    admin_session: AsyncSession,
) -> None:
    """A scoped tenant with no users on the affected farm produces no
    inbox rows and no dispatches."""
    register_subscribers(get_default_bus())

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4b-no-recipients",
        name="PR-S4-B no recipients",
        contact_email="ops@pr-s4b-no.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )

    inbox_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".in_app_inbox')
        )
    ).scalar_one()
    assert inbox_count == 0

    dispatch_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".notification_dispatches')
        )
    ).scalar_one()
    assert dispatch_count == 0
