"""IndicesService Protocol + concrete impl.

The imagery pipeline calls `record_aggregate_row(...)` per index per
ingested scene; the API surface calls `get_timeseries(...)`. Both go
through this Protocol so the imagery module never reaches into
indices' tables, and the API surface never reaches into the imagery
module's tables.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.indices.repository import IndicesRepository
from app.modules.indices.schemas import (
    IndexCatalogEntry,
    IndexTimeseriesPoint,
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
    ) -> None: ...


class IndicesServiceImpl:
    """Concrete service. One per request — receives a tenant-scoped session."""

    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._session = tenant_session
        self._repo = IndicesRepository(tenant_session)
        self._log = get_logger(__name__)

    async def list_catalog(self) -> tuple[IndexCatalogEntry, ...]:
        rows = await self._repo.list_catalog()
        return tuple(IndexCatalogEntry.model_validate(r) for r in rows)

    async def get_timeseries(
        self,
        *,
        block_id: UUID,
        index_code: str,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        granularity: TimeseriesGranularity = "daily",
    ) -> IndexTimeseriesResponse:
        rows = await self._repo.get_timeseries(
            block_id=block_id,
            index_code=index_code,
            granularity=granularity,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
        )
        points = tuple(
            IndexTimeseriesPoint(
                time=r["bucket_time"],
                mean=r.get("mean"),
                min=r.get("min"),
                max=r.get("max"),
                valid_pixels=r.get("valid_pixels"),
                valid_pixel_pct=r.get("valid_pixel_pct"),
            )
            for r in rows
        )
        return IndexTimeseriesResponse(
            block_id=block_id,
            index_code=index_code,
            granularity=granularity,
            points=points,
        )

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
        await self._repo.upsert_aggregate_row(
            time=time,
            block_id=block_id,
            index_code=index_code,
            product_id=product_id,
            stac_item_id=stac_item_id,
            mean=mean,
            min_value=min_value,
            max_value=max_value,
            p10=p10,
            p50=p50,
            p90=p90,
            std_dev=std_dev,
            valid_pixel_count=valid_pixel_count,
            total_pixel_count=total_pixel_count,
            cloud_cover_pct=cloud_cover_pct,
        )


def get_indices_service(*, tenant_session: AsyncSession) -> IndicesService:
    """Factory used by the router's FastAPI dependency."""
    return IndicesServiceImpl(tenant_session=tenant_session)
