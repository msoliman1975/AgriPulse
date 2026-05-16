"""Farm-block config model — PR-1 foundation.

Mechanical schema changes only, no behavior change:
  * Farm-only adds  : ``farm_manager_id``, ``default_irrigation_system``,
                      ``default_irrigation_source``,
                      ``default_flow_rate_m3_per_hour``, ``default_tags``,
                      and three lock booleans
                      (``subscriptions_locked``, ``irrigation_locked``,
                      ``org_locked``).
  * Block rename    : ``responsible_user_id`` → ``agronomist_id``.

See ``docs/proposals/farm-block-config-model.md`` for the design.
The Subscriptions template table move and the lock-enforcement service
layer arrive in 0028 (PR-2) and PR-3 respectively; this migration adds
storage only.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- farms: Farm-only people field + Shared templates + locks -----
    op.add_column(
        "farms",
        sa.Column("farm_manager_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column("default_irrigation_system", sa.Text(), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column("default_irrigation_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column(
            "default_flow_rate_m3_per_hour",
            sa.Numeric(8, 2),
            nullable=True,
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "default_tags",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "subscriptions_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "irrigation_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "farms",
        sa.Column(
            "org_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )

    # ---- blocks: rename responsible_user_id → agronomist_id -----------
    op.alter_column(
        "blocks",
        "responsible_user_id",
        new_column_name="agronomist_id",
    )


def downgrade() -> None:
    op.alter_column(
        "blocks",
        "agronomist_id",
        new_column_name="responsible_user_id",
    )

    op.drop_column("farms", "org_locked")
    op.drop_column("farms", "irrigation_locked")
    op.drop_column("farms", "subscriptions_locked")
    op.drop_column("farms", "default_tags")
    op.drop_column("farms", "default_flow_rate_m3_per_hour")
    op.drop_column("farms", "default_irrigation_source")
    op.drop_column("farms", "default_irrigation_system")
    op.drop_column("farms", "farm_manager_id")
