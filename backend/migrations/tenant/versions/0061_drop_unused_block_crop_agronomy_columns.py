"""Drop the five ``block_crops`` columns nothing ever wrote.

``expected_harvest_start``, ``expected_harvest_end``, ``plant_density_per_ha``,
``row_spacing_m`` and ``plant_spacing_m`` shipped with the original farms
schema (0002) and have been dead ever since: no surface in the product ever
rendered an input for them. They reached the API only as optional fields on
the assign payload, so the only way to set one was to hand-write JSON.

They are not part of what a crop-block assignment is meant to carry. Anything
a tenant genuinely needs here belongs in the crop-attribute system, which is
per-crop, typed, gated and reportable — a fixed column that is right for mango
and meaningless for wheat is the shape this schema is supposed to avoid. The
five codes are released from ``RESERVED_ATTRIBUTE_CODES`` in the same change,
so a tenant that wants "row spacing" can now author it there.

**Data checked before writing this.** Every crop-assignment row in production
was read through the API immediately before this migration was authored: 8
rows across 3 farms / 76 blocks, with **zero** non-null values in all five
columns. Nothing is lost.

``actual_harvest_date`` is deliberately KEPT — it records a real event and
stays both a column and a reserved code.

**Irreversible in practice.** The downgrade re-adds the columns so the schema
shape round-trips, but any values that existed are gone. That is the accepted
trade here precisely because the pre-flight showed there are none.

Revision ID: 0061
Revises: 0060
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (name, type) — one list drives both directions so they cannot drift.
_COLUMNS: list[tuple[str, sa.types.TypeEngine[object]]] = [
    ("expected_harvest_start", sa.Date()),
    ("expected_harvest_end", sa.Date()),
    ("plant_density_per_ha", sa.Numeric(8, 2)),
    ("row_spacing_m", sa.Numeric(5, 2)),
    ("plant_spacing_m", sa.Numeric(5, 2)),
]


def upgrade() -> None:
    for name, _type in _COLUMNS:
        op.drop_column("block_crops", name)


def downgrade() -> None:
    # Shape only. The values are not recoverable from here; restore from a
    # backup if a tenant ever turns out to have had some.
    for name, type_ in _COLUMNS:
        op.add_column("block_crops", sa.Column(name, type_, nullable=True))
