"""`/farms/{id}/blocks/summary` — recent-window lookup + stale fallback.

The latest-index lookup runs in two passes: a time-bounded one (so
TimescaleDB can exclude chunks — that bound is the whole performance fix,
see `_RECENT_WINDOW_DAYS`) and an unbounded sweep for any block the window
turned up nothing for.

These tests pin the part that could silently regress: a block whose only
readings predate the window must still report them. If someone later drops
the fallback to "simplify", a block that stopped being imaged would quietly
render as `unknown` on the map instead of showing its last known value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.blocks_summary_router import _RECENT_WINDOW_DAYS
from app.modules.farms.blocks_summary_router import router as summary_router
from app.modules.farms.router import router as farms_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import StubAuth, make_context

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [lon, lat],
                    [lon + side, lat],
                    [lon + side, lat + side],
                    [lon, lat + side],
                    [lon, lat],
                ]
            ]
        ],
    }


def _polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


def _build_app(context) -> FastAPI:
    """farms router (to create the fixtures) + the summary router under test."""
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(summary_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "Test User",
        },
    )
    membership_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant_id},
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await session.commit()


async def _bootstrap(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


async def _insert_index(
    session: AsyncSession,
    *,
    schema: str,
    block_id: UUID,
    at: datetime,
    mean: float,
    index_code: str = "ndvi",
) -> None:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO block_index_aggregates "
            "(time, block_id, index_code, product_id, mean, "
            " valid_pixel_count, total_pixel_count, stac_item_id) "
            "VALUES (:t, :b, :code, :p, :mean, 100, 100, :scene)"
        ).bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "t": at,
            "b": block_id,
            "code": index_code,
            "p": uuid4(),
            "mean": mean,
            "scene": f"scene-{at.isoformat()}",
        },
    )
    await session.commit()


async def _insert_alert(
    session: AsyncSession,
    *,
    schema: str,
    block_id: UUID,
    severity: str,
    action_type: str | None,
    created_at: datetime,
    status: str = "open",
    resolved_at: datetime | None = None,
) -> None:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO alerts "
            "(id, block_id, rule_code, severity, action_type, status, "
            " created_at, updated_at, resolved_at) "
            "VALUES (:id, :b, :rule, :sev, :action, :status, :at, :at, :resolved)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("b", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "b": block_id,
            # Unique per row: `uq_alerts_block_rule_open` is partial on the
            # open statuses, so two alerts on one block need two rule codes.
            "rule": f"tree:t:{severity}:{action_type}:{created_at.isoformat()}",
            "sev": severity,
            "action": action_type,
            "at": created_at,
            "status": status,
            "resolved": resolved_at,
        },
    )
    await session.commit()


async def _make_farm_with_block(client: AsyncClient) -> tuple[str, str]:
    farm = await client.post(
        "/api/v1/farms",
        json={"code": "F1", "name": "F1", "boundary": _square(31.2, 30.0)},
    )
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]
    block = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": "B1", "name": "B1", "boundary": _polygon(31.201, 30.001)},
    )
    assert block.status_code == 201, block.text
    return farm_id, block.json()["id"]


@pytest.mark.asyncio
async def test_recent_reading_is_reported(admin_session: AsyncSession) -> None:
    """The common case: a reading inside the window comes back from pass one."""
    tenant, context = await _bootstrap(admin_session, "bsw-recent")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=2),
            mean=0.71,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.71)
    assert unit["health"] == "healthy"


@pytest.mark.asyncio
async def test_reading_older_than_the_window_still_reported(
    admin_session: AsyncSession,
) -> None:
    """A block whose only reading predates the window falls back, not to `unknown`.

    This is the regression guard: the bounded first pass finds nothing for
    this block, so the unbounded sweep has to pick it up.
    """
    tenant, context = await _bootstrap(admin_session, "bsw-stale")
    app = _build_app(context)

    stale_at = datetime.now(UTC) - timedelta(days=_RECENT_WINDOW_DAYS + 45)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=stale_at,
            mean=0.31,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.31), "stale reading was dropped"
    # 0.31 < 0.4, so the health classifier calls it critical — proves the
    # value actually reached classification rather than defaulting.
    assert unit["health"] == "critical"
    assert unit["last_index_at"] is not None


@pytest.mark.asyncio
async def test_recent_reading_wins_over_older_one(admin_session: AsyncSession) -> None:
    """With both, the in-window value is reported — the sweep must not override it."""
    tenant, context = await _bootstrap(admin_session, "bsw-both")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=_RECENT_WINDOW_DAYS + 30),
            mean=0.20,
        )
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=3),
            mean=0.66,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.66)


@pytest.mark.asyncio
async def test_block_with_no_readings_is_unknown(admin_session: AsyncSession) -> None:
    """Neither pass finds anything — the block still appears, as `unknown`."""
    _, context = await _bootstrap(admin_session, "bsw-none")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] is None
    assert unit["health"] == "unknown"
    assert unit["last_index_at"] is None


@pytest.mark.asyncio
async def test_alert_action_type_names_the_worst_alerts_verb(
    admin_session: AsyncSession,
) -> None:
    """The map draws ONE glyph per block, so the summary has to pick one verb.

    It picks the worst alert's, because that is the one whose severity the
    marker's colour is already showing. Picking the newest instead would
    colour a chip critical and draw the picture of an unrelated warning.
    """
    tenant, context = await _bootstrap(admin_session, "bsw-verb")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        # The warning is NEWER, so a plain "latest" rule would pick it.
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="critical",
            action_type="irrigate",
            created_at=now - timedelta(days=3),
        )
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="warning",
            action_type="spray",
            created_at=now,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["alert_action_type"] == "irrigate"
    assert unit["alert_severity"] == "critical"
    assert unit["alert_count"] == 2


@pytest.mark.asyncio
async def test_alert_action_type_skips_a_worst_alert_that_named_no_verb(
    admin_session: AsyncSession,
) -> None:
    """A null verb must not win, or the block draws the neutral glyph.

    Alert rows predate `action_type` (tenant migration 0063) and a tree leaf
    can still omit it, so the worst alert is often the one with nothing to
    draw. Falling through to the next alert down keeps the marker informative
    instead of showing the "not stated" glyph on a block we could describe.
    """
    tenant, context = await _bootstrap(admin_session, "bsw-verb-null")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="critical",
            action_type=None,
            created_at=now,
        )
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="warning",
            action_type="scout",
            created_at=now - timedelta(days=1),
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["alert_action_type"] == "scout"
    assert unit["alert_severity"] == "critical"


@pytest.mark.asyncio
async def test_block_with_no_alerts_reports_no_verb(admin_session: AsyncSession) -> None:
    """Null, not a default verb: the marker is not drawn at all in this case."""
    _tenant, context = await _bootstrap(admin_session, "bsw-verb-none")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["alert_action_type"] is None
    assert unit["alert_count"] == 0


# ---------------------------------------------------------------------------
# `at` — the alert rollup answered as of a past instant.
#
# The console's date bar sends it when a reader has scrubbed back to an older
# pass. The map is a picture of one day, and an alert that opened this morning
# did not exist on a scene from last week.
#
# Against the database on purpose. The rollup is raw SQL, and a fake session
# would assert the shape of a query rather than what Postgres does with it —
# which is how both SQL bugs in the platform-alerts work reached production.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as_of_excludes_an_alert_raised_after_it(admin_session: AsyncSession) -> None:
    """An alert opened yesterday is absent from a picture of last week."""
    tenant, context = await _bootstrap(admin_session, "bsw-asof-future")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="critical",
            action_type="inspect",
            created_at=now - timedelta(days=1),
        )

        live = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")
        past = await c.get(
            f"/api/v1/farms/{farm_id}/blocks/summary",
            params={"at": (now - timedelta(days=7)).isoformat()},
        )

    assert live.status_code == 200, live.text
    assert past.status_code == 200, past.text
    assert next(u for u in live.json()["units"] if u["id"] == block_id)["alert_count"] == 1
    unit = next(u for u in past.json()["units"] if u["id"] == block_id)
    assert unit["alert_count"] == 0
    assert unit["alert_severity"] is None
    assert unit["alert_action_type"] is None


@pytest.mark.asyncio
async def test_as_of_includes_an_alert_that_has_since_been_resolved(
    admin_session: AsyncSession,
) -> None:
    """The rule that makes this worth writing.

    Reading `status = 'open'` for a past instant would drop every alert closed
    since — so the further back a reader scrubbed, the FEWER alerts the map
    would show, which reads as "the farm was fine then". It was not; the alert
    was open on that day and was closed later.
    """
    tenant, context = await _bootstrap(admin_session, "bsw-asof-closed")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="warning",
            action_type="spray",
            created_at=now - timedelta(days=20),
            status="resolved",
            resolved_at=now - timedelta(days=2),
        )

        live = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")
        past = await c.get(
            f"/api/v1/farms/{farm_id}/blocks/summary",
            params={"at": (now - timedelta(days=10)).isoformat()},
        )

    assert live.status_code == 200, live.text
    assert past.status_code == 200, past.text
    # Closed today, so the live map says nothing is wrong.
    assert next(u for u in live.json()["units"] if u["id"] == block_id)["alert_count"] == 0
    # Ten days ago it was open, and the map for that day has to say so.
    unit = next(u for u in past.json()["units"] if u["id"] == block_id)
    assert unit["alert_count"] == 1
    assert unit["alert_severity"] == "watch"
    assert unit["alert_action_type"] == "spray"


@pytest.mark.asyncio
async def test_as_of_drops_one_resolved_before_it(admin_session: AsyncSession) -> None:
    """Resolved BEFORE the instant asked about: gone, on that day too."""
    tenant, context = await _bootstrap(admin_session, "bsw-asof-earlier")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="critical",
            action_type="irrigate",
            created_at=now - timedelta(days=40),
            status="resolved",
            resolved_at=now - timedelta(days=30),
        )

        past = await c.get(
            f"/api/v1/farms/{farm_id}/blocks/summary",
            params={"at": (now - timedelta(days=10)).isoformat()},
        )

    assert past.status_code == 200, past.text
    assert next(u for u in past.json()["units"] if u["id"] == block_id)["alert_count"] == 0


@pytest.mark.asyncio
async def test_omitting_at_answers_now(admin_session: AsyncSession) -> None:
    """No `at` is the behaviour every caller before this had — `status = 'open'`."""
    tenant, context = await _bootstrap(admin_session, "bsw-asof-omitted")
    app = _build_app(context)
    now = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_alert(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            severity="critical",
            action_type="inspect",
            created_at=now - timedelta(days=3),
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["alert_count"] == 1
    assert unit["alert_severity"] == "critical"
