"""DB access for the grid-zones module. Internal to the module.

Operations are organised by domain object:

  * Block reads — ``boundary_utm`` + area + SRID for grid generation.
  * Product reads — ``resolution_m`` for guardrail checks (cross-schema
    to ``public.imagery_products``).
  * grid_configs — fetch / upsert / soft-retire.
  * grid_cells — bulk insert / count / delete-by-config.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.grid.geometry import GeneratedCell


class GridRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- block context ------------------------------------------------

    async def get_block_geometry(
        self, *, block_id: UUID
    ) -> dict[str, Any] | None:
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

    # ---- grid_configs -------------------------------------------------

    async def get_active_config(
        self, *, block_id: UUID, product_id: UUID
    ) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT id, block_id, product_id, cell_size_m, utm_srid,
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
    ) -> UUID:
        """Insert a new active grid_config row. Caller must have retired
        any previous active config for the same (block, product) first.
        """
        row = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO grid_configs (
                        block_id, product_id, cell_size_m, utm_srid,
                        created_by, updated_by
                    ) VALUES (
                        :block_id, :product_id, :cell_size_m, :utm_srid,
                        :created_by, :created_by
                    )
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("created_by", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "block_id": block_id,
                    "product_id": product_id,
                    "cell_size_m": cell_size_m,
                    "utm_srid": utm_srid,
                    "created_by": created_by,
                },
            )
        ).scalar_one()
        await self._session.flush()
        return row

    async def retire_config(self, *, config_id: UUID, retired_at: datetime) -> None:
        await self._session.execute(
            text(
                """
                UPDATE grid_configs
                SET retired_at = :retired_at,
                    updated_at = now()
                WHERE id = :config_id
                  AND retired_at IS NULL
                """
            ).bindparams(bindparam("config_id", type_=PG_UUID(as_uuid=True))),
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
        per row, a busy scene (a few thousand cells × six indices)
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
        """Most recent scene time with any cell observation for (block, product, index)."""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT MAX(time) AS t
                    FROM block_grid_aggregates
                    WHERE block_id   = :block
                      AND product_id = :product
                      AND index_code = :code
                    """
                ).bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True)),
                    bindparam("product", type_=PG_UUID(as_uuid=True)),
                ),
                {"block": block_id, "product": product_id, "code": index_code},
            )
        ).scalar_one_or_none()
        return row

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
                          AND cfg.retired_at IS NULL
                        ORDER BY gc.row_idx, gc.col_idx
                        """
                    ).bindparams(
                        bindparam("block", type_=PG_UUID(as_uuid=True)),
                        bindparam("product", type_=PG_UUID(as_uuid=True)),
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

    async def resolve_cell_context(
        self, *, cell_id: UUID
    ) -> dict[str, Any] | None:
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
                text(
                    "SELECT count(*) FROM grid_cells WHERE grid_config_id = :gc"
                ).bindparams(bindparam("gc", type_=PG_UUID(as_uuid=True))),
                {"gc": grid_config_id},
            )
        ).scalar_one()
        return int(row)
