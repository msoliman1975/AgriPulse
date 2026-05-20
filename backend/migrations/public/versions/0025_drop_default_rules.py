"""Drop public.default_rules (Stage 2 of rules sunset).

Companion to tenant migration `0033_drop_tenant_rule_tables`. The
platform rule catalog has been replaced 1:1 by the decision-tree seed
`ndvi_baseline_alert_v1.yaml` (PR-F), and the alerts engine is being
deleted in this same PR. Dropping the catalog table closes the loop.

Drop precondition: confirm the `ndvi_baseline_alert_v1` tree is
present in `public.decision_trees` for every environment before
running this. The seed loader inserts it at app startup
(`sync_from_disk`), so deploying Stage 2 to an environment that
already ran a Stage 1 app at least once guarantees the row exists.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("default_rules", schema="public")


def downgrade() -> None:
    # Structural-only restore. Re-seeding the two original rows + the
    # alerts engine code is a separate revert of Stage 2's app PR.
    op.create_table(
        "default_rules",
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
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'warning'"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "applies_to_crop_categories",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
