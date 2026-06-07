"""Allow `count` and `sum` aggregation modes on signal definitions (CS-14).

The 0029 CHECK constraint pinned ``signal_definitions.aggregation`` to
{latest, mean, median, max, min}. CS-14 adds ``count`` (valid for any
value_kind — counts observations) and ``sum`` (numeric-only). This just
widens the CHECK; no data migration is needed since existing rows already
hold one of the prior values.

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | Sequence[str] | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VALUES = ("latest", "mean", "median", "max", "min")
_NEW_VALUES = ("latest", "mean", "median", "max", "min", "count", "sum")
_CONSTRAINT = "ck_signal_definitions_aggregation"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "signal_definitions", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "signal_definitions",
        f"aggregation IN {_NEW_VALUES!r}",
    )


def downgrade() -> None:
    # Any rows already using count/sum would violate the old CHECK; reset
    # them to `latest` so the constraint can be re-applied cleanly.
    op.execute(
        "UPDATE signal_definitions SET aggregation = 'latest' "
        "WHERE aggregation IN ('count', 'sum')"
    )
    op.drop_constraint(_CONSTRAINT, "signal_definitions", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "signal_definitions",
        f"aggregation IN {_OLD_VALUES!r}",
    )
