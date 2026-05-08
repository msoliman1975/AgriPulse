"""Pre-loaded data the evaluator reads from.

The service layer (alerts engine driver, future recommendations
evaluator) loads a ``ConditionContext`` once per block per evaluation
pass and hands it to ``evaluate``. Adding a new source means adding a
field here and teaching the relevant value-ref resolver to read it; the
evaluator core stays untouched.

Slice 5 will add ``weather`` and ``signals`` fields backed by the
``weather_*`` and ``signal_*`` tables. Until then those resolvers raise
``DataSourceUnavailable`` so a rule that references them returns
``(False, {})`` rather than spuriously firing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class IndicesEntry:
    """One row pulled from ``block_index_aggregates`` (latest per index)."""

    time: datetime
    mean: Decimal | None
    baseline_deviation: Decimal | None


@dataclass(frozen=True, slots=True)
class ConditionContext:
    """Per-block snapshot the evaluator reads.

    Treat as additive: new fields mean "more rules can be expressed".
    Removing a field is a breaking change for any persisted rule that
    references it.
    """

    block_id: str
    crop_category: str | None = None
    block_attributes: dict[str, Any] = field(default_factory=dict)
    indices: dict[str, IndicesEntry] = field(default_factory=dict)
    # Slice 5 will add: weather: dict[str, Any] | None = None
    # Slice 5 will add: signals: dict[str, Any] | None = None

    @classmethod
    def from_block_signals(
        cls,
        *,
        block_id: str,
        crop_category: str | None,
        latest_index_aggregates: dict[str, dict[str, Any]],
        block_attributes: dict[str, Any] | None = None,
    ) -> ConditionContext:
        """Build a context from the ``BlockSignals`` shape the alerts
        engine already loads. Adapter so the alerts service doesn't
        change signature.
        """
        indices: dict[str, IndicesEntry] = {}
        for code, row in latest_index_aggregates.items():
            indices[code] = IndicesEntry(
                time=row.get("time"),  # type: ignore[arg-type]
                mean=_to_decimal(row.get("mean")),
                baseline_deviation=_to_decimal(row.get("baseline_deviation")),
            )
        return cls(
            block_id=block_id,
            crop_category=crop_category,
            block_attributes=dict(block_attributes or {}),
            indices=indices,
        )


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
