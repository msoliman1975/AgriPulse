"""Forward lineage: what a number went on to cause.

The overview's consumer count is a time proxy — things created on this block
in this window — and says so. This module is the exact answer, and it exists
because the decision engine already records one.

Every decision-tree evaluation stores an ``evaluation_snapshot`` whose
``values`` map is keyed by what the condition actually read:

    indices.ndmi.mean          block aggregate
    grid.ndvi.mean             per-cell aggregate
    weather_index.rainfall.value

So "which recommendations read NDMI on this block" is not an inference from
timestamps — it is a lookup, and it comes back with the number the tree saw.

That last part turns out to be the useful bit. The snapshot froze the value at
decision time; the aggregate row is an upsert. When the two disagree, the row
was recomputed *after* the decision was made — the recommendation is standing
on a number that no longer exists. Nothing else in the product can see that.

Reverse lineage answers the other direction: given a decision, which stored
row would the evaluator have read? The latest aggregate at or before the
decision's timestamp — deterministic, and comparable against the frozen value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.repository import _ts

# Snapshot key prefixes that mean "this decision read that index". Block-level
# and per-cell aggregates are separate namespaces in the evaluator, and a
# consumer reading either is a consumer of the index.
_PREFIXES = ("indices.{code}.", "grid.{code}.")


def _prefix_params(index_code: str) -> dict[str, str]:
    return {f"p{i}": p.format(code=index_code) + "%" for i, p in enumerate(_PREFIXES)}


class ObserverLineageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def consumers_of_index(
        self,
        *,
        block_id: UUID,
        index_code: str,
        window_from: datetime,
        window_to: datetime,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """Recommendations and alerts whose conditions read this index.

        The LATERAL returns the first matching snapshot entry, so the caller
        gets both *which* key matched and the value the tree saw — a
        recommendation that fired on `indices.ndmi.mean = 0.28` is a very
        different finding from one that merely happened the same afternoon.
        """
        params: dict[str, Any] = {
            "bid": str(block_id),
            "limit": limit,
            **_prefix_params(index_code),
        }
        match = " OR ".join(f"kv.key LIKE :p{i}" for i in range(len(_PREFIXES)))

        recs_sql = f"""
            SELECT r.id, r.created_at, r.cell_id, r.tree_code, r.tree_version,
                   r.action_type, r.severity,
                   -- recommendations call it `state`, alerts `status`. The
                   -- lineage list shows both side by side, so it exposes one
                   -- name rather than making the reader learn two.
                   r.state AS status,
                   m.key AS snapshot_key, m.value AS observed_value
              FROM recommendations r
              CROSS JOIN LATERAL (
                SELECT kv.key, kv.value
                  FROM jsonb_each_text(
                         COALESCE(r.evaluation_snapshot -> 'values', '{{}}'::jsonb)
                       ) kv
                 WHERE {match}
                 LIMIT 1
              ) m
             WHERE r.block_id = :bid
               AND r.deleted_at IS NULL
               AND r.created_at >= {_ts(window_from)}
               AND r.created_at < {_ts(window_to)}
             ORDER BY r.created_at DESC
             LIMIT :limit
        """  # noqa: S608 - the only interpolation is a fixed LIKE disjunction
        recs = (await self._s.execute(text(recs_sql), params)).mappings()

        alerts_sql = f"""
            SELECT a.id, a.created_at, a.cell_id, a.rule_code, a.severity,
                   a.status,
                   m.key AS snapshot_key, m.value AS observed_value
              FROM alerts a
              CROSS JOIN LATERAL (
                SELECT kv.key, kv.value
                  FROM jsonb_each_text(
                         COALESCE(a.signal_snapshot -> 'values', '{{}}'::jsonb)
                       ) kv
                 WHERE {match}
                 LIMIT 1
              ) m
             WHERE a.block_id = :bid
               AND a.deleted_at IS NULL
               AND a.created_at >= {_ts(window_from)}
               AND a.created_at < {_ts(window_to)}
             ORDER BY a.created_at DESC
             LIMIT :limit
        """  # noqa: S608
        alerts = (await self._s.execute(text(alerts_sql), params)).mappings()

        return {
            "recommendations": [dict(r) for r in recs],
            "alerts": [dict(r) for r in alerts],
        }

    async def cell_values_for_scene(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        scene_time: datetime,
    ) -> list[dict[str, Any]]:
        """Per-cell means for one scene, for the anomaly pass.

        Returned raw rather than pre-flagged: the outlier decision belongs to
        `grid.anomaly.detect_low_outliers`, and re-implementing its threshold
        maths here would be a second answer to the same question.
        """
        sql = f"""
            SELECT g.cell_id, g.mean, g.valid_pixel_count, g.total_pixel_count,
                   c.row_idx, c.col_idx,
                   ST_X(c.centroid) AS centroid_lon,
                   ST_Y(c.centroid) AS centroid_lat
              FROM block_grid_aggregates g
              JOIN grid_cells c ON c.id = g.cell_id
             WHERE g.block_id = :bid
               AND g.product_id = :pid
               AND g.index_code = :code
               AND g.time = {_ts(scene_time)}
             ORDER BY g.cell_id
        """
        rows = (
            await self._s.execute(
                text(sql),
                {"bid": str(block_id), "pid": str(product_id), "code": index_code},
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def anomaly_threshold(self, *, block_id: UUID, product_id: UUID) -> float | None:
        """The block's z-threshold override, if it has one."""
        row = (
            await self._s.execute(
                text(
                    """
                    SELECT cfg.anomaly_z_threshold
                      FROM grid_configs cfg
                     WHERE cfg.block_id = :bid
                       AND cfg.product_id = :pid
                       AND cfg.retired_at IS NULL
                       AND cfg.deleted_at IS NULL
                     LIMIT 1
                    """
                ),
                {"bid": str(block_id), "pid": str(product_id)},
            )
        ).first()
        return float(row[0]) if row and row[0] is not None else None

    async def source_row_for_decision(
        self,
        *,
        block_id: UUID,
        index_code: str,
        at: datetime,
    ) -> dict[str, Any] | None:
        """The aggregate row the evaluator would have read at that moment.

        The latest at-or-before the decision — deterministic, and the only
        honest answer available: nothing stores an explicit edge from a
        decision back to the row it read.
        """
        sql = f"""
            SELECT a.time, a.mean, a.valid_pixel_count, a.total_pixel_count,
                   a.baseline_deviation, a.stac_item_id, a.product_id,
                   a.inserted_at
              FROM block_index_aggregates a
             WHERE a.block_id = :bid
               AND a.index_code = :code
               AND a.time <= {_ts(at)}
             ORDER BY a.time DESC
             LIMIT 1
        """
        rows = (
            await self._s.execute(text(sql), {"bid": str(block_id), "code": index_code})
        ).mappings()
        found = rows.first()
        return dict(found) if found else None

    async def decision_snapshot(self, *, kind: str, decision_id: UUID) -> dict[str, Any] | None:
        """One recommendation's or alert's frozen evaluation snapshot."""
        if kind == "recommendation":
            sql = """
                SELECT id, block_id, cell_id, created_at,
                       evaluation_snapshot AS snapshot,
                       tree_code AS source_code
                  FROM recommendations
                 WHERE id = :did AND deleted_at IS NULL
            """
        else:
            sql = """
                SELECT id, block_id, cell_id, created_at,
                       signal_snapshot AS snapshot,
                       rule_code AS source_code
                  FROM alerts
                 WHERE id = :did AND deleted_at IS NULL
            """
        rows = (await self._s.execute(text(sql), {"did": str(decision_id)})).mappings()
        found = rows.first()
        return dict(found) if found else None
