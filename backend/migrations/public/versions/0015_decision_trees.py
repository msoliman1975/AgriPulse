"""decision_trees + decision_tree_versions — recommendations catalog.

Slice 4 finisher (recommendations sub-module). The recommendations
engine is two-layered:

  * `public.decision_trees` — platform-curated tree catalog. One row
    per tree (e.g. `scout_for_stress_v1`).
  * `public.decision_tree_versions` — immutable version history. Each
    YAML revision lands as a new version row; tenant-side recommendations
    point at the version they were generated from for explainability.
  * `tenant.recommendations` (in tenant migration 0015) — generated
    recommendations + lifecycle.

This migration creates the empty catalog tables. The on-disk YAML
definitions in ``app/modules/recommendations/seeds/`` are loaded into
these tables by ``app.modules.recommendations.loader.sync_from_disk``
on app startup; tests / fixtures may call it directly.

data_model § 11.2 says ``crop_id`` is NOT NULL; we relax to NULL so a
crop-agnostic tree (e.g. "scout for stress" — any crop benefits) can
exist without inventing a placeholder crop row. Per-crop trees still
populate the column.

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
        "decision_trees",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_ar", sa.Text(), nullable=True),
        # Logical FK to public.crops.id; nullable means "applies to any
        # crop" (matches how alerts default_rules.applies_to_crop_categories
        # uses an empty array for the same intent).
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "applicable_regions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        # FK to decision_tree_versions.id — points at the latest published
        # version. Set after the first version row lands; nullable until then.
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        schema="public",
    )

    op.create_table(
        "decision_tree_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "tree_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.decision_trees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        # Raw YAML kept for human review and round-tripping. The compiled
        # JSON is what the evaluator consumes; we store both so an admin
        # editing in the UI later sees the source they authored.
        sa.Column("tree_yaml", sa.Text(), nullable=False),
        sa.Column("tree_compiled", postgresql.JSONB(), nullable=False),
        # Hash of tree_compiled — the sync-from-disk loader compares
        # against this to decide whether a new version row is needed.
        sa.Column("compiled_hash", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("tree_id", "version", name="uq_decision_tree_versions_tree_version"),
        schema="public",
    )

    # Add the FK from decision_trees.current_version_id → decision_tree_versions.id
    # after both tables exist (avoids a circular CREATE TABLE).
    op.create_foreign_key(
        "fk_decision_trees_current_version",
        "decision_trees",
        "decision_tree_versions",
        ["current_version_id"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_decision_tree_versions_tree_published",
        "decision_tree_versions",
        ["tree_id"],
        schema="public",
        postgresql_where=sa.text("published_at IS NOT NULL"),
    )
    op.create_index(
        "ix_decision_trees_active_code",
        "decision_trees",
        ["code"],
        schema="public",
        postgresql_where=sa.text("is_active = TRUE AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_trees_active_code",
        table_name="decision_trees",
        schema="public",
    )
    op.drop_index(
        "ix_decision_tree_versions_tree_published",
        table_name="decision_tree_versions",
        schema="public",
    )
    op.drop_constraint(
        "fk_decision_trees_current_version",
        "decision_trees",
        schema="public",
        type_="foreignkey",
    )
    op.drop_table("decision_tree_versions", schema="public")
    op.drop_table("decision_trees", schema="public")
