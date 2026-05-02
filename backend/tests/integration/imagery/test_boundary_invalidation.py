"""BlockBoundaryChangedV1 → reset last_successful_ingest_at.

Slice 1 emits this event whenever a block's polygon is replaced. The
imagery subscriber listens for it and clears `last_successful_ingest_at`
on every active subscription for that block, so the next discovery
runs against the new aoi_hash.

We don't go through farms' PATCH endpoint here — that would couple this
test to farms HTTP details we don't need. We simulate the event by
publishing it directly on the bus after seeding state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.events import BlockBoundaryChangedV1
from app.modules.imagery.subscribers import register_subscribers
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from app.shared.eventbus import EventBus

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_subscription_crud import (
    _create_farm_and_block,
    _get_s2l2a_product_id,
)

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_block_boundary_changed_resets_last_successful(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-boundary",
        name="Imagery Boundary",
        contact_email="ops@boundary.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        sub_id = UUID(sub_resp.json()["id"])

    # Seed `last_successful_ingest_at` to a non-null value so we can
    # observe the reset.
    seed_at = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    await admin_session.execute(
        text(
            f'UPDATE "{tenant.schema_name}".imagery_aoi_subscriptions '
            "SET last_successful_ingest_at = :ts WHERE id = :id"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"ts": seed_at, "id": sub_id},
    )
    await admin_session.commit()

    # Wire the subscriber on a fresh bus and publish the event.
    bus = EventBus()
    register_subscribers(bus)
    bus.publish(
        BlockBoundaryChangedV1(
            block_id=UUID(block_id),
            farm_id=UUID(farm_id),
            prev_aoi_hash="0" * 64,
            new_aoi_hash="1" * 64,
            actor_user_id=user_id,
        )
    )

    # last_successful_ingest_at should now be NULL on the subscription.
    after = (
        await admin_session.execute(
            text(
                f'SELECT last_successful_ingest_at FROM "{tenant.schema_name}".'
                "imagery_aoi_subscriptions WHERE id = :id"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": sub_id},
        )
    ).scalar_one()
    assert after is None
