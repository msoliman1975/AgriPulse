"""Aggregation and recurrence: tenant migration 0079.

Two behaviours, both of which only a real database can prove.

**Aggregation.** A cell-scoped tree that fires on N cells of one block must put
*one* row on the queue, not N. The mechanism is a group parent plus N children,
and the parts that can silently not work are all schema-level: the partial
unique that lets two parents of one tree coexist (they differ by leaf or
severity, and the pre-0079 predicate matched both as "open, no cell"), the
children being filtered out of the unified read, and the member count following
cells as they start and stop firing.

**Recurrence.** A re-fire against a still-open item used to write nothing at
all. Now it moves a per-day clock, and the arithmetic that matters — a second
sweep on the same morning is not a second day, a skipped day breaks the streak
— is expressed in SQL and cannot be checked anywhere but here.

One tenant schema for the module: creating a tenant replays every tenant
migration, and a schema per test is what pushed this job past its budget once
already.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.action_center.repository import ActionCenterRepository
from app.modules.action_center.service import ActionCenterServiceImpl
from app.modules.alerts.errors import GroupMemberNotActionableError
from app.modules.alerts.repository import AlertsRepository
from app.modules.alerts.service import AlertsServiceImpl
from app.modules.recommendations.errors import (
    GroupMemberNotActionableError as RecGroupMemberNotActionableError,
)
from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.recommendations.service import RecommendationsServiceImpl
from app.modules.tenancy.service import get_tenant_service
from app.shared.action_items import build_group_key, derive_recurrence, derive_spread
from app.shared.eventbus import EventBus

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"
_CELL_POLY = "POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))"

# Four cells is the smallest number that distinguishes "all cleared" from "some
# cleared" while still leaving two live — enough for a count to be wrong in a
# visible way rather than off by one.
_CELL_COUNT = 4


async def _seed(admin_session: Any) -> dict[str, Any]:
    """One farm, one block, four grid cells. Built once for the module."""
    if not _SHARED:
        slug = f"grp-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

        farm_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO farms (
                        code, name, country_code, boundary, boundary_utm,
                        centroid, area_m2
                    ) VALUES (
                        'GRP-FARM', 'Grouping farm', 'EG',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                        100000
                    ) RETURNING id
                    """
                ),
                {"poly": _POLY},
            )
        ).scalar_one()

        block_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO blocks (
                        farm_id, code, boundary, boundary_utm, centroid,
                        area_m2, aoi_hash
                    ) VALUES (
                        :farm_id, 'GB-01',
                        ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                        100000, 'grp-hash'
                    ) RETURNING id
                    """
                ),
                {"farm_id": farm_id, "poly": _POLY},
            )
        ).scalar_one()

        grid_config_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO grid_configs (block_id, product_id, cell_size_m, utm_srid)
                    VALUES (:block_id, gen_random_uuid(), 20, 32636)
                    RETURNING id
                    """
                ),
                {"block_id": block_id},
            )
        ).scalar_one()

        cells = [
            (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO grid_cells (
                            grid_config_id, row_idx, col_idx, geom, centroid, area_m2
                        ) VALUES (
                            :cfg, :row, 1,
                            ST_GeomFromText(:cell_poly, 4326),
                            ST_SetSRID(ST_MakePoint(31.205, 30.005), 4326),
                            400
                        ) RETURNING id
                        """
                    ),
                    {"cfg": grid_config_id, "row": idx, "cell_poly": _CELL_POLY},
                )
            ).scalar_one()
            for idx in range(_CELL_COUNT)
        ]

        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            farm_id=farm_id,
            block_id=block_id,
            cells=cells,
        )

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return _SHARED


def _repos(session: Any) -> tuple[RecommendationsRepository, AlertsRepository]:
    return (
        RecommendationsRepository(tenant_session=session, public_session=session),
        AlertsRepository(tenant_session=session, public_session=session),
    )


async def _insert_group(
    repo: RecommendationsRepository,
    *,
    seed: dict[str, Any],
    group_key: str,
    cells: list[UUID],
    today: date,
    severity: str = "warning",
    tree_id: UUID | None = None,
) -> tuple[UUID, list[UUID]]:
    """A parent plus one child per cell, exactly as the engine writes them."""
    tree_id = tree_id or uuid4()
    parent_id = uuid4()

    async def _write(row_id: UUID, cell_id: UUID | None, is_group: bool, parent: UUID | None):
        return await repo.insert_recommendation(
            recommendation_id=row_id,
            block_id=seed["block_id"],
            cell_id=cell_id,
            farm_id=seed["farm_id"],
            tree_id=tree_id,
            tree_code="grp_tree_v1",
            tree_version=1,
            block_crop_id=None,
            action_type="scout",
            severity=severity,
            parameters={},
            actions={},
            confidence=Decimal("0.9"),
            tree_path=[{"node_id": "leaf_a"}],
            text_en="Scout this area",
            text_ar=None,
            valid_until=None,
            evaluation_snapshot={},
            actor_user_id=None,
            group_key=group_key,
            group_parent_id=parent,
            is_group=is_group,
            today=today,
        )

    assert await _write(parent_id, None, True, None) is True
    children: list[UUID] = []
    for cell_id in cells:
        child_id = uuid4()
        assert await _write(child_id, cell_id, False, parent_id) is True
        children.append(child_id)
    await repo.refresh_member_count(parent_id=parent_id, today=today)
    return parent_id, children


@pytest.mark.asyncio
async def test_group_lists_as_one_row_and_members_drill_down(admin_session: Any) -> None:
    """Four firing cells, one card — and the four are still reachable.

    This is the whole complaint in one assertion: before 0079 the queue showed
    four rows saying the same sentence about the same block.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    today = date(2026, 8, 10)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_a", action_type="scout", severity="warning"
    )
    parent_id, children = await _insert_group(
        repo, seed=seed, group_key=key, cells=seed["cells"], today=today
    )
    await admin_session.commit()

    ac = ActionCenterRepository(tenant_session=admin_session)
    rows = await ac.list_items(farm_id=seed["farm_id"])
    listed = [r for r in rows if r["id"] == parent_id]
    assert len(listed) == 1
    assert listed[0]["is_group"] is True
    assert listed[0]["member_count"] == _CELL_COUNT
    # The children exist but are not on the board.
    assert not [r for r in rows if r["id"] in set(children)]

    members = await ac.list_members(kind="recommendation", parent_id=parent_id)
    assert {m["id"] for m in members} == set(children)
    # Every member carries its own cell, which is what the map colours.
    assert all(m["cell_id"] is not None for m in members)
    assert all(m["cleared_at"] is None for m in members)


@pytest.mark.asyncio
async def test_two_severities_of_one_tree_are_two_groups(admin_session: Any) -> None:
    """The index change is load-bearing, not cosmetic.

    Both parents are (state='open', cell_id IS NULL) for the same tree, which
    is exactly what `uq_recommendations_block_tree_open` matched before its
    predicate gained `is_group = FALSE`. Without that change the second insert
    is rejected and the warning-severity cells silently join the critical card.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    today = date(2026, 8, 11)
    tree_id = uuid4()
    warn_key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_b", action_type="spray", severity="warning"
    )
    crit_key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_b", action_type="spray", severity="critical"
    )
    warn_parent, _ = await _insert_group(
        repo,
        seed=seed,
        group_key=warn_key,
        cells=seed["cells"][:2],
        today=today,
        severity="warning",
        tree_id=tree_id,
    )
    crit_parent, _ = await _insert_group(
        repo,
        seed=seed,
        group_key=crit_key,
        cells=[],
        today=today,
        severity="critical",
        tree_id=tree_id,
    )
    await admin_session.commit()

    assert warn_parent != crit_parent
    ac = ActionCenterRepository(tenant_session=admin_session)
    ids = {r["id"] for r in await ac.list_items(farm_id=seed["farm_id"])}
    assert {warn_parent, crit_parent} <= ids


@pytest.mark.asyncio
async def test_same_key_twice_reuses_the_parent(admin_session: Any) -> None:
    """A second attempt at the same group is refused, not duplicated."""
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_dup", action_type="prune", severity="info"
    )
    parent_id, _ = await _insert_group(
        repo, seed=seed, group_key=key, cells=[], today=date(2026, 8, 12), severity="info"
    )
    found = await repo.find_open_group_parent(block_id=seed["block_id"], group_key=key)
    assert found == parent_id
    await admin_session.commit()


@pytest.mark.asyncio
async def test_recurrence_counts_days_not_evaluations(admin_session: Any) -> None:
    """Twice in one morning is one day. A skipped day breaks the streak.

    Both halves are SQL `CASE` arithmetic, so a Python-level test of the same
    intent would prove nothing about what actually runs.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    day1 = date(2026, 8, 13)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_rec", action_type="irrigate", severity="info"
    )
    parent_id, _ = await _insert_group(
        repo, seed=seed, group_key=key, cells=[], today=day1, severity="info"
    )

    # A second sweep on the same day must not read as a second day.
    again = await repo.bump_recurrence(row_id=parent_id, today=day1, actor_user_id=None)
    assert (again["occurrence_count"], again["day_streak"]) == (1, 1)

    day2 = await repo.bump_recurrence(
        row_id=parent_id, today=day1 + timedelta(days=1), actor_user_id=None
    )
    assert (day2["occurrence_count"], day2["day_streak"]) == (2, 2)

    day3 = await repo.bump_recurrence(
        row_id=parent_id, today=day1 + timedelta(days=2), actor_user_id=None
    )
    assert (day3["occurrence_count"], day3["day_streak"]) == (3, 3)

    # Skip a day: it fired again, but not consecutively.
    later = await repo.bump_recurrence(
        row_id=parent_id, today=day1 + timedelta(days=4), actor_user_id=None
    )
    assert later["occurrence_count"] == 4
    assert later["day_streak"] == 1
    await admin_session.commit()


@pytest.mark.asyncio
async def test_cells_that_stop_firing_are_cleared_and_uncounted(admin_session: Any) -> None:
    """A shrinking outbreak has to look like one.

    The clearing pass runs per (block, tree) after the sweep rather than per
    firing, because the interesting cells are the ones the sweep never reached.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    tree_id = uuid4()
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_clear", action_type="scout", severity="warning"
    )
    parent_id, children = await _insert_group(
        repo,
        seed=seed,
        group_key=key,
        cells=seed["cells"],
        today=date(2026, 8, 14),
        tree_id=tree_id,
    )
    assert (
        await repo.refresh_member_count(parent_id=parent_id, today=date(2026, 8, 14)) == _CELL_COUNT
    )

    # Next day only the first two cells fire.
    still_firing = children[:2]
    touched = await repo.clear_stale_children(
        block_id=seed["block_id"], tree_id=tree_id, fired_ids=list(still_firing)
    )
    assert parent_id in set(touched)
    assert await repo.refresh_member_count(parent_id=parent_id, today=date(2026, 8, 15)) == 2

    members = await repo.list_group_members(parent_id=parent_id)
    cleared = {m["id"] for m in members if m["cleared_at"] is not None}
    assert cleared == set(children[2:])
    # Cleared members stay attached — that is the history.
    assert len(members) == _CELL_COUNT
    await admin_session.commit()


@pytest.mark.asyncio
async def test_a_tree_that_fires_nowhere_still_retires_yesterdays_cells(
    admin_session: Any,
) -> None:
    """The zero case: nothing fired, so nothing is in the fired list.

    A loop over results cannot reach this, which is why the clearing pass is
    driven by the tree rather than by what it produced.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    tree_id = uuid4()
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_quiet", action_type="scout", severity="info"
    )
    parent_id, _ = await _insert_group(
        repo,
        seed=seed,
        group_key=key,
        cells=seed["cells"][:3],
        today=date(2026, 8, 15),
        severity="info",
        tree_id=tree_id,
    )
    assert await repo.refresh_member_count(parent_id=parent_id, today=date(2026, 8, 15)) == 3

    await repo.clear_stale_children(block_id=seed["block_id"], tree_id=tree_id, fired_ids=[])
    await repo.refresh_member_counts_for_tree(
        block_id=seed["block_id"], tree_id=tree_id, today=date(2026, 8, 16)
    )

    count = (
        await admin_session.execute(
            text("SELECT member_count FROM recommendations WHERE id = :i"),
            {"i": parent_id},
        )
    ).scalar_one()
    assert count == 0
    await admin_session.commit()


@pytest.mark.asyncio
async def test_acting_on_the_group_carries_every_cell_with_it(admin_session: Any) -> None:
    """Applying the card must not leave four open rows underneath it.

    A member left `open` under an applied parent keeps that cell's dedup key
    occupied, so the next genuine firing there is swallowed as a duplicate —
    a silent failure with no error anywhere.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_apply", action_type="spray", severity="warning"
    )
    parent_id, children = await _insert_group(
        repo, seed=seed, group_key=key, cells=seed["cells"], today=date(2026, 8, 16)
    )
    await admin_session.commit()

    service = RecommendationsServiceImpl(
        tenant_session=admin_session,
        public_session=admin_session,
        event_bus=EventBus(),
    )
    after = await service.transition_recommendation(
        recommendation_id=parent_id,
        action="apply",
        dismissal_reason=None,
        deferred_until=None,
        outcome_notes=None,
        actor_user_id=None,
        tenant_schema=_SHARED["schema"],
    )
    assert after["state"] == "applied"

    states = (
        (
            await admin_session.execute(
                text("SELECT DISTINCT state FROM recommendations WHERE id = ANY(:ids)"),
                {"ids": children},
            )
        )
        .scalars()
        .all()
    )
    assert set(states) == {"applied"}
    await admin_session.commit()


@pytest.mark.asyncio
async def test_a_member_cannot_be_acted_on_alone(admin_session: Any) -> None:
    """The refusal names the parent, so a stale client can retry correctly."""
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_guard", action_type="scout", severity="info"
    )
    parent_id, children = await _insert_group(
        repo,
        seed=seed,
        group_key=key,
        cells=seed["cells"][:1],
        today=date(2026, 8, 17),
        severity="info",
    )
    await admin_session.commit()

    service = RecommendationsServiceImpl(
        tenant_session=admin_session,
        public_session=admin_session,
        event_bus=EventBus(),
    )
    with pytest.raises(RecGroupMemberNotActionableError) as excinfo:
        await service.transition_recommendation(
            recommendation_id=children[0],
            action="dismiss",
            dismissal_reason="nope",
            deferred_until=None,
            outcome_notes=None,
            actor_user_id=None,
            tenant_schema=_SHARED["schema"],
        )
    assert excinfo.value.extras["group_parent_id"] == str(parent_id)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_alert_groups_behave_the_same(admin_session: Any) -> None:
    """The alerts half of the mechanism, end to end.

    Alerts are the side where the pre-0079 dedup smuggled the cell uuid into
    `rule_code`. The parent now holds the plain code and the children keep the
    suffix — so the parent is listable, the children are not, and resolving the
    parent closes them.
    """
    seed = await _seed(admin_session)
    _, alerts = _repos(admin_session)
    today = date(2026, 8, 18)
    key = build_group_key(
        tree_code="grp_alert_v1",
        leaf_node_id="leaf_hot",
        action_type="irrigate",
        severity="critical",
    )
    parent_id = uuid4()
    assert await alerts.insert_alert(
        alert_id=parent_id,
        block_id=seed["block_id"],
        cell_id=None,
        rule_code="tree:grp_alert_v1:leaf_hot",
        severity="critical",
        action_type="irrigate",
        diagnosis_en="Soil moisture below wilting point",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot={},
        actor_user_id=None,
        group_key=key,
        group_parent_id=None,
        is_group=True,
        today=today,
    )
    child_ids = []
    for cell_id in seed["cells"][:3]:
        child_id = uuid4()
        assert await alerts.insert_alert(
            alert_id=child_id,
            block_id=seed["block_id"],
            cell_id=cell_id,
            rule_code=f"tree:grp_alert_v1:leaf_hot:cell:{cell_id}",
            severity="critical",
            action_type="irrigate",
            diagnosis_en="Soil moisture below wilting point",
            diagnosis_ar=None,
            prescription_en=None,
            prescription_ar=None,
            prescription_activity_id=None,
            signal_snapshot={},
            actor_user_id=None,
            group_key=key,
            group_parent_id=parent_id,
            is_group=False,
            today=today,
        )
        child_ids.append(child_id)
    assert await alerts.refresh_member_count(parent_id=parent_id, today=today) == 3
    await admin_session.commit()

    ac = ActionCenterRepository(tenant_session=admin_session)
    rows = await ac.list_items(farm_id=seed["farm_id"])
    assert [r for r in rows if r["id"] == parent_id]
    assert not [r for r in rows if r["id"] in set(child_ids)]

    service = AlertsServiceImpl(
        tenant_session=admin_session,
        public_session=admin_session,
        event_bus=EventBus(),
    )
    await service.transition_alert(
        alert_id=parent_id,
        action="resolve",
        snooze_until=None,
        actor_user_id=None,
        tenant_schema=_SHARED["schema"],
    )
    statuses = (
        (
            await admin_session.execute(
                text("SELECT DISTINCT status FROM alerts WHERE id = ANY(:ids)"),
                {"ids": child_ids},
            )
        )
        .scalars()
        .all()
    )
    assert set(statuses) == {"resolved"}

    with pytest.raises(GroupMemberNotActionableError):
        await service.transition_alert(
            alert_id=child_ids[0],
            action="acknowledge",
            snooze_until=None,
            actor_user_id=None,
            tenant_schema=_SHARED["schema"],
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_action_item_carries_aggregation_and_recurrence(admin_session: Any) -> None:
    """What the screen actually receives.

    The counters are useless if they stop at the repository — the badge, the
    cell count and the "N days running" line all read off the serialised item.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    day1 = date(2026, 8, 19)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_api", action_type="scout", severity="critical"
    )
    parent_id, _ = await _insert_group(
        repo,
        seed=seed,
        group_key=key,
        cells=seed["cells"][:2],
        today=day1,
        severity="critical",
    )
    for offset in range(1, 6):
        await repo.bump_recurrence(
            row_id=parent_id, today=day1 + timedelta(days=offset), actor_user_id=None
        )
    await admin_session.commit()

    service = ActionCenterServiceImpl(tenant_session=admin_session)
    response = await service.list_items(farm_id=seed["farm_id"], group_by="none")
    item = next(i for g in response.groups for i in g.items if i.id == parent_id)

    assert item.aggregation.is_group is True
    assert item.aggregation.member_count == 2
    assert item.recurrence.day_streak == 6
    assert item.recurrence.occurrence_count == 6
    # Six consecutive mornings with nobody acting is the escalated reading.
    assert item.recurrence.state == "persistent"
    assert item.recurrence.first_seen_at is not None

    members = await service.list_members(farm_id=seed["farm_id"], item_id=parent_id)
    assert members is not None
    assert members.total == 2
    assert members.active == 2
    assert members.kind == "recommendation"


def test_recurrence_never_escalates_past_recurring_once_somebody_acts() -> None:
    """Escalation is about neglect, not about persistence.

    A pure function, but the rule it encodes is the one most likely to be
    "simplified" later into `streak >= 5 → persistent`, which would badge every
    item somebody is actively treating as ignored.
    """
    assert derive_recurrence(day_streak=1, occurrence_count=1, acted=False) == "new"
    assert derive_recurrence(day_streak=2, occurrence_count=2, acted=False) == "recurring"
    assert derive_recurrence(day_streak=9, occurrence_count=9, acted=False) == "persistent"
    assert derive_recurrence(day_streak=9, occurrence_count=9, acted=True) == "recurring"
    # A gap in the run still counts as a repeat even though the streak reset.
    assert derive_recurrence(day_streak=1, occurrence_count=4, acted=False) == "recurring"


def test_group_key_is_the_documented_tuple() -> None:
    """The key is a contract: the migration's backfill builds the same string
    in SQL, and a change here that is not mirrored there would fork a
    backfilled group away from the one the engine goes on writing."""
    assert (
        build_group_key(
            tree_code="mango_heat_v1",
            leaf_node_id="leaf_hot",
            action_type="irrigate",
            severity="critical",
        )
        == "mango_heat_v1:leaf_hot:irrigate:critical"
    )
    # A row whose path was never recorded still lands on a stable key.
    assert (
        build_group_key(tree_code="t", leaf_node_id=None, action_type=None, severity="info")
        == "t:leaf:unclassified:info"
    )


@pytest.mark.asyncio
async def test_a_cleared_cell_that_fires_again_rejoins_its_group(admin_session: Any) -> None:
    """`attach_child` is what stops a returning cell becoming an orphan.

    Its open row still occupies the per-cell dedup key, so the insert is
    refused; without the re-attach it would sit there `cleared`, invisible and
    uncounted, while the group under-reports the block.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    tree_id = uuid4()
    today = date(2026, 8, 20)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_return", action_type="scout", severity="warning"
    )
    parent_id, children = await _insert_group(
        repo, seed=seed, group_key=key, cells=seed["cells"][:2], today=today, tree_id=tree_id
    )
    await repo.clear_stale_children(
        block_id=seed["block_id"], tree_id=tree_id, fired_ids=[children[0]]
    )
    assert await repo.refresh_member_count(parent_id=parent_id, today=today) == 1

    await repo.attach_child(
        child_id=children[1],
        parent_id=parent_id,
        group_key=key,
        tree_version=1,
        text_en="Scout this area again",
        text_ar=None,
        evaluation_snapshot={"ndvi": 0.3},
        today=today + timedelta(days=1),
        actor_user_id=None,
    )
    assert (
        await repo.refresh_member_count(parent_id=parent_id, today=today + timedelta(days=1)) == 2
    )

    row = (
        (
            await admin_session.execute(
                text("SELECT cleared_at, text_en, day_streak FROM recommendations WHERE id = :i"),
                {"i": children[1]},
            )
        )
        .mappings()
        .one()
    )
    assert row["cleared_at"] is None
    assert row["text_en"] == "Scout this area again"
    # The cell's own clock moved too, not just the parent's.
    assert row["day_streak"] == 2
    await admin_session.commit()


@pytest.mark.asyncio
async def test_tenant_today_uses_the_tenant_timezone(admin_session: Any) -> None:
    """The streak boundary is the tenant's midnight, not the server's.

    An evening sweep in Cairo is tomorrow in UTC for two hours a day; taking
    the UTC date would split one run of consecutive days into two runs of one,
    every single night, for every tenant east of Greenwich.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    await admin_session.execute(
        text("UPDATE public.tenants SET default_timezone = 'Pacific/Kiritimati' WHERE id = :i"),
        {"i": (await _tenant_id(admin_session, seed))},
    )
    ahead = await repo.tenant_today(tenant_schema=_SHARED["schema"])
    await admin_session.execute(
        text("UPDATE public.tenants SET default_timezone = 'Pacific/Midway' WHERE id = :i"),
        {"i": (await _tenant_id(admin_session, seed))},
    )
    behind = await repo.tenant_today(tenant_schema=_SHARED["schema"])
    # +14 and -11 are 25 hours apart, so the two never agree on the date.
    assert ahead != behind
    assert (ahead - behind) == timedelta(days=1)
    assert abs((ahead - datetime.now(UTC).date()).days) <= 1
    await admin_session.rollback()


async def _tenant_id(session: Any, seed: dict[str, Any]) -> UUID:
    return (
        await session.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :s"),
            {"s": _SHARED["schema"]},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_block_scoped_refire_finds_and_bumps_its_own_row(admin_session: Any) -> None:
    """The block-scoped recurrence path, including its bind parameters.

    `find_open_recommendation` builds its WHERE clause two ways, and the cell
    branch is the one that names `:c`. Declaring that bind unconditionally
    makes `bindparams()` raise for the block branch — the common one — so this
    exercises the shape that has 500'd this codebase before, not just the
    counter arithmetic.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    tree_id = uuid4()
    day1 = date(2026, 8, 21)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_blk", action_type="fertilize", severity="info"
    )

    async def _write(row_id: UUID) -> bool:
        return await repo.insert_recommendation(
            recommendation_id=row_id,
            block_id=seed["block_id"],
            cell_id=None,
            farm_id=seed["farm_id"],
            tree_id=tree_id,
            tree_code="grp_tree_v1",
            tree_version=1,
            block_crop_id=None,
            action_type="fertilize",
            severity="info",
            parameters={},
            actions={},
            confidence=Decimal("0.7"),
            tree_path=[{"node_id": "leaf_blk"}],
            text_en="Top-dress nitrogen",
            text_ar=None,
            valid_until=None,
            evaluation_snapshot={},
            actor_user_id=None,
            group_key=key,
            group_parent_id=None,
            is_group=False,
            today=day1,
        )

    first = uuid4()
    assert await _write(first) is True
    # Tomorrow's sweep: same finding, still open. The index refuses it.
    assert await _write(uuid4()) is False

    found = await repo.find_open_recommendation(
        block_id=seed["block_id"], tree_id=tree_id, cell_id=None
    )
    assert found == first
    bumped = await repo.bump_recurrence(
        row_id=found, today=day1 + timedelta(days=1), actor_user_id=None
    )
    assert (bumped["occurrence_count"], bumped["day_streak"]) == (2, 2)
    await admin_session.commit()


@pytest.mark.asyncio
async def test_the_day_over_day_baseline_moves_once_a_day(admin_session: Any) -> None:
    """Aggregation must not hide the thing it summarises.

    With only a current count on the card, a 12-cell finding and a 20-cell one
    render identically. The baseline is what makes the difference visible — and
    it has to move exactly once per tenant-day, because a sweep runs several
    times a morning and a baseline that moved with it would decay to "same as
    five minutes ago" and never show a trend at all.
    """
    seed = await _seed(admin_session)
    repo, _ = _repos(admin_session)
    tree_id = uuid4()
    day1 = date(2026, 8, 22)
    key = build_group_key(
        tree_code="grp_tree_v1", leaf_node_id="leaf_trend", action_type="spray", severity="warning"
    )
    # Day 1: two cells and no yesterday. The group reads as `unknown` — the
    # absence of a baseline, which must not be drawn as steadiness.
    parent_id, children = await _insert_group(
        repo, seed=seed, group_key=key, cells=seed["cells"][:2], today=day1, tree_id=tree_id
    )
    row = await _counts(admin_session, parent_id)
    assert (row["member_count"], row["previous_member_count"]) == (2, 0)
    assert (
        derive_spread(
            is_group=True,
            member_count=row["member_count"],
            previous_member_count=row["previous_member_count"],
        )
        == "unknown"
    )

    # A second sweep the same morning must not move the baseline. If it did,
    # the baseline would decay to "same as five minutes ago" and the group
    # would read as steady forever, however fast it was spreading.
    await repo.refresh_member_counts_for_tree(
        block_id=seed["block_id"], tree_id=tree_id, today=day1
    )
    row = await _counts(admin_session, parent_id)
    assert (row["member_count"], row["previous_member_count"]) == (2, 0)

    # Day 2: the outbreak reaches all four cells.
    day2 = day1 + timedelta(days=1)
    for cell_id in seed["cells"][2:]:
        child_id = uuid4()
        assert await repo.insert_recommendation(
            recommendation_id=child_id,
            block_id=seed["block_id"],
            cell_id=cell_id,
            farm_id=seed["farm_id"],
            tree_id=tree_id,
            tree_code="grp_tree_v1",
            tree_version=1,
            block_crop_id=None,
            action_type="spray",
            severity="warning",
            parameters={},
            actions={},
            confidence=Decimal("0.9"),
            tree_path=[{"node_id": "leaf_trend"}],
            text_en="Spray this area",
            text_ar=None,
            valid_until=None,
            evaluation_snapshot={},
            actor_user_id=None,
            group_key=key,
            group_parent_id=parent_id,
            is_group=False,
            today=day2,
        )
    await repo.refresh_member_counts_for_tree(
        block_id=seed["block_id"], tree_id=tree_id, today=day2
    )
    row = await _counts(admin_session, parent_id)
    assert (row["member_count"], row["previous_member_count"]) == (4, 2)
    assert (
        derive_spread(
            is_group=True,
            member_count=row["member_count"],
            previous_member_count=row["previous_member_count"],
        )
        == "spreading"
    )

    # Day 3: it collapses back to one cell.
    day3 = day2 + timedelta(days=1)
    await repo.clear_stale_children(
        block_id=seed["block_id"], tree_id=tree_id, fired_ids=[children[0]]
    )
    await repo.refresh_member_counts_for_tree(
        block_id=seed["block_id"], tree_id=tree_id, today=day3
    )
    row = await _counts(admin_session, parent_id)
    assert (row["member_count"], row["previous_member_count"]) == (1, 4)
    assert (
        derive_spread(
            is_group=True,
            member_count=row["member_count"],
            previous_member_count=row["previous_member_count"],
        )
        == "receding"
    )
    await admin_session.commit()


async def _counts(session: Any, parent_id: UUID) -> dict[str, Any]:
    return dict(
        (
            await session.execute(
                text(
                    "SELECT member_count, previous_member_count, last_counted_day "
                    "  FROM recommendations WHERE id = :i"
                ),
                {"i": parent_id},
            )
        )
        .mappings()
        .one()
    )


def test_a_single_cell_of_drift_is_not_a_trend() -> None:
    """The grid re-evaluates every morning against imagery that moves on its
    own. An arrow that flickers daily is an arrow people stop reading, so a
    move has to clear both an absolute and a relative floor."""
    assert derive_spread(is_group=True, member_count=13, previous_member_count=12) == "steady"
    assert derive_spread(is_group=True, member_count=20, previous_member_count=12) == "spreading"
    assert derive_spread(is_group=True, member_count=4, previous_member_count=14) == "receding"
    # A big relative move that is only one cell is still noise.
    assert derive_spread(is_group=True, member_count=2, previous_member_count=1) == "steady"
    # No baseline is not steadiness.
    assert derive_spread(is_group=True, member_count=9, previous_member_count=0) == "unknown"
    # A block-scoped item has no cells to spread across.
    assert derive_spread(is_group=False, member_count=0, previous_member_count=0) == "unknown"
