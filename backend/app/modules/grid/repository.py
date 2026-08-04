"""DB access for the grid-zones module. Internal to the module.

Operations are organised by domain object:

  * Block reads — ``boundary_utm`` + area + SRID for grid generation.
  * Product reads — ``resolution_m`` for guardrail checks (cross-schema
    to ``public.imagery_products``).
  * grid_configs — fetch / upsert / soft-retire.
  * grid_cells — bulk insert / count / delete-by-config.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Numeric, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.grid.geometry import GeneratedCell

# ---- Valid-time predicates (tenant migration 0054) -------------------------
#
# Two different questions get asked of grid_configs, and conflating them is
# the §2.2 defect this module used to have. They are spelled out once here so
# the six read sites can't drift apart.
#
# GOVERNS_AT — "which geometry describes this scene time?" Use wherever an
# observation is involved. `superseded_at IS NOT NULL` means the config has
# been fully replaced and governs nothing, even though its rows are still
# physically present until the cleanup task runs.
#
# Interpolated into SQL with `.format()`, so call sites carry `noqa: S608`.
# The only substitution is the timestamp *expression* — either a column
# reference chosen here or a `CAST(:at AS timestamptz)` bind — never a
# caller-supplied value. Values always travel as bind parameters.
_GOVERNS_AT = """
          AND cfg.deleted_at IS NULL
          AND cfg.superseded_at IS NULL
          AND tstzrange(cfg.effective_from, cfg.effective_to) @> {ts}
"""

# The other question — "which geometry do new scenes land on?" — keeps its
# existing `retired_at IS NULL` spelling. That is the honest transaction-time
# answer, and it already excludes superseded configs (a config is retired at
# the moment it is replaced, and only ever superseded afterwards), so those
# sites need no valid-time predicate.


class GridRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- block context ------------------------------------------------

    async def get_block_geometry(self, *, block_id: UUID) -> dict[str, Any] | None:
        """Return ``boundary_utm`` (WKT), ``area_m2``, ``utm_srid`` for a block.

        Returns ``None`` if the block doesn't exist in the tenant schema.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            ST_AsText(boundary_utm) AS boundary_utm_wkt,
                            ST_SRID(boundary_utm)    AS utm_srid,
                            area_m2,
                            farm_id
                        FROM blocks
                        WHERE id = :block_id
                          AND deleted_at IS NULL
                        """
                    ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    {"block_id": block_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    # ---- imagery_products (cross-schema) ------------------------------

    async def get_product_resolution(self, *, product_id: UUID) -> Decimal | None:
        """Look up ``resolution_m`` from the public catalog. None if missing."""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT resolution_m
                    FROM public.imagery_products
                    WHERE id = :product_id AND is_active = TRUE
                    """
                ).bindparams(bindparam("product_id", type_=PG_UUID(as_uuid=True))),
                {"product_id": product_id},
            )
        ).scalar_one_or_none()
        return Decimal(row) if row is not None else None

    async def get_pivot_geometry(self, *, block_id: UUID) -> dict[str, Any] | None:
        """Center/radius/sector_count for a pivot unit, else None.

        Returns None for non-pivot blocks or pivots missing the geometry,
        so callers can fall back to plain row/col labels. The shape mirrors
        ``blocks.irrigation_geometry``:
        ``{"center": {"lat", "lon"}, "radius_m", "sector_count"}``.
        """
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT unit_type, irrigation_geometry
                    FROM blocks
                    WHERE id = :block AND deleted_at IS NULL
                    """
                    ).bindparams(bindparam("block", type_=PG_UUID(as_uuid=True))),
                    {"block": block_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["unit_type"] != "pivot":
            return None
        geom = row["irrigation_geometry"]
        if isinstance(geom, str):
            geom = json.loads(geom)
        if not isinstance(geom, dict):
            return None
        center = geom.get("center") or {}
        try:
            return {
                "center_lon": float(center["lon"]),
                "center_lat": float(center["lat"]),
                "radius_m": float(geom["radius_m"]),
                "sector_count": int(geom.get("sector_count") or 4),
            }
        except (KeyError, TypeError, ValueError):
            return None

    # ---- grid_configs -------------------------------------------------

    async def get_active_config(self, *, block_id: UUID, product_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT id, block_id, product_id, cell_size_m, utm_srid,
                               anomaly_z_threshold,
                               retired_at, created_at, updated_at
                        FROM grid_configs
                        WHERE block_id = :block_id
                          AND product_id = :product_id
                          AND retired_at IS NULL
                        """
                    ).bindparams(
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"block_id": block_id, "product_id": product_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def insert_config(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        cell_size_m: Decimal,
        utm_srid: int,
        created_by: UUID | None,
        anomaly_z_threshold: Decimal | None = None,
        effective_from: datetime | None = None,
    ) -> UUID:
        """Insert a new active grid_config row. Caller must have retired
        any previous active config for the same (block, product) first.

        ``anomaly_z_threshold`` carries forward a per-block detection
        override across a rezone so the operator's tuning survives a
        cell-size change.

        ``effective_from`` is the scene time this geometry starts
        governing. ``None`` means ``-infinity`` — "this grid describes all
        of history" — which is right for a block's *first* grid, including
        one created before a historical backfill runs. A rezone must pass
        the cutover instant instead, so the geometry it replaces keeps
        governing the scenes it actually produced.
        """
        row = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO grid_configs (
                        block_id, product_id, cell_size_m, utm_srid,
                        anomaly_z_threshold, created_by, updated_by,
                        effective_from
                    ) VALUES (
                        :block_id, :product_id, :cell_size_m, :utm_srid,
                        :anomaly_z_threshold, :created_by, :created_by,
                        COALESCE(:effective_from, '-infinity'::timestamptz)
                    )
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("created_by", type_=PG_UUID(as_uuid=True)),
                    bindparam("effective_from", type_=DateTime(timezone=True)),
                ),
                {
                    "block_id": block_id,
                    "product_id": product_id,
                    "cell_size_m": cell_size_m,
                    "utm_srid": utm_srid,
                    "anomaly_z_threshold": anomaly_z_threshold,
                    "created_by": created_by,
                    "effective_from": effective_from,
                },
            )
        ).scalar_one()
        await self._session.flush()
        return row

    async def update_config_threshold(
        self, *, config_id: UUID, anomaly_z_threshold: Decimal | None
    ) -> None:
        """Update only the per-block anomaly threshold on an active config.

        Used when the operator tunes the threshold without changing the
        cell size — avoids retiring + regenerating the whole cell grid for
        a knob that doesn't touch geometry.
        """
        await self._session.execute(
            text(
                """
                UPDATE grid_configs
                SET anomaly_z_threshold = :v,
                    updated_at = now()
                WHERE id = :config_id
                  AND retired_at IS NULL
                """
            ).bindparams(bindparam("config_id", type_=PG_UUID(as_uuid=True))),
            {"config_id": config_id, "v": anomaly_z_threshold},
        )
        await self._session.flush()

    async def list_farm_grid_rows(
        self, *, block_ids: tuple[UUID, ...]
    ) -> tuple[dict[str, Any], ...]:
        """One row per (block, active imagery subscription) for a block set.

        Single statement on purpose: the farm-wide preview runs over every
        block of a farm, and a per-block fan-out here is exactly the N+1
        that exhausted the pool on the map endpoints (#311).

        Blocks with no active subscription still yield one row with NULL
        product columns, so the preview can show *why* they were left out
        instead of dropping them. Blocks whose subscription has no grid
        config yield NULL config columns.
        """
        if not block_ids:
            return ()
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            b.id            AS block_id,
                            b.code          AS block_code,
                            b.name          AS block_name,
                            b.area_m2       AS block_area_m2,
                            s.product_id    AS product_id,
                            p.code          AS product_code,
                            p.name          AS product_name,
                            p.resolution_m  AS native_pixel_m,
                            cfg.id                  AS grid_config_id,
                            cfg.cell_size_m         AS current_cell_size_m,
                            cfg.anomaly_z_threshold AS current_anomaly_z_threshold
                        FROM blocks b
                        LEFT JOIN imagery_aoi_subscriptions s
                               ON s.block_id = b.id
                              AND s.is_active = TRUE
                        LEFT JOIN public.imagery_products p
                               ON p.id = s.product_id
                              AND p.is_active = TRUE
                        LEFT JOIN grid_configs cfg
                               ON cfg.block_id   = b.id
                              AND cfg.product_id = s.product_id
                              AND cfg.retired_at IS NULL
                              AND cfg.deleted_at IS NULL
                        WHERE b.id = ANY(:block_ids)
                          AND b.deleted_at IS NULL
                        ORDER BY b.code, p.code NULLS FIRST
                        """
                    ).bindparams(
                        bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
                    ),
                    {"block_ids": list(block_ids)},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def set_config_thresholds(
        self,
        *,
        config_ids: tuple[UUID, ...],
        anomaly_z_threshold: Decimal | None,
    ) -> int:
        """Set ``anomaly_z_threshold`` on many active configs at once.

        Threshold-only: touches no geometry, retires nothing, regenerates
        no cells. That is the whole reason a farm-wide threshold apply is
        safe while a farm-wide cell-size apply is not.

        ``anomaly_z_threshold=None`` clears the override so the block
        falls back to the tenant/platform default.
        """
        if not config_ids:
            return 0
        result = await self._session.execute(
            text(
                """
                UPDATE grid_configs
                SET anomaly_z_threshold = :threshold,
                    updated_at = now()
                WHERE id = ANY(:config_ids)
                  AND retired_at IS NULL
                  AND deleted_at IS NULL
                """
            ).bindparams(
                bindparam("config_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
                # NUMERIC bind pinned so asyncpg doesn't have to infer the
                # type of a bare NULL on the clear-override path.
                bindparam("threshold", type_=Numeric(4, 2)),
            ),
            {"config_ids": list(config_ids), "threshold": anomaly_z_threshold},
        )
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    async def retire_config(self, *, config_id: UUID, retired_at: datetime) -> None:
        """Close a config in both time dimensions at once.

        ``retired_at`` is transaction time — when the operator changed
        their mind. ``effective_to`` is valid time — the scene times this
        geometry stops governing. They are stamped together here because
        the replacement config opens its own range at exactly this
        instant; letting them drift apart is what produced the §2.2
        orphaning, and would now also trip the non-overlap constraint.
        """
        await self._session.execute(
            text(
                """
                UPDATE grid_configs
                SET retired_at   = :retired_at,
                    effective_to = :retired_at,
                    updated_at   = now()
                WHERE id = :config_id
                  AND retired_at IS NULL
                """
            ).bindparams(
                bindparam("config_id", type_=PG_UUID(as_uuid=True)),
                bindparam("retired_at", type_=DateTime(timezone=True)),
            ),
            {"config_id": config_id, "retired_at": retired_at},
        )
        await self._session.flush()

    # ---- grid_cells ---------------------------------------------------

    async def bulk_insert_cells(
        self,
        *,
        grid_config_id: UUID,
        utm_srid: int,
        cells: list[GeneratedCell],
    ) -> int:
        """Insert all cells for one grid_config. The centroid in 4326
        is computed in-DB via ``ST_Transform(ST_Centroid(geom), 4326)``
        so we don't need pyproj on the Python side.

        Returns the number of rows inserted.
        """
        if not cells:
            return 0
        values_sql = ", ".join(
            f"(:gc, :r{i}, :c{i}, "
            f"ST_GeomFromText(:g{i}, :srid), "
            f"ST_Transform(ST_Centroid(ST_GeomFromText(:g{i}, :srid)), 4326), "
            f":a{i})"
            for i in range(len(cells))
        )
        params: dict[str, Any] = {"gc": grid_config_id, "srid": utm_srid}
        for i, gc in enumerate(cells):
            params[f"r{i}"] = gc.row_idx
            params[f"c{i}"] = gc.col_idx
            params[f"g{i}"] = gc.geom_wkt
            params[f"a{i}"] = gc.area_m2
        await self._session.execute(
            text(
                f"""
                INSERT INTO grid_cells
                    (grid_config_id, row_idx, col_idx, geom, centroid, area_m2)
                VALUES {values_sql}
                """
            ).bindparams(bindparam("gc", type_=PG_UUID(as_uuid=True))),
            params,
        )
        await self._session.flush()
        return len(cells)

    async def list_active_cells_for_block_product(
        self, *, block_id: UUID, product_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        """Return (cell_id, geom_wkt) for every cell of the active
        grid_config for this (block, product), or empty tuple if no
        active config exists.

        Geometry is returned in the config's UTM SRID — same SRID the
        raw COGs are written in, so the caller can run zonal stats
        without re-projecting.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT gc.id AS cell_id,
                               ST_AsText(gc.geom) AS geom_wkt,
                               cfg.utm_srid       AS utm_srid
                        FROM grid_cells gc
                        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                        WHERE cfg.block_id = :block_id
                          AND cfg.product_id = :product_id
                          AND cfg.retired_at IS NULL
                        """
                    ).bindparams(
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"block_id": block_id, "product_id": product_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_cells_for_scene(
        self, *, block_id: UUID, product_id: UUID, at: datetime
    ) -> tuple[dict[str, Any], ...]:
        """Cells of the geometry that governs scene time ``at``.

        The write-path counterpart of :meth:`list_cells_with_values`. A
        scene is not necessarily current: a late-arriving delivery, or any
        historical backfill, computes cell aggregates for a time that may
        predate the live grid. Gridding those against "whatever geometry
        is current" would write 2026 cells for a 2025 scene and leave the
        row unreadable by every valid-time-aware read path.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT gc.id AS cell_id,
                               ST_AsText(gc.geom) AS geom_wkt,
                               cfg.utm_srid       AS utm_srid
                        FROM grid_cells gc
                        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                        WHERE cfg.block_id = :block_id
                          AND cfg.product_id = :product_id
                          {_GOVERNS_AT.format(ts="CAST(:at AS timestamptz)")}
                        """
                    ).bindparams(
                        bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                        bindparam("at", type_=DateTime(timezone=True)),
                    ),
                    {"block_id": block_id, "product_id": product_id, "at": at},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def bulk_upsert_aggregates(
        self,
        *,
        rows: list[dict[str, Any]],
    ) -> int:
        """Upsert grid-cell aggregates. ``rows`` keys must include:
        time, cell_id, block_id, index_code, product_id, stac_item_id,
        mean, min_val, max_val, std_dev, valid_pixel_count,
        total_pixel_count, cloud_cover_pct.

        Re-running computation for the same scene is idempotent — the
        UNIQUE on (time, block_id, cell_id, index_code, product_id)
        collides and we DO NOTHING. Returns the number of rows in the
        input batch (not the number actually inserted; conflict rows
        are silently dropped).

        Chunked because asyncpg (and the underlying Postgres protocol)
        cap a single statement at 32_767 parameters. With 13 params
        per row, a busy scene (a few thousand cells x six indices)
        easily blows past that; chunk to a safe row count to keep each
        execute under the limit.
        """
        if not rows:
            return 0
        # 13 params/row, asyncpg cap 32_767 → 2520 rows max per chunk.
        # Round down to 2000 for headroom against future column adds.
        chunk_size = 2000
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            values_sql = ", ".join(
                f"(:t{i}, :cell{i}, :block{i}, :code{i}, :prod{i}, "
                f":mean{i}, :min{i}, :max{i}, :std{i}, "
                f":vp{i}, :tp{i}, :cc{i}, :stac{i})"
                for i in range(len(chunk))
            )
            params: dict[str, Any] = {}
            for i, r in enumerate(chunk):
                params[f"t{i}"] = r["time"]
                params[f"cell{i}"] = r["cell_id"]
                params[f"block{i}"] = r["block_id"]
                params[f"code{i}"] = r["index_code"]
                params[f"prod{i}"] = r["product_id"]
                params[f"mean{i}"] = r["mean"]
                params[f"min{i}"] = r["min_val"]
                params[f"max{i}"] = r["max_val"]
                params[f"std{i}"] = r["std_dev"]
                params[f"vp{i}"] = r["valid_pixel_count"]
                params[f"tp{i}"] = r["total_pixel_count"]
                params[f"cc{i}"] = r["cloud_cover_pct"]
                params[f"stac{i}"] = r["stac_item_id"]
            await self._session.execute(
                text(
                    f"""
                    INSERT INTO block_grid_aggregates (
                        time, cell_id, block_id, index_code, product_id,
                        mean, "min", "max", std_dev,
                        valid_pixel_count, total_pixel_count, cloud_cover_pct,
                        stac_item_id
                    ) VALUES {values_sql}
                    ON CONFLICT (time, block_id, cell_id, index_code, product_id) DO NOTHING
                    """
                ),
                params,
            )
        await self._session.flush()
        return len(rows)

    async def get_latest_scene_time(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
    ) -> datetime | None:
        """Most recent *readable* scene time for (block, product, index).

        Joins through to ``grid_configs`` rather than scanning
        ``block_grid_aggregates`` raw. Without the join this returned the
        last scene of a retired grid, and the caller then resolved cells
        against a different geometry — an all-NULL heatmap and a silently
        dead anomaly sweep (§2.2). A scene time is only useful here if the
        geometry that produced it can still be read back.
        """
        row = (
            await self._session.execute(
                text(
                    f"""
                    SELECT MAX(obs.time) AS t
                    FROM block_grid_aggregates obs
                    JOIN grid_cells gc   ON gc.id = obs.cell_id
                    JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                    WHERE obs.block_id   = :block
                      AND obs.product_id = :product
                      AND obs.index_code = :code
                      {_GOVERNS_AT.format(ts="obs.time")}
                    """  # noqa: S608 - only _GOVERNS_AT interpolates
                ).bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True)),
                    bindparam("product", type_=PG_UUID(as_uuid=True)),
                ),
                {"block": block_id, "product": product_id, "code": index_code},
            )
        ).scalar_one_or_none()
        return row

    async def list_active_configs(self) -> tuple[dict[str, Any], ...]:
        """Every non-retired grid config in the tenant: (block_id, product_id).

        Drives the anomaly sweep — one detection pass per active grid.
        Also carries ``anomaly_z_threshold`` (nullable per-block override)
        so the sweep can resolve the detection k without a second query.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT block_id, product_id, anomaly_z_threshold
                        FROM grid_configs
                        WHERE retired_at IS NULL
                          AND deleted_at IS NULL
                        ORDER BY created_at
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_active_configs_for_block(self, *, block_id: UUID) -> tuple[dict[str, Any], ...]:
        """Active grid configs for one block: (product_id, anomaly_z_threshold).

        Drives the per-block anomaly snapshot the recommendations engine
        reads (G-4) — a block usually has a single active grid, but the
        schema allows one per imagery product.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT product_id, anomaly_z_threshold
                        FROM grid_configs
                        WHERE block_id = :block
                          AND retired_at IS NULL
                          AND deleted_at IS NULL
                        ORDER BY created_at
                        """
                    ).bindparams(bindparam("block", type_=PG_UUID(as_uuid=True))),
                    {"block": block_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_observed_indices(self, *, block_id: UUID, product_id: UUID) -> tuple[str, ...]:
        """Distinct index codes that have any cell observation for a grid.

        Drives the multi-index sweep (G-1): rather than hardcoding NDVI we
        run detection over exactly the indices the imagery pipeline has
        actually written for this (block, product). Indices with too few
        observed cells are filtered out downstream by the detector's
        ``min_cells`` guard, so listing all present codes is safe.

        Config-joined for the same reason as :meth:`get_latest_scene_time`:
        an index whose only observations belong to a superseded geometry is
        not "observed" for any purpose the caller has — advertising it just
        sends the sweep after a scene time that resolves to zero cells.
        """
        rows = (
            await self._session.execute(
                text(
                    f"""
                    SELECT DISTINCT obs.index_code
                    FROM block_grid_aggregates obs
                    JOIN grid_cells gc   ON gc.id = obs.cell_id
                    JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                    WHERE obs.block_id   = :block
                      AND obs.product_id = :product
                      {_GOVERNS_AT.format(ts="obs.time")}
                    ORDER BY obs.index_code
                    """  # noqa: S608 - only _GOVERNS_AT interpolates
                ).bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True)),
                    bindparam("product", type_=PG_UUID(as_uuid=True)),
                ),
                {"block": block_id, "product": product_id},
            )
        ).all()
        return tuple(str(r[0]) for r in rows)

    async def list_cell_means(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        at: datetime,
    ) -> tuple[dict[str, Any], ...]:
        """Per-cell means for one scene — lean input for anomaly detection.

        Unlike :meth:`list_cells_with_values` this skips geometry/centroid
        work (no ST_AsGeoJSON / transforms): the detector only needs
        (cell_id, row_idx, col_idx, mean), and the sweep runs this across
        every block in the tenant.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        f"""
                        SELECT gc.id AS cell_id, gc.row_idx, gc.col_idx,
                               ST_X(gc.centroid) AS centroid_lon,
                               ST_Y(gc.centroid) AS centroid_lat,
                               obs.mean
                        FROM grid_cells gc
                        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                        JOIN block_grid_aggregates obs
                          ON obs.cell_id    = gc.id
                         AND obs.block_id   = cfg.block_id
                         AND obs.product_id = cfg.product_id
                         AND obs.index_code = :code
                         AND obs.time       = :at
                        WHERE cfg.block_id   = :block
                          AND cfg.product_id = :product
                          {_GOVERNS_AT.format(ts="CAST(:at AS timestamptz)")}
                        """
                    ).bindparams(
                        bindparam("block", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
                        bindparam("at", type_=DateTime(timezone=True)),
                    ),
                    {
                        "block": block_id,
                        "product": product_id,
                        "code": index_code,
                        "at": at,
                    },
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_cells_with_values(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        at: datetime | None,
    ) -> tuple[dict[str, Any], ...]:
        """Per-cell GeoJSON + value at a given scene time (or NULL if no
        observations at that time). Cells without any observation still
        appear so the heatmap can render them as "no data" tiles.

        The geometry is chosen by the *requested scene time*, not by "which
        grid is current": a scene that predates a rezone is served from the
        grid that produced it. Selecting the current grid instead is what
        made a rezone render the whole block as "no data" (§2.2).

        ``at IS NULL`` means "the live grid" — no scene time to resolve
        against, so fall back to the open-ended config.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT
                            gc.id              AS cell_id,
                            gc.row_idx,
                            gc.col_idx,
                            gc.area_m2,
                            ST_X(gc.centroid) AS centroid_lon,
                            ST_Y(gc.centroid) AS centroid_lat,
                            ST_AsGeoJSON(ST_Transform(gc.geom, 4326)) AS geometry_json,
                            obs.mean,
                            obs.valid_pixel_pct,
                            obs.time
                        FROM grid_cells gc
                        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                        LEFT JOIN block_grid_aggregates obs
                          ON obs.cell_id    = gc.id
                         AND obs.product_id = cfg.product_id
                         AND obs.index_code = :code
                         AND (:at IS NULL OR obs.time = :at)
                        WHERE cfg.block_id   = :block
                          AND cfg.product_id = :product
                          AND cfg.deleted_at IS NULL
                          AND cfg.superseded_at IS NULL
                          AND CASE
                                WHEN CAST(:at AS timestamptz) IS NULL
                                  THEN cfg.effective_to IS NULL
                                ELSE tstzrange(cfg.effective_from, cfg.effective_to)
                                     @> CAST(:at AS timestamptz)
                              END
                        ORDER BY gc.row_idx, gc.col_idx
                        """
                    ).bindparams(
                        bindparam("block", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
                        # asyncpg can't infer the type of a bare NULL used in
                        # ":at IS NULL"; pin it to timestamptz so the prepared
                        # statement type-checks when no scene time is given.
                        bindparam("at", type_=DateTime(timezone=True)),
                    ),
                    {
                        "block": block_id,
                        "product": product_id,
                        "code": index_code,
                        "at": at,
                    },
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def get_cell_history(
        self,
        *,
        cell_id: UUID,
        index_code: str,
        product_id: UUID,
    ) -> tuple[dict[str, Any], ...]:
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT time, mean, "min", "max", std_dev, valid_pixel_pct
                        FROM block_grid_aggregates
                        WHERE cell_id    = :cell
                          AND index_code = :code
                          AND product_id = :product
                        ORDER BY time ASC
                        """
                    ).bindparams(
                        bindparam("cell", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"cell": cell_id, "code": index_code, "product": product_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def resolve_cell_context(self, *, cell_id: UUID) -> dict[str, Any] | None:
        """Look up block_id + product_id for a cell — used by RBAC checks."""
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT cfg.block_id, cfg.product_id
                        FROM grid_cells gc
                        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
                        WHERE gc.id = :cell
                        """
                    ).bindparams(bindparam("cell", type_=PG_UUID(as_uuid=True))),
                    {"cell": cell_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    async def count_cells(self, *, grid_config_id: UUID) -> int:
        row = (
            await self._session.execute(
                text("SELECT count(*) FROM grid_cells WHERE grid_config_id = :gc").bindparams(
                    bindparam("gc", type_=PG_UUID(as_uuid=True))
                ),
                {"gc": grid_config_id},
            )
        ).scalar_one()
        return int(row)
