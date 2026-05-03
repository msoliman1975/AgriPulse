"""Async DB access for the indices module. Internal to the module.

Two operations:

  * `upsert_aggregate_row` — called by the imagery pipeline's
    `compute_indices` task. Idempotent: re-running with the same
    `(time, block_id, index_code, product_id)` is a no-op (PR-A's
    UNIQUE constraint catches conflicts).
  * `get_timeseries` — reads from `block_index_daily` /
    `block_index_weekly` (the continuous aggregates), bucketed and
    bounded by the requested time window.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Granularity → CAGG view name. Mapping is closed; new granularities
# require a new continuous aggregate (a migration), so we don't take
# user-supplied SQL identifiers anywhere.
_GRANULARITY_VIEW: dict[str, str] = {
    "daily": "block_index_daily",
    "weekly": "block_index_weekly",
}

# Granularity → bucket-time column name (the `time_bucket(...)` alias
# in each CAGG's SELECT).
_GRANULARITY_TIME_COLUMN: dict[str, str] = {
    "daily": "day",
    "weekly": "week",
}


class IndicesRepository:
    """Internal repository — service layer is the only consumer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_aggregate_row(
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
        """Insert one row into block_index_aggregates; idempotent on rerun.

        ``valid_pixel_pct`` is GENERATED in the DB so we don't pass it.
        Conflict on the unique key is a no-op — re-running computation
        for the same scene must not produce a duplicate row.
        """
        await self._session.execute(
            text(
                """
                INSERT INTO block_index_aggregates (
                    time, block_id, index_code, product_id,
                    mean, "min", "max", p10, p50, p90, std_dev,
                    valid_pixel_count, total_pixel_count,
                    cloud_cover_pct, stac_item_id
                ) VALUES (
                    :time, :block_id, :index_code, :product_id,
                    :mean, :min_value, :max_value, :p10, :p50, :p90, :std_dev,
                    :valid_pixel_count, :total_pixel_count,
                    :cloud_cover_pct, :stac_item_id
                )
                ON CONFLICT (time, block_id, index_code, product_id)
                DO NOTHING
                """
            ).bindparams(
                bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                bindparam("product_id", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "time": time,
                "block_id": block_id,
                "index_code": index_code,
                "product_id": product_id,
                "mean": mean,
                "min_value": min_value,
                "max_value": max_value,
                "p10": p10,
                "p50": p50,
                "p90": p90,
                "std_dev": std_dev,
                "valid_pixel_count": valid_pixel_count,
                "total_pixel_count": total_pixel_count,
                "cloud_cover_pct": cloud_cover_pct,
                "stac_item_id": stac_item_id,
            },
        )
        await self._session.flush()

    async def get_timeseries(
        self,
        *,
        block_id: UUID,
        index_code: str,
        granularity: str,
        from_datetime: datetime | None,
        to_datetime: datetime | None,
    ) -> tuple[dict[str, Any], ...]:
        """Read bucketed mean/min/max from the daily or weekly CAGG.

        With migration 0004's ``materialized_only=false``, freshly
        inserted hypertable rows show up immediately — the query
        merges materialised buckets with the live hypertable.
        """
        if granularity not in _GRANULARITY_VIEW:
            raise ValueError(f"Unknown granularity: {granularity!r}")
        view = _GRANULARITY_VIEW[granularity]
        time_col = _GRANULARITY_TIME_COLUMN[granularity]

        clauses = [
            f'"{view}".block_id = :block_id',
            f'"{view}".index_code = :index_code',
        ]
        params: dict[str, Any] = {
            "block_id": block_id,
            "index_code": index_code,
        }
        if from_datetime is not None:
            clauses.append(f'"{view}".{time_col} >= :from_dt')
            params["from_dt"] = from_datetime
        if to_datetime is not None:
            clauses.append(f'"{view}".{time_col} <= :to_dt')
            params["to_dt"] = to_datetime
        where_sql = " AND ".join(clauses)

        # Daily CAGG exposes valid_pixels + valid_pct columns; weekly
        # CAGG exposes std_of_means rather than valid_pixels. We surface
        # a unified shape with NULL where the underlying view doesn't
        # carry that field.
        if granularity == "daily":
            select_extra = (
                ', "min", "max", valid_pixels::INTEGER AS valid_pixels, '
                "valid_pct AS valid_pixel_pct"
            )
        else:
            select_extra = (
                ", NULL::NUMERIC(7,4) AS min, "
                "NULL::NUMERIC(7,4) AS max, "
                "NULL::INTEGER AS valid_pixels, "
                "NULL::NUMERIC(5,2) AS valid_pixel_pct"
            )

        # `view`, `time_col`, and `select_extra` are derived from the
        # closed-set granularity → CAGG mapping at the top of this
        # module — never user input. `where_sql` is composed of
        # whitelisted columns below; values bind through `params`.
        sql = " ".join(
            (
                f"SELECT {time_col} AS bucket_time, mean",
                select_extra,
                f'FROM "{view}"',
                "WHERE",
                where_sql,
                f"ORDER BY {time_col} ASC",
            )
        )
        rows = (
            (
                await self._session.execute(
                    text(sql).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)

    async def list_catalog(self) -> tuple[dict[str, Any], ...]:
        """Read public.indices_catalog for /api/v1/config and the
        timeseries endpoint's bounds-aware response.
        """
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT id, code, name_en, name_ar, formula_text, "
                        "value_min, value_max, physical_meaning, is_standard "
                        "FROM public.indices_catalog "
                        "WHERE deleted_at IS NULL "
                        "ORDER BY code"
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(dict(r) for r in rows)
