"""IndicesService Protocol + skeleton implementation.

The imagery pipeline calls `record_aggregate_row(...)` per index per
ingested scene; the API surface calls `get_timeseries(...)`. Both go
through this Protocol so the imagery module never reaches into
indices' tables, and the API surface never reaches into the imagery
module's tables.

PR-A lands the contract; PR-C fills in the bodies (alongside the
`computation.py` library that produces the per-index COGs and stats).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.modules.indices.schemas import (
    IndexCatalogEntry,
    IndexTimeseriesResponse,
    TimeseriesGranularity,
)


class IndicesService(Protocol):
    """Public contract for the indices module."""

    async def list_catalog(self) -> tuple[IndexCatalogEntry, ...]: ...

    async def get_timeseries(
        self,
        *,
        block_id: UUID,
        index_code: str,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        granularity: TimeseriesGranularity = "daily",
    ) -> IndexTimeseriesResponse: ...

    async def record_aggregate_row(
        self,
        *,
        time: datetime,
        block_id: UUID,
        index_code: str,
        product_id: UUID,
        stac_item_id: str,
        mean: Decimal | None,
        min_value: Decimal | None,
        max_value: Decimal | None,
        p10: Decimal | None,
        p50: Decimal | None,
        p90: Decimal | None,
        std_dev: Decimal | None,
        valid_pixel_count: int,
        total_pixel_count: int,
        cloud_cover_pct: Decimal | None,
    ) -> None:
        """Upsert one row into block_index_aggregates.

        Idempotent: re-running with the same
        (time, block_id, index_code, product_id) tuple is a no-op,
        leveraging the unique constraint declared in migration 0003.
        """
        ...


class IndicesServiceImpl:
    """Skeleton — real implementation lands in PR-C."""

    async def list_catalog(self) -> tuple[IndexCatalogEntry, ...]:
        raise NotImplementedError("Implemented in PR-C")

    async def get_timeseries(
        self,
        *,
        block_id: UUID,
        index_code: str,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        granularity: TimeseriesGranularity = "daily",
    ) -> IndexTimeseriesResponse:
        raise NotImplementedError("Implemented in PR-C")

    async def record_aggregate_row(
        self,
        *,
        time: datetime,
        block_id: UUID,
        index_code: str,
        product_id: UUID,
        stac_item_id: str,
        mean: Decimal | None,
        min_value: Decimal | None,
        max_value: Decimal | None,
        p10: Decimal | None,
        p50: Decimal | None,
        p90: Decimal | None,
        std_dev: Decimal | None,
        valid_pixel_count: int,
        total_pixel_count: int,
        cloud_cover_pct: Decimal | None,
    ) -> None:
        raise NotImplementedError("Implemented in PR-C")
