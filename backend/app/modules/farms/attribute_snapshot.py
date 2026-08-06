"""Load a block's crop attribute values for condition evaluation.

Mirrors ``weather.snapshot`` / ``signals.snapshot``: one small loader the
recommendations driver calls per block, returning the flat
``{definition_code: value}`` dict that ``ConditionContext.crop_attributes``
holds and ``{source: crop_attribute}`` refs resolve against.

No definition join. The values already live in typed columns, so the driver
reads ``Decimal`` / ``date`` / ``str`` / ``list[str]`` straight out of the
row — the same objects the evaluator would get from any other source, with no
CAST and no re-parsing of an ISO string (the failure family behind
#331/#332/#335).

Returns ``{}`` for a block with no current crop assignment or no recorded
values, so every ``crop_attribute`` predicate fails closed exactly like the
other sources.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.models import BlockCropAttributeValue

# Order matters only in that exactly one is non-null per row (enforced by the
# one_value CHECK in tenant migration 0055); the first hit is the value.
_VALUE_COLUMNS = (
    "value_numeric",
    "value_text",
    "value_boolean",
    "value_date",
    "value_option",
    "value_options",
)


async def load_crop_attribute_snapshot(
    session: AsyncSession, *, block_crop_id: UUID | None
) -> dict[str, Any]:
    """``{definition_code: typed value}`` for one crop assignment."""
    if block_crop_id is None:
        return {}
    rows = (
        (
            await session.execute(
                select(BlockCropAttributeValue).where(
                    BlockCropAttributeValue.block_crop_id == block_crop_id,
                    BlockCropAttributeValue.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    snapshot: dict[str, Any] = {}
    for row in rows:
        for column in _VALUE_COLUMNS:
            value = getattr(row, column)
            if value is not None:
                snapshot[row.definition_code] = value
                break
    return snapshot
