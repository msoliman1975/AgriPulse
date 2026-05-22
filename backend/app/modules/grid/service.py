"""GridService Protocol + concrete impl.

PR-1 surface:

  * :meth:`preview_cell_size` — guardrail check + estimate. No writes.
  * :meth:`get_active_config` — fetch the current active config for a
    (block, product) pair.
  * :meth:`upsert_config` — soft-retire any previous active config,
    insert a new one, regenerate cells. All in one transaction.

PR-2 will add a ``record_grid_aggregate_rows`` method that the imagery
pipeline calls per scene; the protocol stays here so consumers don't
import the impl.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.grid.errors import (
    CellSizeInvalidError,
    GridConfigNotFoundError,
    ProductNotFoundError,
)
from app.modules.grid.geometry import (
    estimate_cell_count,
    generate_cells,
    validate_cell_size,
)
from app.modules.grid.repository import GridRepository
from app.modules.grid.schemas import (
    CellSizePreviewResponse,
    GridCellHistoryPoint,
    GridCellHistoryResponse,
    GridCellsResponse,
    GridCellWithValue,
    GridConfigResponse,
)
from app.modules.grid.zonal import CellAggregates


class GridService(Protocol):
    """Public contract for the grid-zones module."""

    async def preview_cell_size(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        cell_size_m: Decimal,
    ) -> CellSizePreviewResponse: ...

    async def get_active_config(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
    ) -> GridConfigResponse | None: ...

    async def upsert_config(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        cell_size_m: Decimal,
        created_by: UUID | None,
    ) -> GridConfigResponse: ...

    async def list_active_cells(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
    ) -> tuple[dict[str, Any], ...]: ...

    async def record_grid_aggregates(
        self,
        *,
        scene_time: datetime,
        block_id: UUID,
        product_id: UUID,
        stac_item_id: str,
        cloud_cover_pct: Decimal | None,
        per_cell_per_index: dict[UUID, dict[str, CellAggregates]],
    ) -> int: ...

    async def get_cells_with_values(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        at: datetime | None,
    ) -> GridCellsResponse: ...

    async def get_cell_history(
        self,
        *,
        cell_id: UUID,
        product_id: UUID,
        index_code: str,
    ) -> GridCellHistoryResponse: ...

    async def resolve_cell_context(
        self,
        *,
        cell_id: UUID,
    ) -> dict[str, Any] | None: ...


class GridServiceImpl:
    """Concrete service. One per request — receives a tenant-scoped session."""

    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._session = tenant_session
        self._repo = GridRepository(tenant_session)
        self._log = get_logger(__name__)

    async def preview_cell_size(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        cell_size_m: Decimal,
    ) -> CellSizePreviewResponse:
        block = await self._repo.get_block_geometry(block_id=block_id)
        if block is None:
            # Preview is read-only so a missing block surfaces as a 404
            # via the router's block visibility check; getting here
            # means the block exists but was deleted between checks.
            raise GridConfigNotFoundError(str(block_id), str(product_id))
        native = await self._repo.get_product_resolution(product_id=product_id)
        if native is None:
            raise ProductNotFoundError(str(product_id))

        error = validate_cell_size(
            cell_size_m=cell_size_m,
            native_pixel_m=native,
            block_area_m2=block["area_m2"],
        )
        estimated = estimate_cell_count(
            boundary_utm_wkt=block["boundary_utm_wkt"],
            cell_size_m=cell_size_m,
        )
        pixels_per_cell = int((float(cell_size_m) / float(native)) ** 2)
        return CellSizePreviewResponse(
            cell_size_m=cell_size_m,
            native_pixel_m=native,
            pixels_per_cell=pixels_per_cell,
            estimated_cells=estimated,
            block_area_m2=block["area_m2"],
            valid=error is None,
            error=error,
        )

    async def get_active_config(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
    ) -> GridConfigResponse | None:
        row = await self._repo.get_active_config(
            block_id=block_id, product_id=product_id
        )
        if row is None:
            return None
        count = await self._repo.count_cells(grid_config_id=row["id"])
        return GridConfigResponse(cell_count=count, **row)

    async def upsert_config(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        cell_size_m: Decimal,
        created_by: UUID | None,
    ) -> GridConfigResponse:
        # 1. Validate inputs against the product + block bounds.
        block = await self._repo.get_block_geometry(block_id=block_id)
        if block is None:
            raise GridConfigNotFoundError(str(block_id), str(product_id))
        native = await self._repo.get_product_resolution(product_id=product_id)
        if native is None:
            raise ProductNotFoundError(str(product_id))
        error = validate_cell_size(
            cell_size_m=cell_size_m,
            native_pixel_m=native,
            block_area_m2=block["area_m2"],
        )
        if error is not None:
            raise CellSizeInvalidError(detail=error)

        # 2. Soft-retire any prior active config so the partial unique
        # index doesn't collide on insert.
        prior = await self._repo.get_active_config(
            block_id=block_id, product_id=product_id
        )
        now = datetime.now(tz=UTC)
        if prior is not None:
            # Same cell size = no-op (idempotent re-PUT).
            if prior["cell_size_m"] == cell_size_m:
                count = await self._repo.count_cells(grid_config_id=prior["id"])
                return GridConfigResponse(cell_count=count, **prior)
            await self._repo.retire_config(config_id=prior["id"], retired_at=now)

        # 3. Insert new config + generate + bulk-write cells.
        utm_srid = int(block["utm_srid"])
        config_id = await self._repo.insert_config(
            block_id=block_id,
            product_id=product_id,
            cell_size_m=cell_size_m,
            utm_srid=utm_srid,
            created_by=created_by,
        )

        cells = list(
            generate_cells(
                boundary_utm_wkt=block["boundary_utm_wkt"],
                cell_size_m=cell_size_m,
            )
        )
        inserted = await self._repo.bulk_insert_cells(
            grid_config_id=config_id,
            utm_srid=utm_srid,
            cells=cells,
        )
        self._log.info(
            "grid_config.created",
            block_id=str(block_id),
            product_id=str(product_id),
            cell_size_m=str(cell_size_m),
            cells_generated=inserted,
        )

        fresh = await self._repo.get_active_config(
            block_id=block_id, product_id=product_id
        )
        # By construction the new config is the active one; the None
        # branch is unreachable but keeps mypy honest.
        assert fresh is not None
        return GridConfigResponse(cell_count=inserted, **fresh)


    async def list_active_cells(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_active_cells_for_block_product(
            block_id=block_id, product_id=product_id
        )

    async def record_grid_aggregates(
        self,
        *,
        scene_time: datetime,
        block_id: UUID,
        product_id: UUID,
        stac_item_id: str,
        cloud_cover_pct: Decimal | None,
        per_cell_per_index: dict[UUID, dict[str, CellAggregates]],
    ) -> int:
        """Persist per-(cell, index) aggregates for one scene.

        Idempotent on the UNIQUE (time, cell_id, index_code,
        product_id) — re-running compute for the same scene is a
        no-op. Returns the number of rows in the batch (the input
        size; conflict rows are dropped silently).
        """
        rows: list[dict[str, Any]] = []
        for cell_id, per_index in per_cell_per_index.items():
            for index_code, agg in per_index.items():
                rows.append(
                    {
                        "time": scene_time,
                        "cell_id": cell_id,
                        "block_id": block_id,
                        "index_code": index_code,
                        "product_id": product_id,
                        "stac_item_id": stac_item_id,
                        "mean": agg.mean,
                        "min_val": agg.min,
                        "max_val": agg.max,
                        "std_dev": agg.std_dev,
                        "valid_pixel_count": agg.valid_pixel_count,
                        "total_pixel_count": agg.total_pixel_count,
                        "cloud_cover_pct": cloud_cover_pct,
                    }
                )
        return await self._repo.bulk_upsert_aggregates(rows=rows)


    async def get_cells_with_values(
        self,
        *,
        block_id: UUID,
        product_id: UUID,
        index_code: str,
        at: datetime | None,
    ) -> GridCellsResponse:
        # Resolve "latest" lazily so a stale `at` from the client is
        # never silently extrapolated — either we use what they sent
        # or we use whatever the most-recent observation says.
        import json

        resolved_at = at
        if resolved_at is None:
            resolved_at = await self._repo.get_latest_scene_time(
                block_id=block_id, product_id=product_id, index_code=index_code
            )
        rows = await self._repo.list_cells_with_values(
            block_id=block_id,
            product_id=product_id,
            index_code=index_code,
            at=resolved_at,
        )
        cells = tuple(
            GridCellWithValue(
                cell_id=r["cell_id"],
                row_idx=r["row_idx"],
                col_idx=r["col_idx"],
                area_m2=r["area_m2"],
                centroid_lon=float(r["centroid_lon"]),
                centroid_lat=float(r["centroid_lat"]),
                geometry=json.loads(r["geometry_json"]),
                mean=r["mean"],
                valid_pixel_pct=r["valid_pixel_pct"],
                time=r["time"],
            )
            for r in rows
        )
        return GridCellsResponse(
            block_id=block_id,
            product_id=product_id,
            index_code=index_code,
            cells=cells,
            at=resolved_at,
        )

    async def get_cell_history(
        self,
        *,
        cell_id: UUID,
        product_id: UUID,
        index_code: str,
    ) -> GridCellHistoryResponse:
        rows = await self._repo.get_cell_history(
            cell_id=cell_id, index_code=index_code, product_id=product_id
        )
        points = tuple(
            GridCellHistoryPoint(
                time=r["time"],
                mean=r["mean"],
                min=r["min"],
                max=r["max"],
                std_dev=r["std_dev"],
                valid_pixel_pct=r["valid_pixel_pct"],
            )
            for r in rows
        )
        return GridCellHistoryResponse(
            cell_id=cell_id,
            index_code=index_code,
            product_id=product_id,
            points=points,
        )

    async def resolve_cell_context(
        self,
        *,
        cell_id: UUID,
    ) -> dict[str, Any] | None:
        return await self._repo.resolve_cell_context(cell_id=cell_id)


def get_grid_service(*, tenant_session: AsyncSession) -> GridService:
    """Factory used by the router's FastAPI dependency."""
    return GridServiceImpl(tenant_session=tenant_session)
