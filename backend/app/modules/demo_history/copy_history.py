"""Copy one farm's observation history onto a build tenant's farm.

The backfill is the slow part of building a demo. A satellite pass has to
be fetched, cropped, reduced per block and per cell, and the provider
rations the requests, so two years of history for a farm takes days. When
the build farm has the same blocks as a farm that was already backfilled,
none of that has to happen again: the rows can be copied.

"The same blocks" is what makes it safe. A block's raster keys are built
from its AOI hash, which is the hash of its boundary, so a block with the
same boundary reads the same files in object storage. Only the database
rows are copied. Nothing in object storage is written, and the source
tenant is only ever read.

What is copied, per block matched by code:

* the grid: `grid_configs` and `grid_cells`, with new ids, when the target
  block has no grid of its own yet;
* `imagery_ingestion_jobs`, attached to the target block's subscription
  for the same product;
* `block_index_aggregates` and `block_grid_aggregates`: the index history
  per block and per cell, with the standard deviations stored on them;
* `block_index_baselines`, so z-scores are available from the first day.

And per farm: `weather_observations`, `weather_derived_daily`,
`weather_index_daily` and `weather_index_baselines`.

Engine outputs are not copied: no recommendations, alerts, verdicts, risk
rows or water balance. The replay writes those for the build farm.

Every insert skips rows the target already has, so a second run, or a run
over a farm the live sweep has already touched, adds only what is missing.
Columns come from `information_schema`, the same way the simulation clone
reads them, so a migration that adds a column does not break the copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.db.session import sanitize_tenant_schema

_log = get_logger(__name__)

AUDIT_EVENT = "demo_history.history_copied"

# Columns that name a person in the source tenant. A copied row must not
# claim that somebody from another organisation created it.
_PEOPLE_COLUMNS = frozenset({"created_by", "updated_by", "deleted_by"})

# Per-block history, in insert order. `remap` names the columns that hold
# an id of a copied or matched row.
_BLOCK_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("block_index_aggregates", ("block_id",)),
    ("block_grid_aggregates", ("block_id", "cell_id")),
    ("block_index_baselines", ("block_id",)),
)

_FARM_TABLES: tuple[str, ...] = (
    "weather_observations",
    "weather_derived_daily",
    "weather_index_daily",
    "weather_index_baselines",
)


@dataclass(frozen=True)
class CopySource:
    """Where the history comes from.

    `block_prefix` limits the copy to blocks whose code starts with it; an
    empty prefix copies every block the two farms have in common.
    """

    schema: str
    farm_code: str
    block_prefix: str = ""


async def _columns(session: AsyncSession, schema: str, table: str) -> list[str]:
    rows = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t AND is_generated = 'NEVER' "
            "ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    )
    return [r[0] for r in rows]


async def _farm_id(session: AsyncSession, schema: str, code: str) -> UUID:
    sql = f'SELECT id FROM "{schema}".farms WHERE code = :c AND deleted_at IS NULL'  # noqa: S608
    found = (await session.execute(text(sql), {"c": code})).scalar_one_or_none()
    if found is None:
        raise ValueError(f"no live farm {code!r} in {schema}")
    return UUID(str(found))


async def _blocks(
    session: AsyncSession, schema: str, farm_id: UUID, prefix: str
) -> dict[str, UUID]:
    rows = await session.execute(
        text(
            f'SELECT code, id FROM "{schema}".blocks '  # noqa: S608
            "WHERE farm_id = :f AND deleted_at IS NULL AND code LIKE :p"
        ).bindparams(bindparam("f", type_=PG_UUID(as_uuid=True))),
        {"f": farm_id, "p": f"{prefix}%"},
    )
    return {r.code: UUID(str(r.id)) for r in rows}


async def _fill_map(session: AsyncSession, name: str, pairs: dict[UUID, UUID]) -> None:
    """A temporary (src, dst) table the INSERT ... SELECT statements join on."""
    await session.execute(
        text(
            f"CREATE TEMP TABLE IF NOT EXISTS {name} "
            "(src uuid PRIMARY KEY, dst uuid NOT NULL) ON COMMIT DROP"
        )
    )
    await session.execute(text(f"TRUNCATE {name}"))
    if not pairs:
        return
    await session.execute(
        # `name` is one of this module's own temp-table names, never input.
        text(f"INSERT INTO {name} (src, dst) VALUES (:s, :d)").bindparams(  # noqa: S608
            bindparam("s", type_=PG_UUID(as_uuid=True)),
            bindparam("d", type_=PG_UUID(as_uuid=True)),
        ),
        [{"s": src, "d": dst} for src, dst in pairs.items()],
    )


def _select_list(
    columns: list[str],
    remap: dict[str, str],
    *,
    constants: dict[str, str] | None = None,
) -> str:
    """The SELECT side of a copy: mapped ids, cleared authors, the rest as is."""
    out = []
    for col in columns:
        if col in remap:
            out.append(f"{remap[col]}.dst")
        elif constants and col in constants:
            out.append(constants[col])
        elif col in _PEOPLE_COLUMNS:
            out.append("NULL")
        else:
            out.append(f's."{col}"')
    return ", ".join(out)


async def _copy_grids(
    session: AsyncSession, src: str, dst: str, block_map: dict[UUID, UUID]
) -> dict[str, int]:
    """Copy the grids of target blocks that have none, and map every cell.

    A target block that already has a grid keeps it, and its cells are
    matched to the source cells by (row, column) on the grid with the same
    product and cell size. Cells that do not match are left out of the copy
    rather than attached to the wrong ground.
    """
    counts = {"grid_configs": 0, "grid_cells": 0}
    config_map: dict[UUID, UUID] = {}
    cell_map: dict[UUID, UUID] = {}

    source_configs = (
        (
            await session.execute(
                text(
                    f'SELECT id, block_id, product_id, cell_size_m FROM "{src}".grid_configs '  # noqa: S608
                    "WHERE block_id = ANY(:b)"
                ),
                {"b": list(block_map)},
            )
        )
        .mappings()
        .all()
    )
    target_configs = (
        (
            await session.execute(
                text(
                    f'SELECT id, block_id, product_id, cell_size_m FROM "{dst}".grid_configs '  # noqa: S608
                    "WHERE block_id = ANY(:b) AND retired_at IS NULL"
                ),
                {"b": list(block_map.values())},
            )
        )
        .mappings()
        .all()
    )
    existing = {(r["block_id"], r["product_id"], r["cell_size_m"]): r["id"] for r in target_configs}
    blocks_with_grid = {r["block_id"] for r in target_configs}

    fresh: dict[UUID, UUID] = {}
    for cfg in source_configs:
        target_block = block_map[cfg["block_id"]]
        match = existing.get((target_block, cfg["product_id"], cfg["cell_size_m"]))
        if match is not None:
            config_map[cfg["id"]] = match
        elif target_block not in blocks_with_grid:
            fresh[cfg["id"]] = uuid4()
            config_map[cfg["id"]] = fresh[cfg["id"]]

    if fresh:
        await _fill_map(session, "_cfg_new", fresh)
        cols = await _columns(session, dst, "grid_configs")
        select = _select_list(cols, {"id": "m", "block_id": "b"})
        result = await session.execute(
            text(
                f'INSERT INTO "{dst}".grid_configs ({_quoted(cols)}) '  # noqa: S608
                f'SELECT {select} FROM "{src}".grid_configs s '
                "JOIN _cfg_new m ON m.src = s.id JOIN _blk b ON b.src = s.block_id "
                "ON CONFLICT DO NOTHING"
            )
        )
        counts["grid_configs"] = _rows(result)

        # New cells for the new grids, one fresh id each.
        sql = f'SELECT id FROM "{src}".grid_cells WHERE grid_config_id = ANY(:c)'  # noqa: S608
        src_cells = (await session.execute(text(sql), {"c": list(fresh)})).scalars().all()
        new_cells = {UUID(str(c)): uuid4() for c in src_cells}
        await _fill_map(session, "_cell_new", new_cells)
        cell_cols = await _columns(session, dst, "grid_cells")
        select = _select_list(cell_cols, {"id": "m", "grid_config_id": "c"})
        result = await session.execute(
            text(
                f'INSERT INTO "{dst}".grid_cells ({_quoted(cell_cols)}) '  # noqa: S608
                f'SELECT {select} FROM "{src}".grid_cells s '
                "JOIN _cell_new m ON m.src = s.id JOIN _cfg_new c ON c.src = s.grid_config_id "
                "ON CONFLICT DO NOTHING"
            )
        )
        counts["grid_cells"] = _rows(result)
        cell_map.update(new_cells)

    # Cells of grids the target already had: match by position.
    matched = {k: v for k, v in config_map.items() if k not in fresh}
    if matched:
        await _fill_map(session, "_cfg_old", matched)
        rows = await session.execute(
            text(
                f'SELECT s.id AS src, t.id AS dst FROM "{src}".grid_cells s '  # noqa: S608
                "JOIN _cfg_old m ON m.src = s.grid_config_id "
                f'JOIN "{dst}".grid_cells t ON t.grid_config_id = m.dst '
                "AND t.row_idx = s.row_idx AND t.col_idx = s.col_idx"
            )
        )
        for r in rows:
            cell_map[UUID(str(r.src))] = UUID(str(r.dst))

    await _fill_map(session, "_cell", cell_map)
    counts["cells_mapped"] = len(cell_map)
    return counts


def _quoted(columns: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in columns)


async def _copy_jobs(session: AsyncSession, src: str, dst: str) -> int:
    """Scene records, attached to the target block's subscription.

    The target subscription is the one on the matched block for the same
    product. A job whose product the target block is not subscribed to is
    left behind: its index rows still copy, but there is no subscription to
    hang the scene record on.
    """
    cols = [c for c in await _columns(session, dst, "imagery_ingestion_jobs") if c != "id"]
    select = _select_list(cols, {"block_id": "b", "subscription_id": "sub"})
    result = await session.execute(
        text(
            f'INSERT INTO "{dst}".imagery_ingestion_jobs ({_quoted(cols)}) '  # noqa: S608
            f'SELECT {select} FROM "{src}".imagery_ingestion_jobs s '
            "JOIN _blk b ON b.src = s.block_id "
            "JOIN LATERAL ("
            f'  SELECT t.id AS dst FROM "{dst}".imagery_aoi_subscriptions t '
            "   WHERE t.block_id = b.dst AND t.product_id = s.product_id "
            "   ORDER BY t.is_active DESC, t.created_at LIMIT 1"
            ") sub ON TRUE "
            f'WHERE NOT EXISTS (SELECT 1 FROM "{dst}".imagery_ingestion_jobs x '
            "  WHERE x.block_id = b.dst AND x.product_id = s.product_id AND x.scene_id = s.scene_id) "
            "ON CONFLICT DO NOTHING"
        )
    )
    return _rows(result)


async def _copy_block_table(
    session: AsyncSession, src: str, dst: str, table: str, remap: tuple[str, ...]
) -> int:
    cols = await _columns(session, dst, table)
    aliases = {"block_id": "b", "cell_id": "c"}
    select = _select_list(cols, {col: aliases[col] for col in remap})
    joins = " ".join(
        f"JOIN {'_blk' if col == 'block_id' else '_cell'} {aliases[col]} ON {aliases[col]}.src = s.{col}"
        for col in remap
    )
    result = await session.execute(
        text(
            f'INSERT INTO "{dst}"."{table}" ({_quoted(cols)}) '  # noqa: S608
            f'SELECT {select} FROM "{src}"."{table}" s {joins} '
            "ON CONFLICT DO NOTHING"
        )
    )
    return _rows(result)


async def _copy_farm_table(
    session: AsyncSession, src: str, dst: str, table: str, *, src_farm: UUID, dst_farm: UUID
) -> int:
    cols = await _columns(session, dst, table)
    if not cols:
        return 0
    select = _select_list(cols, {}, constants={"farm_id": "CAST(:dst_farm AS uuid)"})
    result = await session.execute(
        text(
            f'INSERT INTO "{dst}"."{table}" ({_quoted(cols)}) '  # noqa: S608
            f'SELECT {select} FROM "{src}"."{table}" s WHERE s.farm_id = :src_farm '
            "ON CONFLICT DO NOTHING"
        ).bindparams(
            bindparam("src_farm", type_=PG_UUID(as_uuid=True)),
        ),
        {"src_farm": src_farm, "dst_farm": str(dst_farm)},
    )
    return _rows(result)


async def copy_history(
    session_factory: Any,
    *,
    source: CopySource,
    target_schema: str,
    target_farm_code: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy `source`'s history onto `target_farm_code`, in one transaction.

    Returns the rows inserted per table and the block codes that matched.
    With `dry_run` everything is rolled back, so the counts say what a real
    run would add.
    """
    src = sanitize_tenant_schema(source.schema)
    dst = sanitize_tenant_schema(target_schema)
    if src == dst:
        raise ValueError("source and target are the same tenant")

    report: dict[str, Any] = {"source": src, "target": dst, "dry_run": dry_run, "tables": {}}
    async with session_factory() as session:
        await session.begin()
        # The target's own schema first: the audit insert and the temporary
        # tables resolve against it.
        await session.execute(text(f"SET LOCAL search_path TO {dst}, public"))
        src_farm = await _farm_id(session, src, source.farm_code)
        dst_farm = await _farm_id(session, dst, target_farm_code)
        src_blocks = await _blocks(session, src, src_farm, source.block_prefix)
        dst_blocks = await _blocks(session, dst, dst_farm, source.block_prefix)
        common = sorted(set(src_blocks) & set(dst_blocks))
        if not common:
            raise ValueError("the two farms have no block code in common")
        report["blocks"] = common
        report["blocks_only_in_source"] = sorted(set(src_blocks) - set(dst_blocks))
        block_map = {src_blocks[c]: dst_blocks[c] for c in common}

        await _fill_map(session, "_blk", block_map)
        report["tables"].update(await _copy_grids(session, src, dst, block_map))
        report["tables"]["imagery_ingestion_jobs"] = await _copy_jobs(session, src, dst)
        for table, remap in _BLOCK_TABLES:
            report["tables"][table] = await _copy_block_table(session, src, dst, table, remap)
        for table in _FARM_TABLES:
            report["tables"][table] = await _copy_farm_table(
                session, src, dst, table, src_farm=src_farm, dst_farm=dst_farm
            )

        await session.execute(
            text(
                """
                INSERT INTO audit_events
                    (time, id, event_type, actor_user_id, actor_kind, subject_kind,
                     subject_id, farm_id, details)
                VALUES (clock_timestamp(), :id, :ev, NULL, 'system', 'farm',
                        :farm, :farm, CAST(:details AS jsonb))
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": uuid4(),
                "ev": AUDIT_EVENT,
                "farm": dst_farm,
                "details": _json(report),
            },
        )
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    _log.info("demo_history_copy_done", **{k: v for k, v in report.items() if k != "tables"})
    return report


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


__all__ = ["AUDIT_EVENT", "CopySource", "copy_history"]


def _rows(result: Any) -> int:
    """Rows an INSERT wrote. `rowcount` is on the cursor result only."""
    return int(getattr(result, "rowcount", 0) or 0)
