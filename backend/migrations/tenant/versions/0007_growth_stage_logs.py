"""growth_stage_logs — append-only history of phenology transitions.

PR-3 of FarmDM rollout. Today's `block_crops.growth_stage` is *current
state only*: changing it overwrites the prior value with no history.
This migration adds a dedicated log so the timeline (when did this
block enter flowering, who confirmed it, was it derived from a model
or manually marked) is persistent and auditable.

Shape:

  * `block_id` FK + ON DELETE CASCADE — clearing a block also clears
    its history. Cascading is the right call here because the logs
    are intrinsic to the block; preserving orphaned rows would not be
    informative.
  * `block_crop_id` FK + ON DELETE CASCADE, nullable — links to the
    crop assignment that the transition belonged to. Nullable so a
    transition can be recorded before a crop is formally assigned
    (rare, but the data model shouldn't make that impossible).
  * `source` CHECK in (`manual`, `derived`, `imported`). `manual` is
    a user-initiated entry; `derived` is set by a future phenology
    model that watches GDD; `imported` covers backfills.
  * `confirmed_by` is a logical cross-schema FK to `public.users.id`
    (data_model § 5.5 explains why we don't enforce these in DB).
  * `transition_date` is the agronomic event time, not the row's
    `created_at`. Defaults to `now()` for the manual path; the
    derived/imported paths can specify historical dates.

Indexes:
  * `(block_id, transition_date DESC)` — primary read path (timeline).
  * `(block_crop_id)` partial — joins from a specific crop assignment.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "growth_stage_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "block_crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("block_crops.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "confirmed_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "transition_date",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # Audit columns matching TimestampedMixin's shape.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_growth_stage_logs_source",
        "growth_stage_logs",
        "source IN ('manual', 'derived', 'imported')",
    )
    op.create_index(
        "ix_growth_stage_logs_block_transition_desc",
        "growth_stage_logs",
        ["block_id", sa.text("transition_date DESC")],
    )
    op.create_index(
        "ix_growth_stage_logs_block_crop",
        "growth_stage_logs",
        ["block_crop_id"],
        postgresql_where=sa.text("block_crop_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_growth_stage_logs_block_crop", table_name="growth_stage_logs")
    op.drop_index("ix_growth_stage_logs_block_transition_desc", table_name="growth_stage_logs")
    op.drop_table("growth_stage_logs")
