"""When does a block STOP being fetched on its own?

Only when its farm is genuinely fetching the whole AOI. This is the most
dangerous predicate in the cutover: migration 0074 created an
`imagery_farm_subscriptions` row for *every* farm that had block
subscriptions, so a gate keyed on "does a farm subscription exist" would
have stopped imagery for every farm on the platform the moment it shipped.

The gate is `fetch_farm_aoi`, and these tests exist to keep it that way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.repository import ImageryRepository
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_subscription_crud import _create_farm_and_block, _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, UUID, UUID, str]:
    """Tenant + farm + block + an active BLOCK imagery subscription."""
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
    return tenant.schema_name, UUID(farm_id), UUID(product_id), block_id


async def _due_count(session: AsyncSession, schema: str) -> int:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = await ImageryRepository(session).list_active_subscriptions_due(
        default_cadence_hours=24, now=datetime.now(UTC)
    )
    return len(rows)


@pytest.mark.asyncio
async def test_a_block_is_due_when_its_farm_has_not_cut_over(
    admin_session: AsyncSession,
) -> None:
    schema, _farm_id, _product_id, _block_id = await _setup(admin_session, "gate-plain")
    assert await _due_count(admin_session, schema) == 1


@pytest.mark.asyncio
async def test_a_dormant_farm_row_does_not_stop_the_block(
    admin_session: AsyncSession,
) -> None:
    """The whole point. 0074 gave every farm one of these rows.

    If the gate keyed on existence rather than on fetch_farm_aoi, this test
    would see 0 — and every farm on the platform would have stopped fetching
    imagery on deploy.
    """
    schema, farm_id, product_id, _block_id = await _setup(admin_session, "gate-dormant")
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, FALSE)"
        ),
        {"id": uuid4(), "farm": farm_id, "product": product_id},
    )
    await admin_session.commit()

    assert await _due_count(admin_session, schema) == 1


@pytest.mark.asyncio
async def test_the_block_stops_once_the_farm_fetches_its_whole_aoi(
    admin_session: AsyncSession,
) -> None:
    schema, farm_id, product_id, _block_id = await _setup(admin_session, "gate-cutover")
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": uuid4(), "farm": farm_id, "product": product_id},
    )
    await admin_session.commit()

    # One farm-AOI fetch now covers this block, so fetching it separately
    # would be paying twice for the same ground.
    assert await _due_count(admin_session, schema) == 0


@pytest.mark.asyncio
async def test_a_different_product_is_unaffected(
    admin_session: AsyncSession,
) -> None:
    """The gate matches on product, not just farm.

    A farm fetching one product's AOI says nothing about another product it
    subscribes to per block.
    """
    schema, farm_id, _product_id, _block_id = await _setup(admin_session, "gate-product")
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": uuid4(), "farm": farm_id, "product": uuid4()},
    )
    await admin_session.commit()

    assert await _due_count(admin_session, schema) == 1
