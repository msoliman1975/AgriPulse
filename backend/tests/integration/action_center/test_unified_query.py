"""The unified recommendations+alerts query must actually execute.

This file exists because of a specific failure mode this codebase has hit
before: a ``text()`` statement whose ``bindparams()`` are declared out of
lock-step with the WHERE clauses it actually built raises ``ArgumentError``
for any parameter the statement never mentions. Every call that omits a
filter then 500s, and a test that sets all filters at once sails past it.

So every filter is exercised alone, and none at all.

The second reason is the UNION itself. Postgres will not union two SELECTs
whose column types differ, and the two sides here are genuinely asymmetric —
alerts have no ``farm_id``, no ``valid_until``, no ``tree_version``, and reach
their farm only through ``blocks``. A NULL literal on one side against a real
column on the other unions as ``text`` and breaks at read time, not at parse
time. Only a real database catches that.

**One tenant schema for the module.** Creating a tenant replays every tenant
migration; a schema per test is what pushed the integration job past its
budget once already.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.action_center.repository import ActionCenterRepository
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_SHARED: dict[str, Any] = {}

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


async def _seed(admin_session: Any) -> tuple[ActionCenterRepository, dict[str, Any]]:
    """One farm, two blocks, one grid cell, and four items across both tables."""
    if not _SHARED:
        slug = f"ac-{uuid4().hex[:8]}"
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
                        'AC-FARM', 'AC farm', 'EG',
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

        member_id = uuid4()
        blocks: dict[str, UUID] = {}
        for code, responsible in (("B-01", member_id), ("B-02", None)):
            blocks[code] = (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO blocks (
                            farm_id, code, boundary, boundary_utm, centroid,
                            area_m2, aoi_hash, agronomist_membership_id
                        ) VALUES (
                            :farm_id, :code,
                            ST_GeomFromText(:poly, 4326),
                            ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                            ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                            100000, :aoi_hash, :responsible
                        ) RETURNING id
                        """
                    ),
                    {
                        "farm_id": farm_id,
                        "code": code,
                        "poly": _POLY,
                        "aoi_hash": f"hash-{code}",
                        "responsible": responsible,
                    },
                )
            ).scalar_one()

        # A grid config + one cell, so the cell-geometry join has something to
        # find and the coordinate columns are exercised for real.
        grid_config_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO grid_configs (block_id, product_id, cell_size_m, utm_srid)
                    VALUES (:block_id, gen_random_uuid(), 20, 32636)
                    RETURNING id
                    """
                ),
                {"block_id": blocks["B-01"]},
            )
        ).scalar_one()
        cell_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO grid_cells (
                        grid_config_id, row_idx, col_idx, geom, centroid, area_m2
                    ) VALUES (
                        :cfg, 2, 3,
                        ST_GeomFromText(
                            'POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))',
                            4326
                        ),
                        ST_SetSRID(ST_MakePoint(31.23578, 30.04421), 4326),
                        400
                    ) RETURNING id
                    """
                ),
                {"cfg": grid_config_id},
            )
        ).scalar_one()

        now = datetime.now(UTC)
        # 1) block-scoped recommendation, open
        rec_block = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO recommendations (
                        block_id, farm_id, tree_id, tree_code, tree_version,
                        action_type, severity, parameters, confidence, tree_path,
                        evaluation_snapshot, text_en, state, valid_until, actions
                    ) VALUES (
                        :block_id, :farm_id, gen_random_uuid(), 'ac_demo_v1', 1,
                        'spray', 'warning', '{}'::jsonb, 0.80,
                        '[{"node_id":"n1","condition_snapshot":
                           {"left": "rh_max", "op": ">", "right": 80, "observed": 86}}]'::jsonb,
                        '{}'::jsonb, 'Preventive spray', 'open', :valid_until,
                        '{"short_term":[{"text_en":"spray within the week"}]}'::jsonb
                    ) RETURNING id
                    """
                ),
                {
                    "block_id": blocks["B-01"],
                    "farm_id": farm_id,
                    "valid_until": now + timedelta(days=3),
                },
            )
        ).scalar_one()
        # 2) cell-scoped recommendation, open
        rec_cell = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO recommendations (
                        block_id, farm_id, cell_id, tree_id, tree_code, tree_version,
                        action_type, severity, parameters, confidence, tree_path,
                        evaluation_snapshot, text_en, state
                    ) VALUES (
                        :block_id, :farm_id, :cell_id, gen_random_uuid(),
                        'ac_cell_v1', 2, 'scout', 'critical', '{}'::jsonb, 0.82,
                        '[]'::jsonb, '{}'::jsonb, 'Scout this zone', 'open'
                    ) RETURNING id
                    """
                ),
                {"block_id": blocks["B-01"], "farm_id": farm_id, "cell_id": cell_id},
            )
        ).scalar_one()
        # 3) tree-sourced alert carrying an action_type (post-0063)
        alert_tree = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO alerts (
                        block_id, rule_code, action_type, severity, status,
                        diagnosis_en, signal_snapshot
                    ) VALUES (
                        :block_id, 'tree:ac_alert_v1:leaf_hot', 'irrigate',
                        'critical', 'open', 'Soil moisture below wilting point',
                        '{"soil_moisture": 8.1}'::jsonb
                    ) RETURNING id
                    """
                ),
                {"block_id": blocks["B-02"]},
            )
        ).scalar_one()
        # 4) legacy alert: no action_type, non-tree rule_code
        alert_legacy = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO alerts (block_id, rule_code, severity, status, diagnosis_en)
                    VALUES (:block_id, 'legacy_rule_42', 'info', 'resolved', 'Old alert')
                    RETURNING id
                    """
                ),
                {"block_id": blocks["B-02"]},
            )
        ).scalar_one()

        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            farm_id=farm_id,
            blocks=blocks,
            cell_id=cell_id,
            member_id=member_id,
            rec_block=rec_block,
            rec_cell=rec_cell,
            alert_tree=alert_tree,
            alert_legacy=alert_legacy,
        )

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return ActionCenterRepository(tenant_session=admin_session), _SHARED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_name",
    [
        "none",
        "kinds",
        "block_id",
        "action_types",
        "severities",
        "assigned_membership_id",
        "raised_from",
        "raised_to",
        "all",
    ],
)
async def test_every_filter_executes(admin_session: Any, filter_name: str) -> None:
    """Each filter alone, and all together. A bindparam declared out of
    lock-step with its clause raises before a single row is read."""
    repo, seeded = await _seed(admin_session)
    kwargs: dict[str, Any] = {"farm_id": seeded["farm_id"]}
    if filter_name in ("kinds", "all"):
        kwargs["kinds"] = ("recommendation",)
    if filter_name in ("block_id", "all"):
        kwargs["block_id"] = seeded["blocks"]["B-01"]
    if filter_name in ("action_types", "all"):
        kwargs["action_types"] = ("spray", "scout")
    if filter_name in ("severities", "all"):
        kwargs["severities"] = ("critical", "warning")
    if filter_name in ("assigned_membership_id", "all"):
        kwargs["assigned_membership_id"] = uuid4()
    if filter_name in ("raised_from", "all"):
        kwargs["raised_from"] = datetime.now(UTC) - timedelta(days=30)
    if filter_name in ("raised_to", "all"):
        kwargs["raised_to"] = datetime.now(UTC) + timedelta(days=1)

    rows = await repo.list_items(**kwargs)
    assert isinstance(rows, tuple)


@pytest.mark.asyncio
async def test_the_union_returns_both_kinds_for_the_farm(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    ids = {r["id"] for r in rows}
    assert seeded["rec_block"] in ids
    assert seeded["rec_cell"] in ids
    assert seeded["alert_tree"] in ids
    assert seeded["alert_legacy"] in ids
    assert {r["kind"] for r in rows} == {"recommendation", "alert"}


@pytest.mark.asyncio
async def test_an_alert_reaches_its_farm_through_its_block(admin_session: Any) -> None:
    """alerts has no farm_id column — the blocks join is the only way the row
    is farm-scoped, and getting it wrong leaks another farm's alerts."""
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    alert = next(r for r in rows if r["id"] == seeded["alert_tree"])
    assert alert["farm_id"] == seeded["farm_id"]
    assert alert["block_code"] == "B-02"


@pytest.mark.asyncio
async def test_a_foreign_farm_sees_none_of_it(admin_session: Any) -> None:
    repo, _ = await _seed(admin_session)
    assert await repo.list_items(farm_id=uuid4()) == ()


@pytest.mark.asyncio
async def test_cell_coordinates_come_back_as_real_numbers(admin_session: Any) -> None:
    """The whole point of the redesign: a cell-scoped item must carry a
    centroid, not just a row/col zone code."""
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    cell_row = next(r for r in rows if r["id"] == seeded["rec_cell"])
    assert cell_row["cell_id"] == seeded["cell_id"]
    assert (cell_row["row_idx"], cell_row["col_idx"]) == (2, 3)
    assert round(float(cell_row["lat"]), 5) == 30.04421
    assert round(float(cell_row["lon"]), 5) == 31.23578
    assert cell_row["ordinal"] == 1
    assert cell_row["total"] == 1


@pytest.mark.asyncio
async def test_a_block_scoped_item_has_no_cell_geometry(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    block_row = next(r for r in rows if r["id"] == seeded["rec_block"])
    assert block_row["cell_id"] is None
    assert block_row["lat"] is None


@pytest.mark.asyncio
async def test_tree_provenance_is_split_out_of_a_tree_rule_code(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    tree_alert = next(r for r in rows if r["id"] == seeded["alert_tree"])
    assert tree_alert["tree_code"] == "ac_alert_v1"
    legacy = next(r for r in rows if r["id"] == seeded["alert_legacy"])
    # A legacy rule alert has no tree; inventing one would be a lie in the UI.
    assert legacy["tree_code"] is None


@pytest.mark.asyncio
async def test_a_pre_0063_alert_keeps_a_null_action_type(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    legacy = next(r for r in rows if r["id"] == seeded["alert_legacy"])
    assert legacy["action_type"] is None
    tree_alert = next(r for r in rows if r["id"] == seeded["alert_tree"])
    assert tree_alert["action_type"] == "irrigate"


@pytest.mark.asyncio
async def test_action_type_filter_spans_both_tables(admin_session: Any) -> None:
    """The reason alerts.action_type had to exist at all."""
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"], action_types=("irrigate",))
    assert {r["id"] for r in rows} == {seeded["alert_tree"]}


@pytest.mark.asyncio
async def test_critical_sorts_first(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    assert rows[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_block_responsible_is_read_from_the_block(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    assert await repo.block_responsible(block_id=seeded["blocks"]["B-01"]) == seeded["member_id"]
    assert await repo.block_responsible(block_id=seeded["blocks"]["B-02"]) is None


@pytest.mark.asyncio
async def test_get_item_is_farm_scoped(admin_session: Any) -> None:
    repo, seeded = await _seed(admin_session)
    found = await repo.get_item(farm_id=seeded["farm_id"], item_id=seeded["rec_block"])
    assert found is not None
    assert await repo.get_item(farm_id=uuid4(), item_id=seeded["rec_block"]) is None


@pytest.mark.asyncio
async def test_every_item_carries_its_blocks_responsible_member(admin_session: Any) -> None:
    """The dispatch dialog defaults from this, for a SINGLE item.

    It was originally exposed only on the group — so the default worked when
    the queue happened to be grouped by block and silently failed everywhere
    else, which is exactly how it shipped.
    """
    repo, seeded = await _seed(admin_session)
    rows = await repo.list_items(farm_id=seeded["farm_id"])
    owned = next(r for r in rows if r["id"] == seeded["rec_block"])
    assert owned["responsible_membership_id"] == seeded["member_id"]
    # B-02 names nobody; NULL must survive rather than becoming a guess.
    unowned = next(r for r in rows if r["id"] == seeded["alert_tree"])
    assert unowned["responsible_membership_id"] is None
