"""The farm timeline, driven through the HTTP API.

Seven tables feed one endpoint through seven hand-written SQL statements,
so the first thing worth proving is that all seven execute and that each
lands its row on the right UTC calendar day. After that: the block scope,
which is the only scope that carries a phenology stage; the capability
split, which drops kinds instead of 403-ing the screen; and the two
argument checks.

Rows are inserted schema-qualified rather than through a `SET
search_path`. A test that sets the path and then commits hands the
connection back to the pool, and the next read runs unscoped and returns
an empty list with no error.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.timeline.router import router as timeline_router
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]

# Fixed days inside the default window, far enough apart that a bucket
# error shows up as a different day rather than as a near-miss.
DAY_FLAG = date(2026, 6, 3)
DAY_SIGNAL = date(2026, 6, 5)
DAY_ACTIVITY = date(2026, 6, 7)
DAY_VISIT = date(2026, 6, 9)
DAY_ALERT = date(2026, 6, 11)
DAY_REC = date(2026, 6, 13)
DAY_STAGE = date(2026, 6, 15)

WINDOW_FROM = date(2026, 6, 1)
WINDOW_TO = date(2026, 6, 30)


def _at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 30, tzinfo=UTC)


def build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(timeline_router)
    app.add_middleware(StubAuth, context=context)
    return app


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _seed(session: AsyncSession, env: ScoutingFixture) -> UUID:
    """One row per kind, each on its own day. Returns the signal definition id."""
    s = env.schema
    farm = UUID(env.farm_id)
    block = UUID(env.block_id)
    actor = env.scout_user_id

    await session.execute(
        text(
            f"INSERT INTO {s}.field_flags "
            "(farm_id, block_id, note, severity, status, pin_until, raised_by, created_at) "
            "VALUES (:farm, :block, 'Water pooling across the row', 'warning', 'open', "
            ":pin, :actor, :at)"
        ),
        {
            "farm": farm,
            "block": block,
            "pin": _at(DAY_FLAG) + timedelta(days=14),
            "actor": actor,
            "at": _at(DAY_FLAG),
        },
    )

    # A platform-curated definition (tenant_id NULL) so the join in the
    # signals query has something to resolve. The name is what the rail
    # shows, so an empty title in the response would mean the join missed.
    definition_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.signal_definitions "
            "(id, tenant_id, code, name, value_kind, unit) "
            "VALUES (:id, NULL, :code, 'Leaf wetness', 'numeric', 'hrs')"
        ),
        {"id": definition_id, "code": f"lw-{definition_id.hex[:8]}"},
    )
    await session.execute(
        text(
            f"INSERT INTO {s}.signal_observations "
            "(time, signal_definition_id, block_id, farm_id, value_numeric, recorded_by) "
            "VALUES (:at, :def, :block, :farm, 4.25, :actor)"
        ),
        {"at": _at(DAY_SIGNAL), "def": definition_id, "block": block, "farm": farm, "actor": actor},
    )

    await session.execute(
        text(
            f"INSERT INTO {s}.plan_activities "
            "(farm_id, block_id, activity_type, scheduled_date, status, completed_at, "
            "product_name) "
            "VALUES (:farm, :block, 'spraying', :sched, 'completed', :at, 'Copper')"
        ),
        {
            "farm": farm,
            "block": block,
            "sched": DAY_ACTIVITY - timedelta(days=2),
            "at": _at(DAY_ACTIVITY),
        },
    )

    await session.execute(
        text(
            f"INSERT INTO {s}.scouting_visits "
            "(farm_id, block_id, origin, title, severity, status, outcome, completed_at) "
            "VALUES (:farm, :block, 'ad_hoc', 'Check the east rows', 'info', "
            "'completed', 'resolved', :at)"
        ),
        {"farm": farm, "block": block, "at": _at(DAY_VISIT)},
    )

    await session.execute(
        text(
            f"INSERT INTO {s}.alerts "
            "(block_id, rule_code, action_type, severity, status, diagnosis_en, created_at) "
            "VALUES (:block, 'ndvi_drop', 'inspect', 'critical', 'open', "
            "'NDVI fell 22% in seven days', :at)"
        ),
        {"block": block, "at": _at(DAY_ALERT)},
    )

    await session.execute(
        text(
            f"INSERT INTO {s}.recommendations "
            "(block_id, farm_id, tree_id, tree_code, tree_version, action_type, severity, "
            "confidence, tree_path, text_en, evaluation_snapshot, created_at) "
            "VALUES (:block, :farm, :tree, 'mango_water', 1, 'irrigate', 'warning', "
            "0.800, '[]'::jsonb, 'Irrigate within 48 hours', '{}'::jsonb, :at)"
        ),
        {"block": block, "farm": farm, "tree": uuid4(), "at": _at(DAY_REC)},
    )

    await session.execute(
        text(
            f"INSERT INTO {s}.growth_stage_logs "
            "(block_id, stage, source, transition_date) "
            "VALUES (:block, 'flowering', 'manual', :at)"
        ),
        {"block": block, "at": _at(DAY_STAGE)},
    )

    await session.commit()
    return definition_id


async def _get(context, farm_id: str, **params):  # type: ignore[no-untyped-def]
    async with _client(context) as client:
        return await client.get(f"/api/v1/farms/{farm_id}/timeline", params=params)


@pytest.mark.asyncio
async def test_every_kind_lands_on_its_own_day(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    await _seed(admin_session, scouting_env)

    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
        block_id=scouting_env.block_id,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    day_by_kind = {e["kind"]: e["day"] for e in body["events"]}
    assert day_by_kind == {
        "flag": DAY_FLAG.isoformat(),
        "signal": DAY_SIGNAL.isoformat(),
        "activity": DAY_ACTIVITY.isoformat(),
        "visit": DAY_VISIT.isoformat(),
        "alert": DAY_ALERT.isoformat(),
        "recommendation": DAY_REC.isoformat(),
        "stage": DAY_STAGE.isoformat(),
    }

    # The rail is sorted by instant; the day buckets are sorted by day.
    assert [d["day"] for d in body["days"]] == sorted(d["day"] for d in body["days"])
    assert all(d["total"] == 1 for d in body["days"])
    assert body["truncated"] is False
    assert body["from"] == WINDOW_FROM.isoformat()
    assert body["to"] == WINDOW_TO.isoformat()


@pytest.mark.asyncio
async def test_titles_and_codes_carry_the_source_text(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    await _seed(admin_session, scouting_env)

    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
        block_id=scouting_env.block_id,
    )
    by_kind = {e["kind"]: e for e in resp.json()["events"]}

    # The definition name and unit are joined in, not invented — an empty
    # title here means the public.signal_definitions join missed.
    assert by_kind["signal"]["title_en"] == "Leaf wetness: 4.2500 hrs"
    assert by_kind["alert"]["title_en"] == "NDVI fell 22% in seven days"
    assert by_kind["alert"]["code"] == "inspect"
    assert by_kind["alert"]["severity"] == "critical"
    assert by_kind["activity"]["code"] == "spraying"
    assert by_kind["activity"]["title_en"] == "Copper"
    assert by_kind["stage"]["code"] == "flowering"
    assert by_kind["flag"]["title_en"] == "Water pooling across the row"
    # Every event names its block, so the farm-scope rail can say where.
    assert by_kind["visit"]["block_code"] == "SB1"


@pytest.mark.asyncio
async def test_farm_scope_carries_no_phenology_stage(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    # Blocks on one farm run different plans, so a farm-wide stage row
    # would be untrue about all but one of them.
    await _seed(admin_session, scouting_env)

    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
    )
    body = resp.json()
    assert "stage" not in {e["kind"] for e in body["events"]}
    # Not "denied" either — it does not apply, so it is in neither list.
    assert "stage" not in body["omitted_kinds"]
    assert len(body["events"]) == 6


@pytest.mark.asyncio
async def test_scout_gets_a_partial_timeline_not_a_403(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    # A Scout holds farm scopes and no tenant role. Gating the route on all
    # seven capabilities would 403 the whole screen for them; the kinds
    # they cannot read are dropped and named instead.
    await _seed(admin_session, scouting_env)

    resp = await _get(
        scouting_env.scout_context,
        scouting_env.farm_id,
        **{"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    returned = {e["kind"] for e in body["events"]}
    omitted = set(body["omitted_kinds"])
    # Whatever the policy grants a Scout, the two sets must partition the
    # six farm-scope kinds — a kind that is neither returned nor named is
    # a kind the screen silently loses.
    assert returned | omitted == {
        "signal",
        "activity",
        "visit",
        "flag",
        "alert",
        "recommendation",
    }
    assert not (returned & omitted)


@pytest.mark.asyncio
async def test_a_block_from_another_farm_is_404(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    # The capability check gates on farm_id, so without the ownership
    # check a foreign block id would be read through a farm the caller
    # does have.
    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()},
        block_id=str(uuid4()),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_window_bounds_are_checked(scouting_env: ScoutingFixture) -> None:
    reversed_resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": "2026-06-30", "to": "2026-06-01"},
    )
    assert reversed_resp.status_code == 422, reversed_resp.text

    too_wide = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": "2024-01-01", "to": "2026-06-01"},
    )
    assert too_wide.status_code == 422, too_wide.text


@pytest.mark.asyncio
async def test_events_outside_the_window_are_left_out(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    await _seed(admin_session, scouting_env)

    # A window that ends the day before the first seeded row. The bound is
    # inclusive of `to`, so this must return nothing at all.
    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": "2026-05-01", "to": (DAY_FLAG - timedelta(days=1)).isoformat()},
    )
    body = resp.json()
    assert body["events"] == []
    assert body["days"] == []

    # And one that ends ON the first row's day, which must include it.
    resp = await _get(
        scouting_env.admin_context,
        scouting_env.farm_id,
        **{"from": "2026-05-01", "to": DAY_FLAG.isoformat()},
    )
    assert [e["kind"] for e in resp.json()["events"]] == ["flag"]
