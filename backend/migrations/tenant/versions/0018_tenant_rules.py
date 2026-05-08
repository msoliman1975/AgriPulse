"""tenant_rules — per-tenant alert rules authored from the UI.

Counterpart to `public.default_rules` (platform-curated catalog) and
`tenant_<id>.rule_overrides` (severity tweaks + kill-switches on
defaults). This third source lets a tenant author rules from scratch:
own code, own conditions, own actions.

Engine merge precedence at evaluation time:

  1. Walk every active row in `public.default_rules`.
  2. For each, apply the tenant's `rule_overrides` row if present
     (existing flow — unchanged).
  3. Then walk every active row in `tenant_rules`. These are
     never merged with `rule_overrides` — they're standalone.

The partial UNIQUE on `alerts.(block_id, rule_code) WHERE status IN
('open','acknowledged','snoozed')` is shared across all three sources,
so codes must be unique across the union. The router validates a
tenant rule code doesn't collide with any default at create time;
nothing prevents a future default from being added later with a
clashing code, but that's a platform-team coordination problem.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
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
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
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
        "ck_tenant_rules_severity",
        "tenant_rules",
        "severity IN ('info', 'warning', 'critical')",
    )
    op.create_check_constraint(
        "ck_tenant_rules_status",
        "tenant_rules",
        "status IN ('active', 'draft', 'retired')",
    )
    # One active row per code at a time. Re-using a code requires
    # soft-deleting the previous row first.
    op.create_index(
        "uq_tenant_rules_code_active",
        "tenant_rules",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tenant_rules_status",
        "tenant_rules",
        ["status"],
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_rules_status", table_name="tenant_rules")
    op.drop_index("uq_tenant_rules_code_active", table_name="tenant_rules")
    op.drop_constraint("ck_tenant_rules_status", "tenant_rules", type_="check")
    op.drop_constraint("ck_tenant_rules_severity", "tenant_rules", type_="check")
    op.drop_table("tenant_rules")
