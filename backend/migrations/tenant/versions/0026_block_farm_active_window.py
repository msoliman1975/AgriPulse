"""Replace farms/blocks status enums with active_from / active_to date windows.

Land-units PR-1.

Inactivation now records *when* a row stopped being operational
instead of carrying an enum value. The `is_active` predicate becomes
`(active_from <= current_date) AND (active_to IS NULL OR active_to >
current_date) AND deleted_at IS NULL`. `deleted_at` stays in lock-step
with `active_to` for backward compatibility with existing
`WHERE deleted_at IS NULL` filters across the codebase; later PRs can
drop the column once nothing reads it.

Backfill rules:
  * `active_from = created_at::date` for every row.
  * `active_to = COALESCE(deleted_at::date, updated_at::date,
    current_date)` for rows previously flagged `status = 'archived'`
    or carrying `deleted_at IS NOT NULL`.
  * The other historical block states (fallow / abandoned /
    under_preparation) become `active_to = NULL` per product
    direction — they were operational labels, not lifecycle states.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- farms ---------------------------------------------------------
    op.add_column(
        "farms",
        sa.Column("active_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "farms",
        sa.Column("active_to", sa.Date(), nullable=True),
    )
    # Backfill from created_at / status / deleted_at before tightening
    # NOT NULL and dropping status.
    op.execute(
        """
        UPDATE farms
        SET active_from = created_at::date
        """
    )
    op.execute(
        """
        UPDATE farms
        SET active_to = COALESCE(deleted_at::date, updated_at::date, current_date)
        WHERE status = 'archived' OR deleted_at IS NOT NULL
        """
    )
    op.alter_column(
        "farms",
        "active_from",
        nullable=False,
        server_default=sa.text("current_date"),
    )
    op.create_check_constraint(
        "ck_farms_active_window",
        "farms",
        "active_to IS NULL OR active_to >= active_from",
    )
    op.create_index(
        "ix_farms_active_to",
        "farms",
        ["active_to"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Drop the legacy status apparatus.
    op.drop_index("ix_farms_status_active", table_name="farms")
    op.drop_constraint("ck_farms_status", "farms", type_="check")
    op.drop_column("farms", "status")

    # ---- blocks --------------------------------------------------------
    op.add_column(
        "blocks",
        sa.Column("active_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "blocks",
        sa.Column("active_to", sa.Date(), nullable=True),
    )
    op.execute(
        """
        UPDATE blocks
        SET active_from = created_at::date
        """
    )
    op.execute(
        """
        UPDATE blocks
        SET active_to = COALESCE(deleted_at::date, updated_at::date, current_date)
        WHERE status = 'archived' OR deleted_at IS NOT NULL
        """
    )
    op.alter_column(
        "blocks",
        "active_from",
        nullable=False,
        server_default=sa.text("current_date"),
    )
    op.create_check_constraint(
        "ck_blocks_active_window",
        "blocks",
        "active_to IS NULL OR active_to >= active_from",
    )
    op.create_index(
        "ix_blocks_active_to",
        "blocks",
        ["active_to"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_blocks_status_active", table_name="blocks")
    op.drop_constraint("ck_blocks_status", "blocks", type_="check")
    op.drop_column("blocks", "status")


def downgrade() -> None:
    # ---- blocks --------------------------------------------------------
    op.add_column(
        "blocks",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.execute(
        """
        UPDATE blocks
        SET status = CASE
            WHEN active_to IS NOT NULL AND active_to <= current_date THEN 'archived'
            ELSE 'active'
        END
        """
    )
    op.create_check_constraint(
        "ck_blocks_status",
        "blocks",
        "status IN ('active','fallow','abandoned','under_preparation','archived')",
    )
    op.create_index(
        "ix_blocks_status_active",
        "blocks",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_blocks_active_to", table_name="blocks")
    op.drop_constraint("ck_blocks_active_window", "blocks", type_="check")
    op.drop_column("blocks", "active_to")
    op.drop_column("blocks", "active_from")

    # ---- farms ---------------------------------------------------------
    op.add_column(
        "farms",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.execute(
        """
        UPDATE farms
        SET status = CASE
            WHEN active_to IS NOT NULL AND active_to <= current_date THEN 'archived'
            ELSE 'active'
        END
        """
    )
    op.create_check_constraint(
        "ck_farms_status",
        "farms",
        "status IN ('active','archived')",
    )
    op.create_index(
        "ix_farms_status_active",
        "farms",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_farms_active_to", table_name="farms")
    op.drop_constraint("ck_farms_active_window", "farms", type_="check")
    op.drop_column("farms", "active_to")
    op.drop_column("farms", "active_from")
