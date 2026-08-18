"""Migration 0079's backfill, run against rows that actually exist.

Every test run exercises 0079's *create* side, because every tenant schema
replays it — against empty tables. The backfill is the half that only matters
when there is a backlog, which is precisely the situation on the production
tenant this change was written for: a smoke test left cell-scoped rows in the
queue, and the migration is supposed to collapse them on deploy rather than
leave them to be closed by hand.

So this goes down to 0078, seeds the pre-migration shape, and comes back up.

Three things it can get wrong and nothing else would catch:

* The key. The backfill rebuilds `group_key` in SQL — `tree_path -> -1 ->>
  'node_id'` for a recommendation, `split_part(rule_code, ':', 3)` for an
  alert — while the engine builds it in Python. If the two disagree, a
  backfilled group and the next morning's firing fork into two cards for one
  finding, forever, with no error.
* The order of operations. The parents it inserts are `state='open'` with
  `cell_id IS NULL`, which is exactly what the OLD
  `uq_recommendations_block_tree_open` predicate matched. Inserting them before
  that index is re-created would fail on the second group of any tree.
* The blast radius. Applied, dismissed and resolved rows are supposed to be
  left byte-for-byte alone.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.modules.tenancy.service import get_tenant_service
from app.shared.action_items import build_group_key

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"
_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


def _alembic_cfg(schema: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    return cfg


async def _use_schema(session: Any, schema: str) -> None:
    await session.execute(text(f'SET search_path TO "{schema}", public'))


async def _seed_farm_block_cells(session: Any) -> tuple[UUID, UUID, list[UUID]]:
    farm_id = (
        await session.execute(
            text(
                """
                INSERT INTO farms (
                    code, name, country_code, boundary, boundary_utm, centroid, area_m2
                ) VALUES (
                    'MIG79', 'Backfill farm', 'EG',
                    ST_GeomFromText(:poly, 4326),
                    ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                    ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000
                ) RETURNING id
                """
            ),
            {"poly": _POLY},
        )
    ).scalar_one()
    block_id = (
        await session.execute(
            text(
                """
                INSERT INTO blocks (
                    farm_id, code, boundary, boundary_utm, centroid, area_m2, aoi_hash
                ) VALUES (
                    :farm_id, 'MB-01',
                    ST_GeomFromText(:poly, 4326),
                    ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                    ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000, 'mig79'
                ) RETURNING id
                """
            ),
            {"farm_id": farm_id, "poly": _POLY},
        )
    ).scalar_one()
    cfg_id = (
        await session.execute(
            text(
                "INSERT INTO grid_configs (block_id, product_id, cell_size_m, utm_srid) "
                "VALUES (:b, gen_random_uuid(), 20, 32636) RETURNING id"
            ),
            {"b": block_id},
        )
    ).scalar_one()
    cells = [
        (
            await session.execute(
                text(
                    """
                    INSERT INTO grid_cells (
                        grid_config_id, row_idx, col_idx, geom, centroid, area_m2
                    ) VALUES (
                        :cfg, :row, 1,
                        ST_GeomFromText(
                            'POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))',
                            4326
                        ),
                        ST_SetSRID(ST_MakePoint(31.205, 30.005), 4326), 400
                    ) RETURNING id
                    """
                ),
                {"cfg": cfg_id, "row": idx},
            )
        ).scalar_one()
        for idx in range(3)
    ]
    return farm_id, block_id, cells


@pytest.mark.asyncio
async def test_0079_collapses_the_open_cell_scoped_backlog(admin_session: Any) -> None:
    slug = f"mig79-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    schema = str(tenant.schema_name)

    cfg = _alembic_cfg(schema)
    command.downgrade(cfg, "0078")

    await _use_schema(admin_session, schema)
    farm_id, block_id, cells = await _seed_farm_block_cells(admin_session)
    tree_id = uuid4()

    # The pre-0079 shape: one open row per cell, all from the same leaf. Two
    # leaves so the test also proves two groups can coexist for one tree —
    # the case the old unique index would have rejected.
    for cell_id, leaf in zip(cells, ("leaf_a", "leaf_a", "leaf_b"), strict=True):
        await admin_session.execute(
            text(
                """
                INSERT INTO recommendations (
                    block_id, farm_id, cell_id, tree_id, tree_code, tree_version,
                    action_type, severity, parameters, confidence, tree_path,
                    evaluation_snapshot, text_en, state
                ) VALUES (
                    :block_id, :farm_id, :cell_id, :tree_id, 'mig_tree_v1', 1,
                    'scout', 'warning', '{}'::jsonb, 0.8,
                    CAST(:path AS jsonb), '{}'::jsonb, 'Scout this zone', 'open'
                )
                """
            ),
            {
                "block_id": block_id,
                "farm_id": farm_id,
                "cell_id": cell_id,
                "tree_id": tree_id,
                "path": f'[{{"node_id":"root"}},{{"node_id":"{leaf}"}}]',
            },
        )

    # A row that is already closed. It must come out the other side untouched:
    # the migration's contract is that it groups the live backlog and does not
    # rewrite anybody's history.
    closed_id = (
        await admin_session.execute(
            text(
                """
                INSERT INTO recommendations (
                    block_id, farm_id, cell_id, tree_id, tree_code, tree_version,
                    action_type, severity, parameters, confidence, tree_path,
                    evaluation_snapshot, text_en, state, dismissed_at
                ) VALUES (
                    :block_id, :farm_id, :cell_id, :tree_id, 'mig_tree_v1', 1,
                    'scout', 'warning', '{}'::jsonb, 0.8,
                    '[{"node_id":"leaf_a"}]'::jsonb, '{}'::jsonb, 'Old', 'dismissed',
                    now()
                ) RETURNING id
                """
            ),
            {
                "block_id": block_id,
                "farm_id": farm_id,
                "cell_id": cells[0],
                "tree_id": tree_id,
            },
        )
    ).scalar_one()

    # Two cell-scoped alerts from one leaf, in the pre-0079 rule_code shape
    # with the cell uuid smuggled into it.
    for cell_id in cells[:2]:
        await admin_session.execute(
            text(
                """
                INSERT INTO alerts (
                    block_id, cell_id, rule_code, severity, action_type, status,
                    diagnosis_en
                ) VALUES (
                    :block_id, :cell_id,
                    'tree:mig_alert_v1:leaf_hot:cell:' || :cell_text,
                    'critical', 'irrigate', 'open', 'Too hot'
                )
                """
            ),
            {"block_id": block_id, "cell_id": cell_id, "cell_text": str(cell_id)},
        )
    await admin_session.commit()

    command.upgrade(cfg, "0079")
    await _use_schema(admin_session, schema)

    # --- recommendations ---------------------------------------------------
    parents = (
        (
            await admin_session.execute(
                text(
                    "SELECT group_key, member_count, occurrence_count, day_streak, "
                    "       first_seen_at, cell_id "
                    "  FROM recommendations WHERE is_group = TRUE ORDER BY group_key"
                )
            )
        )
        .mappings()
        .all()
    )
    # Two leaves, two groups — and the old index would have allowed only one.
    assert [p["group_key"] for p in parents] == [
        build_group_key(
            tree_code="mig_tree_v1",
            leaf_node_id="leaf_a",
            action_type="scout",
            severity="warning",
        ),
        build_group_key(
            tree_code="mig_tree_v1",
            leaf_node_id="leaf_b",
            action_type="scout",
            severity="warning",
        ),
    ]
    assert [p["member_count"] for p in parents] == [2, 1]
    # A parent spans cells rather than sitting in one.
    assert all(p["cell_id"] is None for p in parents)
    assert all(p["first_seen_at"] is not None for p in parents)
    # No per-day history existed to derive a truer count from, and inventing
    # one would be worse than under-reporting.
    assert all(p["occurrence_count"] == 1 and p["day_streak"] == 1 for p in parents)

    orphans = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM recommendations "
                " WHERE state = 'open' AND cell_id IS NOT NULL AND group_parent_id IS NULL"
            )
        )
    ).scalar_one()
    assert orphans == 0

    closed = (
        (
            await admin_session.execute(
                text("SELECT group_parent_id, group_key, state FROM recommendations WHERE id = :i"),
                {"i": closed_id},
            )
        )
        .mappings()
        .one()
    )
    assert closed["state"] == "dismissed"
    assert closed["group_parent_id"] is None
    assert closed["group_key"] is None

    # --- alerts ------------------------------------------------------------
    alert_parent = (
        (
            await admin_session.execute(
                text(
                    "SELECT id, group_key, rule_code, member_count "
                    "  FROM alerts WHERE is_group = TRUE"
                )
            )
        )
        .mappings()
        .one()
    )
    assert alert_parent["group_key"] == build_group_key(
        tree_code="mig_alert_v1",
        leaf_node_id="leaf_hot",
        action_type="irrigate",
        severity="critical",
    )
    # The parent holds the un-suffixed code — the shape the Action Center
    # splits provenance out of. The children keep their `:cell:<uuid>` tail,
    # which is what still gives each cell its own idempotency.
    assert alert_parent["rule_code"] == "tree:mig_alert_v1:leaf_hot"
    assert alert_parent["member_count"] == 2

    attached = (
        await admin_session.execute(
            text("SELECT count(*) FROM alerts WHERE group_parent_id = :p"),
            {"p": alert_parent["id"]},
        )
    ).scalar_one()
    assert attached == 2

    # --- the shape the engine will go on writing ---------------------------
    # Re-running the backfill's own predicate must now find nothing: if the
    # key the migration built disagreed with the key the engine builds, the
    # next firing would open a second parent beside this one.
    await admin_session.commit()
