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
