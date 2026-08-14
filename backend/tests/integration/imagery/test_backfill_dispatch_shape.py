"""What shape does a backfill take on a farm that has cut over?

The live sweep already refuses to fetch a block whose farm is fetched as one
AOI. The backfill did not: it fanned out per block regardless, which on a
cut-over farm meant paying the provider for ground the farm fetch already
covers, and landing the result in the block tables — so that farm's history
came out shaped unlike the live data sitting beside it.

These tests hold the dispatcher to the same decision the live sweep makes,
including the trap that decision is built around: migration 0074 created an
`imagery_farm_subscriptions` row for EVERY farm that had block subscriptions,
so a gate keyed on "does a farm subscription exist" would turn every backfill
on the platform into a no-op. The gate is `fetch_farm_aoi`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery import tasks as imagery_tasks
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_farm_aoi_ingestion import SCENE, _FakeProvider
from .test_subscription_crud import _create_farm_and_block, _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]

WINDOW_FROM = "2026-01-01"
WINDOW_TO = "2026-01-31"


class _Dispatched:
    """The two fan-out calls the dispatcher can make, captured not queued."""

    def __init__(self) -> None:
        self.block: list[tuple[Any, ...]] = []
        self.farm: list[tuple[Any, ...]] = []


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> _Dispatched:
    calls = _Dispatched()
    monkeypatch.setattr(
        imagery_tasks.backfill_scenes, "delay", lambda *a, **k: calls.block.append(a)
    )
    monkeypatch.setattr(
        imagery_tasks.backfill_farm_aoi_scenes, "delay", lambda *a, **k: calls.farm.append(a)
    )
    return calls


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, UUID, UUID, UUID]:
    """Tenant + farm + block + an active BLOCK imagery subscription.

    Returns ``(tenant_schema, farm_id, product_id, block_subscription_id)``.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        assert resp.status_code == 201, resp.text
        sub_id = resp.json()["id"]
    return tenant.schema_name, UUID(farm_id), UUID(product_id), UUID(sub_id)


async def _add_farm_subscription(
    admin_session: AsyncSession,
    *,
    schema: str,
    farm_id: UUID,
    product_id: UUID,
    fetch_farm_aoi: bool,
) -> UUID:
    sub_id = uuid4()
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, :fetch)"
        ),
        {"id": sub_id, "farm": farm_id, "product": product_id, "fetch": fetch_farm_aoi},
    )
    await admin_session.commit()
    return sub_id


async def _run_dispatcher(farm_id: UUID, schema: str) -> dict[str, int]:
    return await imagery_tasks._backfill_farm_scenes_async(
        farm_id, schema, WINDOW_FROM, WINDOW_TO, False
    )


@pytest.mark.asyncio
async def test_a_plain_farm_still_backfills_per_block(
    admin_session: AsyncSession, dispatched: _Dispatched
) -> None:
    schema, farm_id, _product_id, sub_id = await _setup(admin_session, "bf-shape-plain")

    result = await _run_dispatcher(farm_id, schema)

    assert result == {"subscriptions_enqueued": 1, "farm_subscriptions_enqueued": 0}
    assert [c[0] for c in dispatched.block] == [str(sub_id)]
    assert dispatched.farm == []


@pytest.mark.asyncio
async def test_a_dormant_farm_row_does_not_change_the_shape(
    admin_session: AsyncSession, dispatched: _Dispatched
) -> None:
    """The trap. 0074 gave every farm one of these rows.

    Keyed on existence rather than on `fetch_farm_aoi`, this test would see
    the block dispatch disappear — and every backfill on the platform would
    have started fetching nothing.
    """
    schema, farm_id, product_id, sub_id = await _setup(admin_session, "bf-shape-dormant")
    await _add_farm_subscription(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        product_id=product_id,
        fetch_farm_aoi=False,
    )

    result = await _run_dispatcher(farm_id, schema)

    assert result == {"subscriptions_enqueued": 1, "farm_subscriptions_enqueued": 0}
    assert [c[0] for c in dispatched.block] == [str(sub_id)]
    assert dispatched.farm == []


@pytest.mark.asyncio
async def test_a_cut_over_farm_backfills_as_one_surface(
    admin_session: AsyncSession, dispatched: _Dispatched
) -> None:
    schema, farm_id, product_id, _sub_id = await _setup(admin_session, "bf-shape-cutover")
    farm_sub_id = await _add_farm_subscription(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        product_id=product_id,
        fetch_farm_aoi=True,
    )

    result = await _run_dispatcher(farm_id, schema)

    # One whole-farm fetch per pass covers this block, so fetching the block
    # too would be buying the same ground twice.
    assert result == {"subscriptions_enqueued": 0, "farm_subscriptions_enqueued": 1}
    assert dispatched.block == []
    assert [c[0] for c in dispatched.farm] == [str(farm_sub_id)]
    # The window is what the operator asked for, not a watermark.
    assert dispatched.farm[0][2:] == (WINDOW_FROM, WINDOW_TO)


@pytest.mark.asyncio
async def test_a_product_the_farm_has_not_cut_over_is_still_per_block(
    admin_session: AsyncSession, dispatched: _Dispatched
) -> None:
    """The exclusion matches on product, exactly as the live sweep's does.

    A farm fetching one product's whole AOI says nothing about another
    product it still subscribes to per block.
    """
    schema, farm_id, _product_id, sub_id = await _setup(admin_session, "bf-shape-product")
    other_product = uuid4()
    farm_sub_id = await _add_farm_subscription(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        product_id=other_product,
        fetch_farm_aoi=True,
    )

    result = await _run_dispatcher(farm_id, schema)

    assert result == {"subscriptions_enqueued": 1, "farm_subscriptions_enqueued": 1}
    assert [c[0] for c in dispatched.block] == [str(sub_id)]
    assert [c[0] for c in dispatched.farm] == [str(farm_sub_id)]


@pytest.mark.asyncio
async def test_a_farm_backfill_does_not_move_the_live_watermark(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backfill ingests old passes; the live poll must not skip past them.

    `last_successful_ingest_at` is where the next live discovery starts, so
    letting a January backfill set it to "now" would bury every pass the
    daily sweep has not yet seen.
    """
    schema, farm_id, product_id, _sub_id = await _setup(admin_session, "bf-shape-watermark")
    farm_sub_id = await _add_farm_subscription(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        product_id=product_id,
        fetch_farm_aoi=True,
    )

    imagery_tasks.set_provider_factory(lambda _code: _FakeProvider((SCENE,)))
    monkeypatch.setattr(imagery_tasks.acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        result = await imagery_tasks._discover_farm_scenes_async(
            farm_sub_id,
            schema,
            window_start_override=datetime(2026, 1, 1, tzinfo=UTC),
            window_end_override=datetime(2026, 1, 31, tzinfo=UTC),
            bump_watermark=False,
        )
    finally:
        imagery_tasks.reset_provider_factory()

    # It really did ingest — otherwise an untouched watermark proves nothing.
    assert result["queued"] == 1

    row = (
        (
            await admin_session.execute(
                text(
                    f'SELECT last_attempted_at, last_successful_ingest_at FROM "{schema}"'
                    ".imagery_farm_subscriptions WHERE id = :id"
                ),
                {"id": farm_sub_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["last_attempted_at"] is None
    assert row["last_successful_ingest_at"] is None


@pytest.mark.asyncio
async def test_the_live_poll_still_moves_its_own_watermark(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the contract — `bump_watermark` defaults to on.

    Without this, a change that quietly stopped the live path recording its
    attempts would look identical to a correct one: the sweep would re-fetch
    the same window on every beat, forever.
    """
    schema, farm_id, product_id, _sub_id = await _setup(admin_session, "bf-shape-live")
    farm_sub_id = await _add_farm_subscription(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        product_id=product_id,
        fetch_farm_aoi=True,
    )

    imagery_tasks.set_provider_factory(lambda _code: _FakeProvider((SCENE,)))
    monkeypatch.setattr(imagery_tasks.acquire_farm_scene, "delay", lambda *a, **k: None)
    before = datetime.now(UTC) - timedelta(seconds=1)
    try:
        assert (await imagery_tasks._discover_farm_scenes_async(farm_sub_id, schema))["queued"] == 1
    finally:
        imagery_tasks.reset_provider_factory()

    row = (
        (
            await admin_session.execute(
                text(
                    f'SELECT last_attempted_at, last_successful_ingest_at FROM "{schema}"'
                    ".imagery_farm_subscriptions WHERE id = :id"
                ),
                {"id": farm_sub_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["last_attempted_at"] is not None
    assert row["last_attempted_at"] >= before
    assert row["last_successful_ingest_at"] is not None
