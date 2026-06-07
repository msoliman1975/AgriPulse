"""Public signals snapshot loader.

Builds a dict of ``{signal_code: SignalEntry}`` for one block at a
moment in time. Consumers are the alerts and recommendations services,
which call this once per evaluation pass and embed the result in the
``ConditionContext`` fed to the evaluator.

Public surface — other modules may import this. The internals
(``models``, ``repository``, ``router``, ``schemas``) remain private
per the import-linter contract; this loader uses raw SQL so it doesn't
need to import ``SignalsRepository``.

"Applies to this block" rule (mirrors ``data_model § 9.3``):
  * tenant-wide assignment (``farm_id IS NULL AND block_id IS NULL``)
  * farm-scoped assignment for the block's farm (``farm_id = farm AND
    block_id IS NULL``)
  * block-scoped assignment (``block_id = block``)

CS-6 aggregation:
  Each ``signal_definitions`` row carries an ``aggregation`` mode +
  optional ``aggregation_window_days``. The snapshot collapses
  observations to a single block-level value per signal using the
  rule:

  * ``aggregation = 'count'`` (CS-14) on ANY value_kind → COUNT(*)
    of in-window observations, returned in ``value_numeric``.
  * ``aggregation = 'latest'``, OR a non-numeric def with any rule
    other than count → take the most recent observation's value.
  * ``aggregation ∈ {mean, median, max, min, sum}`` (CS-14 adds sum)
    on a numeric def → GROUP BY signal_definition_id over the window
    (or all history when ``aggregation_window_days IS NULL``), apply
    the SQL aggregate, and report the window-max ``time`` so consumers
    can still answer "how recent is this".

  Non-numeric kinds are forced to ``latest`` by the service-layer
  ``_coerce_aggregation_for_value_kind`` at write time, but we
  belt-and-brace it here so a hand-edited definitions row can't
  bypass the rule and return a nonsensical AVG over text values.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.conditions.context import SignalEntry

# All SQL aggregates collapsed into one CASE so the query stays
# single-pass. PERCENTILE_CONT requires a float ordering expression,
# hence the double-cast; the outer cast back to numeric keeps the
# returned column type uniform with MAX/MIN/AVG (which preserve numeric).
# CS-14: `count` is COUNT(*) (works for any value_kind — it counts rows,
# not values) and `sum` is SUM(value_numeric) (numeric-only).
_AGGREGATE_SQL = """
    CASE a.aggregation
        WHEN 'mean'   THEN AVG(o.value_numeric)
        WHEN 'median' THEN (
            PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY o.value_numeric::double precision)
        )::numeric
        WHEN 'max'    THEN MAX(o.value_numeric)
        WHEN 'min'    THEN MIN(o.value_numeric)
        WHEN 'sum'    THEN SUM(o.value_numeric)
        WHEN 'count'  THEN COUNT(*)::numeric
    END
"""


async def load_snapshot(
    session: AsyncSession,
    *,
    block_id: UUID,
    farm_id: UUID,
) -> dict[str, SignalEntry]:
    """Aggregated observation per applicable signal.

    Signals with no observations in their window are omitted —
    predicates that reference them resolve to ``None`` in the
    evaluator (permissive on missing data).
    """
    # _AGGREGATE_SQL is a module-level constant, not request input;
    # all data params bind through :name placeholders.
    rows = (
        (
            await session.execute(
                text(
                    f"""
                WITH applicable AS (
                    SELECT DISTINCT
                           d.id, d.code, d.value_kind,
                           d.aggregation, d.aggregation_window_days
                    FROM signal_definitions d
                    JOIN signal_assignments a ON a.signal_definition_id = d.id
                    WHERE d.deleted_at IS NULL
                      AND d.is_active = TRUE
                      AND a.deleted_at IS NULL
                      AND a.is_active = TRUE
                      AND (
                            (a.farm_id IS NULL AND a.block_id IS NULL)
                         OR (a.block_id = :block_id)
                         OR (a.farm_id = :farm_id AND a.block_id IS NULL)
                      )
                ),
                -- CS-6: latest-mode rows + every non-numeric value_kind.
                -- DISTINCT ON gives us the most recent observation per
                -- signal_definition_id (ORDER BY DESC then dedupes).
                latest_per_def AS (
                    SELECT DISTINCT ON (o.signal_definition_id)
                           o.signal_definition_id, o.time,
                           o.value_numeric, o.value_categorical,
                           o.value_event, o.value_boolean
                    FROM signal_observations o
                    JOIN applicable a ON a.id = o.signal_definition_id
                    -- latest if explicitly configured, or a non-numeric def
                    -- whose rule coerces to latest (everything except count).
                    WHERE (
                            a.aggregation = 'latest'
                         OR (a.value_kind != 'numeric' AND a.aggregation != 'count')
                      )
                      AND (o.block_id = :block_id OR o.block_id IS NULL)
                      AND o.farm_id = :farm_id
                    ORDER BY o.signal_definition_id, o.time DESC
                ),
                -- CS-6: aggregated rows for numeric defs with a non-
                -- latest rule. NULL aggregation_window_days means
                -- "use all history" — only meaningful for `latest`
                -- but we guard here so a misconfigured row doesn't
                -- silently filter to zero observations.
                aggregated_per_def AS (
                    SELECT o.signal_definition_id,
                           MAX(o.time)  AS time,
                           {_AGGREGATE_SQL} AS value_numeric,
                           NULL::text     AS value_categorical,
                           NULL::text     AS value_event,
                           NULL::boolean  AS value_boolean
                    FROM signal_observations o
                    JOIN applicable a ON a.id = o.signal_definition_id
                    -- numeric non-latest rules, plus `count` on ANY
                    -- value_kind (CS-14 — counts rows via COUNT(*)).
                    WHERE a.aggregation != 'latest'
                      AND (a.value_kind = 'numeric' OR a.aggregation = 'count')
                      AND (o.block_id = :block_id OR o.block_id IS NULL)
                      AND o.farm_id = :farm_id
                      AND (
                          a.aggregation_window_days IS NULL
                          OR o.time >= now()
                                     - make_interval(days => a.aggregation_window_days)
                      )
                    GROUP BY o.signal_definition_id, a.aggregation
                ),
                resolved AS (
                    SELECT * FROM latest_per_def
                    UNION ALL
                    SELECT * FROM aggregated_per_def
                )
                SELECT a.code, r.time, r.value_numeric, r.value_categorical,
                       r.value_event, r.value_boolean
                FROM applicable a
                JOIN resolved r ON r.signal_definition_id = a.id
                """  # noqa: S608 — only interp is the _AGGREGATE_SQL constant
                ).bindparams(
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
                ),
                {"block_id": block_id, "farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        row["code"]: SignalEntry(
            time=row["time"],
            value_numeric=_to_decimal(row["value_numeric"]),
            value_categorical=row["value_categorical"],
            value_event=row["value_event"],
            value_boolean=row["value_boolean"],
        )
        for row in rows
    }


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


_ = datetime  # silence unused-import; re-export-ready for future fields
