"""When an alert fires, the notifications subscriber must:

  * Insert one ``in_app_inbox`` row per scoped user.
  * Insert ``notification_dispatches`` rows for each (user, channel)
    pair the tenant has enabled — sent for in_app, sent for email
    (PR-D wired to MailHog), skipped for webhook.

Stage 2 of the rules sunset: this test now drives the alert via the
trees engine (``recommendations.service`` walks the
``ndvi_baseline_alert_v1`` seed tree → its ``leaf_alert_critical``
leaf publishes ``AlertOpenedV1`` via ``_open_alert_from_tree``). The
notifications subscriber path is identical regardless of source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.subscribers import register_subscribers
from app.modules.recommendations.loader import sync_from_disk
from app.modules.recommendations.service import get_recommendations_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.eventbus import get_default_bus
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _seed_block_with_ndvi_row(
    admin_session: AsyncSession, schema_name: str, *, deviation: Decimal
) -> tuple[UUID, UUID]:
    """Seed a farm + block + one block_index_aggregate row with the
    given baseline_deviation. Returns ``(farm_id, block_id)``.

    Was previously imported from the now-deleted
    ``tests/integration/alerts/test_alerts_pipeline.py``; inlined here
    after Stage 2 removed that file.
    """
    farm_id = uuid4()
    block_id = uuid4()
    product_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, 'PR-S4B-FARM', 'PR-S4B Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type) "
            "VALUES (:bid, :fid, 'B-PR-S4B', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'pr-s4b-aoi', 'block')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_index_aggregates ("
            "  time, block_id, index_code, product_id, mean, "
            "  valid_pixel_count, total_pixel_count, stac_item_id, baseline_deviation"
            ") VALUES ("
            "  :time, :block_id, 'ndvi', :product_id, 0.45, "
            "  100, 100, 'pr-s4b/scene', :deviation"
            ")"
        ).bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("product_id", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "time": datetime.now(UTC).replace(microsecond=0),
            "block_id": block_id,
            "product_id": product_id,
            "deviation": deviation,
        },
    )
    await admin_session.commit()
    return farm_id, block_id


async def _attach_user_to_farm(
    admin: AsyncSession, *, tenant_id: UUID, user_id: UUID, farm_id: UUID
) -> None:
    """Reuse the membership created by ``_create_user_in_tenant`` and
    grant it a farm_scope on the target farm."""
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


async def _evaluate_via_tree(schema_name: str, tenant_id: UUID, block_id: UUID) -> None:
    """Walk every visible tree against the block — same path the Beat
    recommendations sweep takes. The alert leaf publishes
    ``AlertOpenedV1`` synchronously via ``_open_alert_from_tree``."""
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=schema_name,
                tenant_id=tenant_id,
            )


@pytest.mark.asyncio
async def test_alert_open_creates_inbox_item_and_skipped_dispatches(
    admin_session: AsyncSession,
) -> None:
    register_subscribers(get_default_bus())
    # Tests skip app-startup lifespan, so the seed YAMLs aren't synced
    # into public.decision_trees. Call sync_from_disk ourselves.
    await sync_from_disk(admin_session)

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"pr-s4b-inbox-{uuid4().hex[:6]}",
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

    await _evaluate_via_tree(tenant.schema_name, tenant.tenant_id, block_id)

    # ---- inbox row ---------------------------------------------------
    # The seed catalog now ships TWO trees that both fire on a severe
    # NDVI drop: ``ndvi_baseline_alert_v1`` (kind=alert → inbox row
    # with `alert_id` set) and ``scout_for_stress_v1`` (kind=
    # recommendation → inbox row with `recommendation_id` set). The
    # subscriber dispatches each one independently, so we expect one
    # inbox row per fire-source. Filter to the alert row for this test.
    alert_rows = (
        (
            await admin_session.execute(
                text(
                    f"SELECT id, user_id, alert_id, severity, title, body, link_url, read_at "
                    f'FROM "{tenant.schema_name}".in_app_inbox '
                    f"WHERE user_id = :uid AND alert_id IS NOT NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(alert_rows) == 1
    item = dict(alert_rows[0])
    assert item["severity"] == "critical"
    assert item["read_at"] is None
    assert "/alerts/" in item["link_url"]
    assert item["title"]  # non-empty rendered subject
    assert item["body"]

    # ---- dispatch rows: in_app=sent, email=sent (MailHog), webhook=skipped --
    # Filter to the alert dispatches by joining via inbox_item_id =
    # alert row's id. Cleaner: scope by event_type once we have it; for
    # now check that every channel produced *at least* the expected
    # state for the alert. The recommendation dispatches are separate
    # rows for the same channels.
    rows = (
        (
            await admin_session.execute(
                text(
                    f'SELECT channel, status FROM "{tenant.schema_name}".notification_dispatches '
                    f"WHERE recipient_user_id = :uid OR recipient_user_id IS NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    statuses_per_channel: dict[str, set[str]] = {}
    for r in rows:
        statuses_per_channel.setdefault(r["channel"], set()).add(r["status"])
    assert "sent" in statuses_per_channel.get("in_app", set())
    assert "sent" in statuses_per_channel.get("email", set())
    assert "skipped" in statuses_per_channel.get("webhook", set())


@pytest.mark.asyncio
async def test_alert_open_with_no_recipients_emits_no_inbox(
    admin_session: AsyncSession,
) -> None:
    """A tenant with no users on the affected farm produces no inbox
    rows and no dispatches."""
    register_subscribers(get_default_bus())
    await sync_from_disk(admin_session)

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"pr-s4b-no-recipients-{uuid4().hex[:6]}",
        name="PR-S4-B no recipients",
        contact_email="ops@pr-s4b-no.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    await _evaluate_via_tree(tenant.schema_name, tenant.tenant_id, block_id)

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
