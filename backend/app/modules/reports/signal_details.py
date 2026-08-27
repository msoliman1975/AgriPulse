"""Signal-details report — the filtered query and its roll-up.

Split out of ``service.py`` because it is the only report whose rows are
observations rather than blocks, so it carries a filter set nothing else
shares: nine optional predicates over one hypertable, plus a per-signal
summary that has to branch on ``value_kind``.

Every other report collapses signals to one value per block. That collapse
cannot answer the question this report exists for — what the scouts actually
recorded, who recorded it, and what they wrote in the notes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric as SANumeric
from sqlalchemy.types import Text as SAText

from .schemas import SignalDetailCategoryCount, SignalDetailRow, SignalDetailStat

# Row cap for the table. High enough that a season of scouting on one farm
# fits — a 40-block farm logging 3 signals weekly is ~1,500 rows a quarter —
# and low enough that the response stays a page rather than a data dump.
SIGNAL_DETAIL_LIMIT = 2000

# How many categorical values a per-signal breakdown lists. Past this the
# breakdown stops being a summary; the table underneath carries the rest.
TOP_CATEGORIES = 8

# Values `location_mode` may take, mirroring the CHECK in tenant migration
# 0029. Restated here so the filter can be validated before it reaches SQL.
LOCATION_MODES: tuple[str, ...] = ("entity", "point_in_entity", "free_point")


async def select_signal_details(
    session: AsyncSession,
    *,
    farm_id: UUID,
    since: datetime,
    until: datetime,
    signal_codes: list[str],
    block_ids: list[UUID],
    categorical_values: list[str],
    min_value: Decimal | None,
    max_value: Decimal | None,
    recorded_by: UUID | None,
    location_mode: str | None,
    with_notes_only: bool,
    with_attachment_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """Filtered observations for a farm, newest first.

    Three ``LEFT JOIN``s, each deliberate:

    * **blocks** — a farm-level observation has no block, and the
      ``deleted_at IS NULL`` predicate sits in the ON clause rather than the
      WHERE. An observation on a since-deleted block still happened; moving
      that test to the WHERE would silently shrink a historical report.
    * **block_crops** — the crop context is a nicety, and a block with no
      current assignment must still list its readings.
    * **public.users** — ``recorded_by`` is a logical cross-schema reference
      with no FK, so a purged user costs the display name, not the row.

    Every filter binds as a real typed parameter, and the numeric bounds
    compare against ``value_numeric`` rather than a cast of a text value (the
    #331/#332/#335 family).
    """
    clauses: list[str] = []
    binds: list[Any] = [bindparam("farm_id", type_=PG_UUID(as_uuid=True))]
    params: dict[str, Any] = {
        "farm_id": farm_id,
        "since": since,
        "until": until,
        "limit": limit,
    }

    if signal_codes:
        clauses.append("AND d.code = ANY(:signal_codes)")
        binds.append(bindparam("signal_codes", type_=PG_ARRAY(SAText())))
        params["signal_codes"] = signal_codes
    if block_ids:
        clauses.append("AND o.block_id = ANY(:block_ids)")
        binds.append(bindparam("block_ids", type_=PG_ARRAY(PG_UUID(as_uuid=True))))
        params["block_ids"] = block_ids
    if categorical_values:
        # Covers the categorical and event kinds together: they land in
        # different columns but read as one "which option was it" filter.
        clauses.append(
            "AND (o.value_categorical = ANY(:categorical_values)"
            " OR o.value_event = ANY(:categorical_values))"
        )
        binds.append(bindparam("categorical_values", type_=PG_ARRAY(SAText())))
        params["categorical_values"] = categorical_values
    if min_value is not None:
        clauses.append("AND o.value_numeric >= :min_value")
        binds.append(bindparam("min_value", type_=SANumeric(14, 4)))
        params["min_value"] = min_value
    if max_value is not None:
        clauses.append("AND o.value_numeric <= :max_value")
        binds.append(bindparam("max_value", type_=SANumeric(14, 4)))
        params["max_value"] = max_value
    if recorded_by is not None:
        clauses.append("AND o.recorded_by = :recorded_by")
        binds.append(bindparam("recorded_by", type_=PG_UUID(as_uuid=True)))
        params["recorded_by"] = recorded_by
    if location_mode is not None:
        clauses.append("AND o.location_mode = :location_mode")
        binds.append(bindparam("location_mode", type_=SAText()))
        params["location_mode"] = location_mode
    if with_notes_only:
        clauses.append("AND o.notes IS NOT NULL AND btrim(o.notes) <> :empty")
        binds.append(bindparam("empty", type_=SAText()))
        params["empty"] = ""
    if with_attachment_only:
        clauses.append("AND o.attachment_s3_key IS NOT NULL")

    sql = text(
        f"""
        SELECT o.id, o.time AS observed_at, o.inserted_at AS recorded_at,
               d.code AS signal_code, d.name AS signal_name,
               d.name_ar AS signal_name_ar,
               d.value_kind, d.unit, d.unit_ar,
               d.categorical_values, d.categorical_values_ar,
               o.value_numeric, o.value_categorical, o.value_event, o.value_boolean,
               o.block_id, b.name AS block_name, b.name_ar AS block_name_ar,
               bc.crop_path,
               o.notes, o.recorded_by, u.full_name AS recorded_by_name,
               u.full_name_ar AS recorded_by_name_ar,
               o.location_mode, o.attachment_s3_key,
               o.template_observation_id, o.import_batch_id
        FROM signal_observations o
        JOIN public.signal_definitions d ON d.id = o.signal_definition_id
        LEFT JOIN blocks b ON b.id = o.block_id AND b.deleted_at IS NULL
        LEFT JOIN block_crops bc
               ON bc.block_id = o.block_id
              AND bc.deleted_at IS NULL
              AND bc.is_current IS TRUE
        LEFT JOIN public.users u ON u.id = o.recorded_by
        WHERE o.farm_id = :farm_id
          AND o.time >= :since
          AND o.time < :until
          {" ".join(clauses)}
        ORDER BY o.time DESC, o.id DESC
        LIMIT :limit
        """
    ).bindparams(*binds)

    rows = (await session.execute(sql, params)).mappings().all()
    return [dict(row) for row in rows]


def signal_detail_stats(rows: list[SignalDetailRow]) -> list[SignalDetailStat]:
    """Per-signal roll-up over the rows the filters returned.

    Numeric statistics come out only for a ``numeric`` signal; every other kind
    gets a value breakdown instead. Mixing the two — a "mean" over booleans
    coerced to 0/1 — would put a number under a heading where no number means
    anything.
    """
    grouped: dict[str, list[SignalDetailRow]] = {}
    for row in rows:
        grouped.setdefault(row.signal_code, []).append(row)

    stats: list[SignalDetailStat] = []
    for code, group in grouped.items():
        head = group[0]
        times = [r.observed_at for r in group]
        numbers = [r.value_numeric for r in group if r.value_numeric is not None]

        categories: list[SignalDetailCategoryCount] = []
        if head.value_kind != "numeric":
            counts: dict[str, int] = {}
            for row in group:
                label = row.value_categorical or row.value_event
                if label is None and row.value_boolean is not None:
                    label = "true" if row.value_boolean else "false"
                if label is None:
                    continue
                counts[label] = counts.get(label, 0) + 1
            categories = [
                SignalDetailCategoryCount(value=value, count=count)
                # Count descending, then value ascending, so an equal-count tie
                # renders in a stable order rather than in dict order.
                for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ][:TOP_CATEGORIES]

        stats.append(
            SignalDetailStat(
                signal_code=code,
                signal_name=head.signal_name,
                signal_name_ar=head.signal_name_ar,
                value_kind=head.value_kind,
                unit=head.unit,
                observation_count=len(group),
                block_count=len({r.block_id for r in group if r.block_id is not None}),
                recorder_count=len({r.recorded_by for r in group}),
                first_observed_at=min(times),
                last_observed_at=max(times),
                min_value=min(numbers) if numbers else None,
                mean_value=(
                    (sum(numbers, Decimal(0)) / len(numbers)).quantize(Decimal("0.0001"))
                    if numbers
                    else None
                ),
                max_value=max(numbers) if numbers else None,
                categories=categories,
            )
        )

    # Busiest signal first: the reader is usually after the one with the most
    # readings behind it.
    stats.sort(key=lambda s: (-s.observation_count, s.signal_name.lower()))
    return stats
