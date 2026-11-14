"""The reference values a tree walk reads for one crop path (D18).

Kept beside the keys so the evaluator's view of a crop is the same as the
catalogue screen's: the same rows, the same deepest-path-wins resolution.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference_values.keys import resolve

_FIELDS = ("value", "value_min", "value_max")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


async def load_reference_snapshot(
    public_session: AsyncSession, *, crop_path: str | None
) -> dict[str, dict[str, Decimal | None]]:
    """``{key: {"value", "value_min", "value_max"}}`` for ``crop_path``.

    Empty for a block with no crop, so a ``{source: reference}`` predicate
    fails closed like every other missing source.
    """
    if not crop_path:
        return {}
    segments = [s for s in crop_path.split(".") if s]
    chain = [".".join(segments[: i + 1]) for i in range(len(segments))]
    rows = await public_session.execute(
        text(
            "SELECT crop_path, key, value, value_min, value_max "
            "FROM public.crop_reference_values WHERE crop_path = ANY(:chain)"
        ),
        {"chain": chain},
    )
    resolved = resolve(crop_path, [dict(r._mapping) for r in rows])
    return {key: {f: _decimal(entry.get(f)) for f in _FIELDS} for key, entry in resolved.items()}
