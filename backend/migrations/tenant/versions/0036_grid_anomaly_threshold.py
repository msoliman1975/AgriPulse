"""Per-block grid anomaly z-score threshold override (G-3).

Adds a nullable ``anomaly_z_threshold`` column to ``grid_configs``. NULL
means "inherit" — the sweep falls through to the tenant override
(``tenant_settings_overrides['grid.anomaly_z_threshold']``) and then the
platform default seeded in the public migration. A non-null value lets a
chronically noisy block be tuned independently of its peers.

The detector is self-normalising (z-score vs each block's own cell
distribution), so the threshold means roughly the same thing across
crops; the per-block knob is for outlier blocks, not routine tuning.

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grid_configs",
        sa.Column("anomaly_z_threshold", sa.Numeric(4, 2), nullable=True),
    )
    # Mirror the platform default's lower bound so a per-block override
    # can't be set to a nonsensical non-positive k.
    op.create_check_constraint(
        "ck_grid_configs_anomaly_z_positive",
        "grid_configs",
        "anomaly_z_threshold IS NULL OR anomaly_z_threshold > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_grid_configs_anomaly_z_positive", "grid_configs", type_="check"
    )
    op.drop_column("grid_configs", "anomaly_z_threshold")
