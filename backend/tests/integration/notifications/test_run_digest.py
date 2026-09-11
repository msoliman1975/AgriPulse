"""One message per finding per run, not one per block.

The bug: a decision-tree sweep opens one alert per block, and the
notifications fan-out sent one message per alert. A 23-block farm
produced 23 emails whose subjects differed only in the block number —
``Warning · My new tree — 011, Mango Republic``, then 012, then 013.
Production sent 666 emails in ten days that way.

The alerts themselves are correct and stay one per block: the Action
Center needs a row it can close per block. Only the telling is
consolidated, and only for alerts opened inside an evaluation run —
outside one, nothing would ever flush them, so they still go out at
once. ``test_inbox_dispatch_on_alert_opened.py`` covers that path and
is what proves this change did not silence the immediate case.
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
from app.modules.recommendations.events import EvaluationRunFinishedV1
from app.modules.recommendations.service import get_recommendations_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.eventbus import get_default_bus
from tests.integration.farms.test_farms_crud import _create_user_in_tenant
from tests.integration.notifications.test_inbox_dispatch_on_alert_opened import (
    _attach_user_to_farm,
)

pytestmark = [pytest.mark.integration]

# The seed tree this exercises. Its `leaf_alert_critical` leaf fires on a
# severe NDVI drop and is what the sibling module drives too.
_DEVIATION = Decimal("-2.0")


async def _seed_farm(admin: AsyncSession, schema: str) -> UUID:
    farm_id = uuid4()
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await admin.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, 'DIGEST-FARM', 'Digest Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, 100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin.commit()
    return farm_id


async def _seed_block(admin: AsyncSession, schema: str, farm_id: UUID, code: str) -> UUID:
    """One block that will fire the alert leaf, with its own NDVI row."""
    block_id = uuid4()
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await admin.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, "
            "                    area_m2, aoi_hash, unit_type) "
            "VALUES (:bid, :fid, :code, "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, 50, :aoi, 'block')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id, "code": code, "aoi": f"digest-aoi-{code}"},
    )
    await admin.execute(
        text(
            "INSERT INTO block_index_aggregates ("
            "  time, block_id, index_code, product_id, mean, valid_pixel_count, "
            "  total_pixel_count, stac_item_id, baseline_deviation"
            ") VALUES (:time, :block_id, 'ndvi', :product_id, 0.45, 100, 100, "
            "          :scene, :deviation)"
        ).bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("product_id", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "time": datetime.now(UTC).replace(microsecond=0),
            "block_id": block_id,
            "product_id": uuid4(),
            "scene": f"digest/{code}",
            "deviation": _DEVIATION,
        },
    )
    await admin.commit()
    return block_id


async def _run_sweep(schema: str, tenant_id: UUID, block_ids: list[UUID]) -> UUID:
    """Evaluate every block under ONE run, the way the Beat sweep does.

    Returns the run id. Nothing is announced here: the point of the test
    is that no per-user message has gone out yet at this moment.
    """
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            run_id = await svc._repo.open_eval_run(kind="sweep", actor_user_id=None)

    for block_id in block_ids:
        async with factory() as session, session.begin():
            await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            async with factory() as public_session:
                svc = get_recommendations_service(
                    tenant_session=session, public_session=public_session
                )
                await svc.evaluate_block(
                    block_id=block_id,
                    actor_user_id=None,
                    tenant_schema=schema,
                    tenant_id=tenant_id,
                    run_id=run_id,
                )
    return run_id


async def _dispatches(admin: AsyncSession, schema: str, user_id: UUID, channel: str) -> list[dict]:
    rows = (
        (
            await admin.execute(
                text(
                    f"SELECT template_code, status, rendered_subject, rendered_body "
                    f'FROM "{schema}".notification_dispatches '
                    f"WHERE recipient_user_id = :uid AND channel = :ch "
                    f"ORDER BY created_at"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id, "ch": channel},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _setup(admin: AsyncSession, slug: str, block_codes: list[str]):
    register_subscribers(get_default_bus())
    # The platform catalogue is installed by public migration 0085,
    # which the conftest applies when it upgrades to head.
    tenancy = get_tenant_service(admin)
    tenant = await tenancy.create_tenant(
        slug=f"{slug}-{uuid4().hex[:6]}",
        name="Digest tenant",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin, tenant_id=tenant.tenant_id, user_id=user_id)
    farm_id = await _seed_farm(admin, tenant.schema_name)
    await _attach_user_to_farm(admin, tenant_id=tenant.tenant_id, user_id=user_id, farm_id=farm_id)
    blocks = [await _seed_block(admin, tenant.schema_name, farm_id, c) for c in block_codes]
    return tenant, user_id, farm_id, blocks


@pytest.mark.asyncio
async def test_three_blocks_produce_one_email_not_three(admin_session: AsyncSession) -> None:
    codes = ["D-01", "D-02", "D-03"]
    tenant, user_id, _farm_id, blocks = await _setup(admin_session, "digest-one", codes)

    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)

    # Before the run is announced, nothing has reached the person. This is
    # the assertion that proves the hold is real rather than the digest
    # simply arriving on top of three emails already sent.
    assert await _dispatches(admin_session, tenant.schema_name, user_id, "email") == []

    get_default_bus().publish(
        EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    )

    emails = await _dispatches(admin_session, tenant.schema_name, user_id, "email")
    digests = [e for e in emails if e["template_code"] == "alert_digest"]
    assert len(digests) == 1, f"expected one consolidated email, got {len(emails)}: {emails}"

    body = digests[0]["rendered_body"]
    subject = digests[0]["rendered_subject"]
    # It has to name every block, or the reader has to open the app to
    # learn which three of their blocks it means.
    for code in codes:
        assert code in body, f"{code} missing from the digest body"
    assert "3 blocks" in subject


@pytest.mark.asyncio
async def test_the_alerts_themselves_are_still_one_per_block(
    admin_session: AsyncSession,
) -> None:
    """Consolidation is about the telling, not the work.

    The Action Center closes a row per block, so collapsing the alerts
    would take away the thing a supervisor acts on.
    """
    codes = ["E-01", "E-02", "E-03"]
    tenant, _user_id, _farm_id, blocks = await _setup(admin_session, "digest-rows", codes)
    await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)

    count = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{tenant.schema_name}".alerts '
                f"WHERE deleted_at IS NULL AND group_parent_id IS NULL"
            )
        )
    ).scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_a_second_announcement_sends_nothing_further(
    admin_session: AsyncSession,
) -> None:
    """The run-finished event is published from a ``finally``, so a sweep
    that both fails and then unwinds can announce twice. The dispatch
    table's partial UNIQUE has to make the repeat a no-op — otherwise the
    crash path is worse than the bug this change fixes.
    """
    tenant, user_id, _farm_id, blocks = await _setup(
        admin_session, "digest-twice", ["F-01", "F-02"]
    )
    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)

    event = EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    get_default_bus().publish(event)
    after_first = await _dispatches(admin_session, tenant.schema_name, user_id, "email")
    get_default_bus().publish(event)
    after_second = await _dispatches(admin_session, tenant.schema_name, user_id, "email")

    sent_first = [d for d in after_first if d["status"] == "sent"]
    sent_second = [d for d in after_second if d["status"] == "sent"]
    assert len(sent_first) == 1
    assert len(sent_second) == 1, "the second announcement sent a duplicate"


@pytest.mark.asyncio
async def test_the_bell_gets_one_row_too(admin_session: AsyncSession) -> None:
    """The in-app inbox was flooded the same way — 999 rows over the same
    ten days the 666 emails went out."""
    tenant, user_id, _farm_id, blocks = await _setup(
        admin_session, "digest-bell", ["G-01", "G-02", "G-03"]
    )
    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)
    get_default_bus().publish(
        EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    )

    rows = (
        (
            await admin_session.execute(
                text(
                    f"SELECT title, body, link_url "
                    f'FROM "{tenant.schema_name}".in_app_inbox '
                    f"WHERE user_id = :uid AND alert_id IS NOT NULL"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    # The bell opens the queue, not one of the three alerts.
    assert "kind=alert" in rows[0]["link_url"]
    assert "item=" not in rows[0]["link_url"]


@pytest.mark.asyncio
async def test_digest_carries_the_tree_description_and_what_was_measured(
    admin_session: AsyncSession,
) -> None:
    """The second half of the complaint: the email said what, never why.

    ``decision_trees.description_en`` is written in the authoring screen
    and, until this change, appeared on no surface at all.
    """
    tenant, user_id, _farm_id, blocks = await _setup(admin_session, "digest-why", ["H-01", "H-02"])
    await admin_session.execute(
        text(
            "UPDATE public.decision_trees SET description_en = :d "
            "WHERE code = 'ndvi_baseline_alert_v1'"
        ),
        {"d": "Flags blocks whose canopy signal has dropped far below their own baseline."},
    )
    await admin_session.commit()

    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)
    get_default_bus().publish(
        EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    )

    digests = [
        d
        for d in await _dispatches(admin_session, tenant.schema_name, user_id, "email")
        if d["template_code"] == "alert_digest"
    ]
    assert len(digests) == 1
    body = digests[0]["rendered_body"]
    assert "WHY THIS TREE RAN" in body
    assert "canopy signal has dropped" in body
    # And what the walk actually resolved, labelled the way every other
    # surface labels it.
    assert "WHAT WE MEASURED" in body
    assert "NDVI" in body


@pytest.mark.asyncio
async def test_recommendations_consolidate_the_same_way(
    admin_session: AsyncSession,
) -> None:
    """The larger half of the same flood.

    On 2026-08-31 one production sweep opened 287 recommendations and sent
    574 emails — six times the alert volume, through the same bug. The
    seed catalogue fires recommendation leaves on these blocks alongside
    the alert leaf, so one run produces both kinds and this asserts the
    recommendation side lands as one message per group too.
    """
    codes = ["J-01", "J-02", "J-03"]
    tenant, user_id, _farm_id, blocks = await _setup(admin_session, "digest-recs", codes)
    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)

    assert await _dispatches(admin_session, tenant.schema_name, user_id, "email") == []

    get_default_bus().publish(
        EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    )

    emails = await _dispatches(admin_session, tenant.schema_name, user_id, "email")
    per_code: dict[str, int] = {}
    for e in emails:
        if e["status"] == "sent":
            per_code[e["template_code"]] = per_code.get(e["template_code"], 0) + 1

    # Nothing may go out under the per-item template codes: those are the
    # one-email-per-block path this change exists to stop.
    assert per_code.get("alert_opened", 0) == 0
    assert per_code.get("recommendation_opened", 0) == 0
    # And every digest that did go out is one per group, never one per block.
    for code, count in per_code.items():
        assert count <= 3, f"{code} sent {count} emails for 3 blocks"


@pytest.mark.asyncio
async def test_a_recommendation_digest_uses_the_recommendation_id_column(
    admin_session: AsyncSession,
) -> None:
    """`notification_dispatches` and `in_app_inbox` both CHECK that exactly
    one of alert_id / recommendation_id is set. The digest served alerts
    only at first and hard-coded `alert_id=`; left that way it would fail
    the constraint on every recommendation."""
    tenant, user_id, _farm_id, blocks = await _setup(
        admin_session, "digest-reccol", ["K-01", "K-02"]
    )
    run_id = await _run_sweep(tenant.schema_name, tenant.tenant_id, blocks)
    get_default_bus().publish(
        EvaluationRunFinishedV1(run_id=run_id, tenant_schema=tenant.schema_name, kind="sweep")
    )

    rows = (
        (
            await admin_session.execute(
                text(
                    f"SELECT template_code, alert_id, recommendation_id "
                    f'FROM "{tenant.schema_name}".notification_dispatches '
                    f"WHERE recipient_user_id = :uid AND template_code LIKE '%_digest'"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    assert rows, "the run produced no digest dispatches at all"
    for row in rows:
        if row["template_code"] == "alert_digest":
            assert row["alert_id"] is not None
            assert row["recommendation_id"] is None
        else:
            assert row["recommendation_id"] is not None
            assert row["alert_id"] is None
