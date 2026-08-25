"""When does a daily subscription become due?

The plain cadence rule — "last attempt older than `cadence_hours`" — anchors a
daily poll wherever the previous one happened to land and keeps it there.
Measured on prod 2026-08-20: the Agrosina farm subscription polled at 03:23
UTC, and that day's Sentinel-2 L2A scene was published at 12:30 UTC. The poll
ran nine hours before the scene existed, so the product served three-day-old
imagery while a same-day scene sat in the catalogue.

The anchor hour is the fix. These tests pin both halves of it: a subscription
already polled today becomes due once the clock passes the anchor, and it does
NOT become due a second time after that poll.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

ANCHOR_HOUR = 14


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[str, UUID]:
    """Tenant + farm + block + one active block subscription."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        assert resp.status_code == 201, resp.text
        subscription_id = UUID(resp.json()["id"])
    return tenant.schema_name, subscription_id


async def _set_last_attempt(
    session: AsyncSession, schema: str, subscription_id: UUID, when: datetime
) -> None:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            "UPDATE imagery_aoi_subscriptions "
            "SET last_attempted_at = :when, cadence_hours = 24 WHERE id = :id"
        ),
        {"when": when, "id": subscription_id},
    )


async def _is_due(
    session: AsyncSession,
    schema: str,
    *,
    now: datetime,
    anchor_hour_utc: int | None,
) -> bool:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    rows = await ImageryRepository(session).list_active_subscriptions_due(
        default_cadence_hours=24, now=now, anchor_hour_utc=anchor_hour_utc
    )
    return len(rows) == 1


@pytest.mark.asyncio
async def test_an_early_morning_poll_becomes_due_again_after_the_anchor(
    admin_session: AsyncSession,
) -> None:
    """The prod case. Polled at 03:23, so the plain cadence rule says "not for
    another 24 hours" and the day's scene is missed. The anchor rule says
    "due", because the last poll was before today's anchor."""
    schema, subscription_id = await _setup(admin_session, "anchor-early")
    day = datetime(2026, 8, 20, tzinfo=UTC)
    await _set_last_attempt(admin_session, schema, subscription_id, day.replace(hour=3, minute=23))

    at_noon = day.replace(hour=12)
    at_evening = day.replace(hour=15)

    # Before the anchor: not due under either rule.
    assert await _is_due(admin_session, schema, now=at_noon, anchor_hour_utc=ANCHOR_HOUR) is False
    # After the anchor: due.
    assert await _is_due(admin_session, schema, now=at_evening, anchor_hour_utc=ANCHOR_HOUR) is True
    # And with the anchor switched off, the old behaviour is unchanged.
    assert await _is_due(admin_session, schema, now=at_evening, anchor_hour_utc=None) is False


@pytest.mark.asyncio
async def test_a_poll_at_the_anchor_does_not_fire_twice_the_same_day(
    admin_session: AsyncSession,
) -> None:
    """The rule must settle on one poll per day, not add a second one."""
    schema, subscription_id = await _setup(admin_session, "anchor-settled")
    day = datetime(2026, 8, 20, tzinfo=UTC)
    await _set_last_attempt(
        admin_session, schema, subscription_id, day.replace(hour=ANCHOR_HOUR, minute=2)
    )

    # Later the same day: already polled after the anchor, so not due.
    assert (
        await _is_due(admin_session, schema, now=day.replace(hour=23), anchor_hour_utc=ANCHOR_HOUR)
        is False
    )
    # Next day before the anchor: still not due.
    assert (
        await _is_due(
            admin_session,
            schema,
            now=(day + timedelta(days=1)).replace(hour=9),
            anchor_hour_utc=ANCHOR_HOUR,
        )
        is False
    )
    # Next day at the anchor: due again. One poll per day.
    assert (
        await _is_due(
            admin_session,
            schema,
            now=(day + timedelta(days=1)).replace(hour=ANCHOR_HOUR, minute=1),
            anchor_hour_utc=ANCHOR_HOUR,
        )
        is True
    )


@pytest.mark.asyncio
async def test_the_anchor_leaves_a_sub_daily_cadence_alone(
    admin_session: AsyncSession,
) -> None:
    """A subscription polling more often than daily already sees every scene.
    The anchor must not add a poll to it."""
    schema, subscription_id = await _setup(admin_session, "anchor-hourly")
    day = datetime(2026, 8, 20, tzinfo=UTC)
    await _set_last_attempt(admin_session, schema, subscription_id, day.replace(hour=15))
    await admin_session.execute(
        text("UPDATE imagery_aoi_subscriptions SET cadence_hours = 6 WHERE id = :id"),
        {"id": subscription_id},
    )

    # 15:00 poll, 6h cadence, now 17:00 — under both rules this is not due,
    # and the anchor (14:00, already passed) must not override the cadence.
    assert (
        await _is_due(admin_session, schema, now=day.replace(hour=17), anchor_hour_utc=ANCHOR_HOUR)
        is False
    )


@pytest.mark.asyncio
async def test_the_configured_anchor_clears_sentinel_2_publication() -> None:
    """Pin the shipped hour, because the first value chosen was too early.

    14:00 UTC was picked against Sentinel-2's documented 3-6h L2A publication
    latency. Measured on prod 2026-08-25: the Mango Republic pass was sensed
    at 08:41 UTC and processed at 13:51 UTC, and the 14:32 UTC poll still did
    not find it in the Copernicus catalogue. The same search at 22:21 UTC did.
    """
    from app.core.settings import get_settings

    assert get_settings().imagery_discovery_anchor_hour_utc == 20
