"""Farm-level grid template — cell size + anomaly threshold + lock.

Fourth category in the farm→block config model (see
``docs/proposals/bulk-grid-config-and-valid-time.md`` § B1). Single-row
template on ``farms``, mirroring the Irrigation category's shape rather
than the multi-row Subscriptions one: a farm has exactly one desired
cell size and one desired detection sensitivity.

Both value columns are nullable and NULL means **no template set** —
there is nothing to apply, and Apply is a no-op rather than an
overwrite-with-NULL. That distinction matters: "clear the block's
override so it inherits the tenant default" is a separate explicit
action on the apply request, not something you express by emptying the
template.

Note the template is **not** a resolution tier. The z-threshold already
resolves block → tenant → platform (migration 0036 here + public 0026);
this template is copy-on-apply and writes into
``grid_configs.anomaly_z_threshold``, consistent with the rest of the
config model.

``default_grid_cell_size_m`` is deliberately NOT validated against any
product's native pixel here — the floor depends on which product each
block is subscribed to, and the ≤5000-cell ceiling depends on the
block's own area. Both are enforced per (block, product) at apply time
by ``grid.geometry.validate_cell_size``. A farm template that no block
can satisfy is a legitimate intermediate state.

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column("default_grid_cell_size_m", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column("default_anomaly_z_threshold", sa.Numeric(4, 2), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column(
            "grid_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    # Mirrors ck_grid_configs_anomaly_z_positive (0036) so the template
    # can't hold a value the block-side column would reject.
    op.create_check_constraint(
        "ck_farms_default_anomaly_z_positive",
        "farms",
        "default_anomaly_z_threshold IS NULL OR default_anomaly_z_threshold > 0",
    )
    op.create_check_constraint(
        "ck_farms_default_grid_cell_size_positive",
        "farms",
        "default_grid_cell_size_m IS NULL OR default_grid_cell_size_m > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_farms_default_grid_cell_size_positive", "farms", type_="check")
    op.drop_constraint("ck_farms_default_anomaly_z_positive", "farms", type_="check")
    op.drop_column("farms", "grid_locked")
    op.drop_column("farms", "default_anomaly_z_threshold")
    op.drop_column("farms", "default_grid_cell_size_m")
