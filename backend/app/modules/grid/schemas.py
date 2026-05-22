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
