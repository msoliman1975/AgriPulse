"""Tenant tree-parameter overrides (PR-C of the trees rollout).

PR-B added a `parameters:` block on platform decision trees with
declared defaults. PR-C lets a tenant override individual parameter
values for a tree visible to them (a platform tree or one they
authored). Overrides are per-tenant and per-(tree, param_name); they
live in this tenant-schema table so each tenant's customization stays
isolated.

Table shape:
  * `tree_id` UUID — references `public.decision_trees.id`. Logical FK
    only (no DB constraint) because the tenant schema can't reference
    public tables — same pattern used by `tenant.recommendations.tree_id`.
  * `param_name` TEXT — the declared parameter name in the tree's
    `parameters:` block. Application enforces that the name exists in
    the current published tree version; stale overrides for a removed
    parameter are silently dropped by the engine (PR-B's
    `_build_params`).
  * `value` JSONB — the overridden value. Type matches the parameter's
    declared `type:` (validated at the REST surface). Stored as JSONB
    so all four primitive types (number, integer, boolean, string)
    plus enum + future structured params round-trip without per-type
    columns.
  * Lifecycle: `created_at` / `updated_at` / `created_by` / `updated_by`
    via the standard tenant-schema timestamp mixin.

PK = (tree_id, param_name). One row per override; upserts replace.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tree_parameter_overrides",
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("param_name", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
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
        sa.PrimaryKeyConstraint(
            "tree_id", "param_name", name="pk_tree_parameter_overrides"
        ),
    )
    # Indexed for the sweep's per-tree fetch pattern. The PK already
    # supports prefix-scans on tree_id, but a dedicated index is more
    # explicit and survives any future PK reshuffles.
    op.create_index(
        "ix_tree_parameter_overrides_tree_id",
        "tree_parameter_overrides",
        ["tree_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tree_parameter_overrides_tree_id",
        table_name="tree_parameter_overrides",
    )
    op.drop_table("tree_parameter_overrides")
