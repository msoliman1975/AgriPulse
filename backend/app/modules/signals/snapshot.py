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


async def load_snapshot(
    session: AsyncSession,
    *,
    block_id: UUID,
    farm_id: UUID,
) -> dict[str, SignalEntry]:
    """Latest observation per applicable signal.

    Signals with no observations yet are omitted — predicates that
    reference them resolve to ``None`` in the evaluator (permissive
    on missing data).
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                WITH applicable AS (
                    SELECT DISTINCT d.id, d.code
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
                latest AS (
                    SELECT DISTINCT ON (o.signal_definition_id)
                           o.signal_definition_id, o.time,
                           o.value_numeric, o.value_categorical,
                           o.value_event, o.value_boolean
                    FROM signal_observations o
                    WHERE o.signal_definition_id IN (SELECT id FROM applicable)
                      AND (o.block_id = :block_id OR o.block_id IS NULL)
                      AND o.farm_id = :farm_id
                    ORDER BY o.signal_definition_id, o.time DESC
                )
                SELECT a.code, l.time, l.value_numeric, l.value_categorical,
                       l.value_event, l.value_boolean
                FROM applicable a
                JOIN latest l ON l.signal_definition_id = a.id
                """
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
