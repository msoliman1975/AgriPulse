"""Pydantic schemas for the grid-zones REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GridConfigBody(BaseModel):
    """Request body for PUT /blocks/{b}/grid-configs/{product_id}.

    A bare cell_size_m suffices — utm_srid is inferred server-side from
    ``blocks.boundary_utm``.
    """

    cell_size_m: Decimal = Field(gt=0, description="Cell edge in metres.")


class GridConfigResponse(BaseModel):
    """One ``grid_configs`` row plus a small summary of the generated cells."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    product_id: UUID
    cell_size_m: Decimal
    utm_srid: int
    retired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    cell_count: int = Field(description="Number of materialised cells in this grid.")


class CellSizePreviewRequest(BaseModel):
    """POST /blocks/{b}/grid-configs/{product_id}/preview — guardrail check
    + cell-count estimate without writing anything.
    """

    cell_size_m: Decimal = Field(gt=0)


class CellSizePreviewResponse(BaseModel):
    cell_size_m: Decimal
    native_pixel_m: Decimal
    pixels_per_cell: int = Field(description="Native pixels covered by one cell (square).")
    estimated_cells: int = Field(description="Cells that would intersect this block.")
    block_area_m2: Decimal
    valid: bool
    error: str | None = Field(
        default=None,
        description="Human-readable guardrail violation, or null if valid.",
    )


class GridCellWithValue(BaseModel):
    """One cell + its latest (or scene-specific) index value.

    Geometry is the cell polygon as a GeoJSON dict in WGS84 (4326) so
    the frontend can drop it directly into a MapLibre GeoJSON source.
    """

    cell_id: UUID
    row_idx: int
    col_idx: int
    area_m2: Decimal
    centroid_lon: float
    centroid_lat: float
    geometry: dict[str, object] = Field(description="GeoJSON Polygon in WGS84.")
    mean: Decimal | None
    valid_pixel_pct: Decimal | None
    time: datetime | None = Field(description="Scene time of the value, null if no observations.")


class GridCellsResponse(BaseModel):
    """GET /api/v1/blocks/{block_id}/grid-cells response."""

    block_id: UUID
    product_id: UUID
    index_code: str
    cells: tuple[GridCellWithValue, ...]
    at: datetime | None = Field(
        description="The scene time the values are pulled from (latest by default)."
    )


class GridWorstCell(BaseModel):
    """A single under-performing cell, for the worst-N list.

    Lean by design — no polygon geometry (the list only needs to label
    the cell and fly the map to its centroid on click).
    """

    cell_id: UUID
    row_idx: int
    col_idx: int
    centroid_lon: float
    centroid_lat: float
    mean: Decimal | None
    valid_pixel_pct: Decimal | None
    time: datetime | None


class GridWorstCellsResponse(BaseModel):
    """GET /api/v1/blocks/{block_id}/grid-cells/worst response.

    Cells with the lowest index mean at the latest (or given) scene,
    ascending — the unhealthiest first. Cells without an observation are
    excluded (no signal to rank on).
    """

    block_id: UUID
    product_id: UUID
    index_code: str
    cells: tuple[GridWorstCell, ...]
    at: datetime | None


class GridCellHistoryPoint(BaseModel):
    time: datetime
    mean: Decimal | None
    min: Decimal | None
    max: Decimal | None
    std_dev: Decimal | None
    valid_pixel_pct: Decimal | None


class GridCellHistoryResponse(BaseModel):
    """GET /api/v1/grid-cells/{cell_id}/history response."""

    cell_id: UUID
    index_code: str
    product_id: UUID
    points: tuple[GridCellHistoryPoint, ...]
