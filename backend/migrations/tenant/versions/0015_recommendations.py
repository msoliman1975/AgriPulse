"""recommendations + recommendations_history — tenant side of the
recommendations engine.

Counterpart to public migration 0015 (decision_trees catalog). Two
tables:

  * `recommendations` — generated decision-tree outcomes. State machine:
    open → applied | dismissed | deferred | expired. Partial UNIQUE on
    `(block_id, tree_id) WHERE state='open'` keeps the daily evaluator
    idempotent — re-running while a prior recommendation is still open
    is a no-op.
  * `recommendations_history` — state transitions for explainability and
    future ML training. Regular table for now; the data_model spec
    promotes this to a hypertable later (chunk 30d, retention indefinite).

Like alerts, the FK on `block_id` cascades; recommendations on a
deleted block disappear with it.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
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
        # Denormalised so list pages can filter by farm without joining
        # blocks. Matches the same pattern as alerts → block-only.
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Logical FK to public.decision_trees.id (cross-schema, not
        # enforced — same trade-off as alerts.rule_code → public.default_rules).
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_code", sa.Text(), nullable=False),
        sa.Column("tree_version", sa.Integer(), nullable=False),
        sa.Column("block_crop_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'info'"),
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        # Array of node IDs visited during evaluation, in traversal
        # order. Renders the "why" path on the recommendations detail
        # page. JSONB so we can store the per-node label/snapshot
        # alongside the id without schema gymnastics.
        sa.Column("tree_path", postgresql.JSONB(), nullable=False),
        sa.Column("text_en", sa.Text(), nullable=False),
        sa.Column("text_ar", sa.Text(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("evaluation_snapshot", postgresql.JSONB(), nullable=False),
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
        "ck_recommendations_state",
        "recommendations",
        "state IN ('open', 'applied', 'dismissed', 'deferred', 'expired')",
    )
    op.create_check_constraint(
        "ck_recommendations_severity",
        "recommendations",
        "severity IN ('info', 'warning', 'critical')",
    )
    op.create_check_constraint(
        "ck_recommendations_action_type",
        "recommendations",
        (
            "action_type IN ('irrigate','fertilize','spray','scout',"
            "'harvest_window','prune','no_action','other')"
        ),
    )
    op.create_check_constraint(
        "ck_recommendations_confidence",
        "recommendations",
        "confidence >= 0 AND confidence <= 1",
    )
    # Idempotency for the daily evaluator: one open recommendation per
    # (block, tree) at a time. The same tree can fire again once the
    # previous recommendation transitions out of 'open'.
    op.create_index(
        "uq_recommendations_block_tree_open",
        "recommendations",
        ["block_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index(
        "ix_recommendations_block_state_created",
        "recommendations",
        ["block_id", "state", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_recommendations_farm_state",
        "recommendations",
        ["farm_id", "state", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_recommendations_action_state",
        "recommendations",
        ["action_type", "state"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "recommendations_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_recommendations_history_rec_time",
        "recommendations_history",
        ["recommendation_id", sa.text("time DESC")],
    )
    op.create_index(
        "ix_recommendations_history_block_time",
        "recommendations_history",
        ["block_id", sa.text("time DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendations_history_block_time",
        table_name="recommendations_history",
    )
    op.drop_index(
        "ix_recommendations_history_rec_time",
        table_name="recommendations_history",
    )
    op.drop_table("recommendations_history")

    op.drop_index("ix_recommendations_action_state", table_name="recommendations")
    op.drop_index("ix_recommendations_farm_state", table_name="recommendations")
    op.drop_index("ix_recommendations_block_state_created", table_name="recommendations")
    op.drop_index("uq_recommendations_block_tree_open", table_name="recommendations")
    op.drop_constraint("ck_recommendations_confidence", "recommendations", type_="check")
    op.drop_constraint("ck_recommendations_action_type", "recommendations", type_="check")
    op.drop_constraint("ck_recommendations_severity", "recommendations", type_="check")
    op.drop_constraint("ck_recommendations_state", "recommendations", type_="check")
    op.drop_table("recommendations")
