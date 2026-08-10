"""Auto-dispatch: recommendations and alerts becoming scouting visits.

The two paths are deliberately asymmetric and the asymmetry is the point, so
it is asserted rather than assumed:

* a recommendation dispatches because the tree said ``action_type: scout``;
* an alert dispatches **only** where a routing rule opted the farm in with a
  ``min_severity``, because ``AlertOpenedV1`` carries no action type and is also
  published by the grid anomaly sweep.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.events import AlertOpenedV1
from app.modules.recommendations.events import RecommendationOpenedV1
from app.modules.scouting.subscribers import register_subscribers
from app.shared.eventbus import get_default_bus
from tests.integration.scouting.conftest import ScoutingFixture

pytestmark = [pytest.mark.integration]


def _scout_rec(env: ScoutingFixture, **overrides: Any) -> RecommendationOpenedV1:
    defaults: dict[str, Any] = {
        "recommendation_id": uuid4(),
        "block_id": UUID(env.block_id),
        "farm_id": UUID(env.farm_id),
        "tree_id": uuid4(),
        "tree_code": "scout_for_stress_v1",
        "tree_version": 1,
        "action_type": "scout",
        "severity": "critical",
        "confidence": Decimal("0.85"),
        "created_at": datetime.now(UTC),
        "tenant_schema": env.schema,
        "text_en": "Severe NDVI drop on this block.",
        "parameters": {"within_hours": 24, "priority": "high"},
    }
    return RecommendationOpenedV1(**{**defaults, **overrides})


def _alert(env: ScoutingFixture, severity: str = "critical") -> AlertOpenedV1:
    return AlertOpenedV1(
        alert_id=uuid4(),
        block_id=UUID(env.block_id),
        rule_code="tree:x:leaf",
        severity=severity,
        created_at=datetime.now(UTC),
        tenant_schema=env.schema,
        farm_id=UUID(env.farm_id),
        diagnosis_en="Soil salinity above threshold",
    )


async def _visits(session: AsyncSession, env: ScoutingFixture, origin: str) -> list[dict[str, Any]]:
    await session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, status, priority, severity, due_by, assigned_to, assigned_by, title "
                    "FROM scouting_visits WHERE origin = :o ORDER BY created_at"
                ),
                {"o": origin},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _add_rule(session: AsyncSession, env: ScoutingFixture, **cols: Any) -> None:
    await session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    keys = ", ".join(cols)
    vals = ", ".join(f":{k}" for k in cols)
    await session.execute(
        text(f"INSERT INTO scouting_routing_rules ({keys}) VALUES ({vals})"),
        cols,
    )
    await session.commit()


@pytest.mark.asyncio
async def test_scout_recommendation_creates_a_visit(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    register_subscribers(get_default_bus())

    get_default_bus().publish(_scout_rec(env))

    rows = await _visits(admin_session, env, "recommendation")
    assert len(rows) == 1
    visit = rows[0]
    assert visit["status"] == "queued"
    # Deadline and priority come off the tree leaf, not from a default.
    assert visit["priority"] == "high"
    hours = round((visit["due_by"] - datetime.now(UTC)).total_seconds() / 3600)
    assert hours == 24
    assert visit["title"].startswith("Severe NDVI drop")


@pytest.mark.asyncio
async def test_non_scout_and_per_cell_recommendations_are_ignored(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    register_subscribers(get_default_bus())
    bus = get_default_bus()

    bus.publish(_scout_rec(env, action_type="irrigate"))
    # A cell-scoped tree opens one recommendation per grid cell; dispatching
    # each would put dozens of visits on one scout for one block. The sweep's
    # block-level digest is what gets acted on instead.
    bus.publish(_scout_rec(env, cell_id=uuid4()))

    assert await _visits(admin_session, env, "recommendation") == []


@pytest.mark.asyncio
async def test_replaying_a_recommendation_does_not_duplicate(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The daily evaluator re-walks every tree; a persistent dip must not queue
    a new visit every morning."""
    env = scouting_env
    register_subscribers(get_default_bus())
    event = _scout_rec(env)

    get_default_bus().publish(event)
    get_default_bus().publish(event)

    assert len(await _visits(admin_session, env, "recommendation")) == 1


@pytest.mark.asyncio
async def test_alerts_do_not_dispatch_without_an_opt_in_rule(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    register_subscribers(get_default_bus())

    # No rule at all.
    get_default_bus().publish(_alert(env))
    assert await _visits(admin_session, env, "alert") == []

    # A rule exists but sets no severity floor — still opted out.
    await _add_rule(admin_session, env, farm_id=UUID(env.farm_id), mode="triage")
    get_default_bus().publish(_alert(env))
    assert await _visits(admin_session, env, "alert") == []


@pytest.mark.asyncio
async def test_alert_dispatch_respects_the_severity_floor(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    register_subscribers(get_default_bus())
    await _add_rule(
        admin_session, env, farm_id=UUID(env.farm_id), mode="triage", min_severity="critical"
    )

    get_default_bus().publish(_alert(env, severity="warning"))
    assert await _visits(admin_session, env, "alert") == []

    get_default_bus().publish(_alert(env, severity="critical"))
    rows = await _visits(admin_session, env, "alert")
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_auto_rule_assigns_and_degrades_without_an_assignee(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    register_subscribers(get_default_bus())
    await _add_rule(
        admin_session,
        env,
        farm_id=UUID(env.farm_id),
        mode="auto",
        default_assignee=env.scout_user_id,
    )

    get_default_bus().publish(_scout_rec(env))
    rows = await _visits(admin_session, env, "recommendation")
    assert len(rows) == 1
    assert rows[0]["status"] == "assigned"
    assert rows[0]["assigned_to"] == env.scout_user_id
    # A rule did this, not a person — the board reads that difference.
    assert rows[0]["assigned_by"] is None

    # Strip the assignee: `auto` with nobody to assign to must fall back to the
    # queue rather than drop the visit. A visit waiting is a nuisance; a visit
    # that silently never existed is a missed field problem.
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    await admin_session.execute(
        text("UPDATE scouting_routing_rules SET default_assignee = NULL, fallback_assignee = NULL")
    )
    await admin_session.commit()

    get_default_bus().publish(_scout_rec(env))
    rows = await _visits(admin_session, env, "recommendation")
    assert len(rows) == 2
    assert rows[1]["status"] == "queued"
    assert rows[1]["assigned_to"] is None
