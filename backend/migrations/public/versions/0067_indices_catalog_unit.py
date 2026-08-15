"""Give `indices_catalog` a unit, because LST is degrees Celsius.

Every index seeded before 0066 is a dimensionless ratio — a normalized
difference in [-1, 1], or `msi`'s plain band ratio in roughly [0, 3].
Nothing needed a unit, so the table never had one, and the SPA could
safely render an index value as a bare number.

`lst` breaks that. It is a physical temperature, and a chart axis or
tooltip that prints `31.85` without saying `°C` is not merely terse, it
is ambiguous with every other index on the same screen.

The column mirrors `public.weather_indices_catalog.unit`, which has
carried exactly this since 0009: a single NOT NULL text column holding
a display string (`'mm'`, `'°C·day'`), not a localised pair. The SPA
already renders that one directly as ```${value.toFixed(1)} ${unit}```,
so an empty string is the honest "dimensionless" value and needs no
special case at the call site. Deliberately NOT `unit_en`/`unit_ar`:
`crop_attribute_definitions` has that shape, but it describes
user-authored agronomic attributes whose units are prose. These are
symbols.

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Only `lst` carries one. `cwsi` and `smi` are 0-1 indices by
# construction, so they stay dimensionless alongside the spectral rows.
_UNITS: tuple[tuple[str, str], ...] = (("lst", "°C"),)


def upgrade() -> None:
    op.add_column(
        "indices_catalog",
        sa.Column("unit", sa.Text(), nullable=False, server_default=sa.text("''")),
        schema="public",
    )
    bind = op.get_bind()
    for code, unit in _UNITS:
        bind.execute(
            sa.text("UPDATE public.indices_catalog SET unit = :unit WHERE code = :code"),
            {"unit": unit, "code": code},
        )


def downgrade() -> None:
    # Data-safe: the column holds display metadata only, and every value
    # is recreated by this migration's upgrade rather than being entered
    # by a user, so dropping it loses nothing that cannot be rebuilt.
    op.drop_column("indices_catalog", "unit", schema="public")
