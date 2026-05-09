"""platform_defaults + tenant_settings_overrides — three-tier resolver foundation.

Per `docs/proposals/admin-portals-and-settings.md` §3.1–§3.2.

Defaults are referenced by key, not copied. New tenants don't snapshot —
they inherit live. Updating a default in `public.platform_defaults`
flows to every tenant that hasn't written an override row.

`tenant_settings_overrides.key` REFERENCES `platform_defaults.key` ON
DELETE RESTRICT so an operator can't delete a default with active
tenant overrides — must clean up the overrides first. Documented in
`runbooks/platform-defaults.md` (lands with PR-Set5).

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_defaults",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("value_schema", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "value_schema IN ('string','number','boolean','object','array')",
            name="ck_platform_defaults_value_schema",
        ),
        sa.CheckConstraint(
            "category IN ('weather','imagery','email','webhook','alert','general')",
            name="ck_platform_defaults_category",
        ),
        schema="public",
    )

    op.create_table(
        "tenant_settings_overrides",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "tenant_id", "key", name="pk_tenant_settings_overrides"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_settings_overrides_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["key"],
            ["platform_defaults.key"],
            name="fk_tenant_settings_overrides_key_platform_defaults",
            ondelete="RESTRICT",
        ),
        schema="public",
    )

    # No update-trigger needed: the resolver reads `updated_at` straight
    # from the row, which is set on INSERT and the service updates it
    # on every PATCH (we don't rely on Postgres triggers for this).


def downgrade() -> None:
    op.drop_table("tenant_settings_overrides", schema="public")
    op.drop_table("platform_defaults", schema="public")
