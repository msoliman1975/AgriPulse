"""Tenancy tables: tenants, tenant_subscriptions, tenant_settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- public.tenants -------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("tax_id", sa.Text(), nullable=True),
        sa.Column(
            "country_code",
            sa.CHAR(2),
            nullable=False,
            server_default=sa.text("'EG'"),
        ),
        sa.Column(
            "default_locale",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column(
            "default_timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Africa/Cairo'"),
        ),
        sa.Column(
            "default_currency",
            sa.CHAR(3),
            nullable=False,
            server_default=sa.text("'EGP'"),
        ),
        sa.Column(
            "default_unit_system",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'feddan'"),
        ),
        sa.Column("contact_email", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("billing_address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("branding_color", sa.Text(), nullable=True),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("schema_name", name="uq_tenants_schema_name"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9-]{3,32}$'",
            name="ck_tenants_slug_format",
        ),
        sa.CheckConstraint(
            "default_locale IN ('en','ar')",
            name="ck_tenants_default_locale",
        ),
        sa.CheckConstraint(
            "default_unit_system IN ('feddan','acre','hectare')",
            name="ck_tenants_default_unit_system",
        ),
        sa.CheckConstraint(
            "status IN ('active','suspended','archived')",
            name="ck_tenants_status",
        ),
        sa.CheckConstraint(
            "branding_color IS NULL OR branding_color ~ '^#[0-9A-Fa-f]{6}$'",
            name="ck_tenants_branding_color",
        ),
    )
    op.create_index(
        "uq_tenants_slug_active",
        "tenants",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_tenants_status_active",
        "tenants",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_tenants_updated_at "
        "BEFORE UPDATE ON public.tenants "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.tenant_subscriptions -----------------------------------
    op.create_table(
        "tenant_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "feature_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_subscriptions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "tier IN ('free','standard','premium','enterprise')",
            name="ck_tenant_subscriptions_tier",
        ),
    )
    op.create_index(
        "uq_tenant_subscriptions_current",
        "tenant_subscriptions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE"),
    )
    op.create_index(
        "ix_tenant_subscriptions_tenant_started",
        "tenant_subscriptions",
        ["tenant_id", sa.text("started_at DESC")],
    )
    op.execute(
        "CREATE TRIGGER trg_tenant_subscriptions_updated_at "
        "BEFORE UPDATE ON public.tenant_subscriptions "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.tenant_settings ----------------------------------------
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cloud_cover_threshold_visualization_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "cloud_cover_threshold_analysis_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "imagery_refresh_cadence_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("24"),
        ),
        sa.Column(
            "alert_notification_channels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['in_app','email']::text[]"),
        ),
        sa.Column("webhook_endpoint_url", sa.Text(), nullable=True),
        sa.Column("webhook_signing_secret_kms_key", sa.Text(), nullable=True),
        sa.Column(
            "dashboard_default_indices",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['ndvi','ndwi']::text[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_settings_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cloud_cover_threshold_visualization_pct BETWEEN 0 AND 100",
            name="ck_tenant_settings_cc_visualization_range",
        ),
        sa.CheckConstraint(
            "cloud_cover_threshold_analysis_pct BETWEEN 0 AND 100",
            name="ck_tenant_settings_cc_analysis_range",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_tenant_settings_updated_at "
        "BEFORE UPDATE ON public.tenant_settings "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tenant_settings_updated_at ON public.tenant_settings")
    op.drop_table("tenant_settings")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_tenant_subscriptions_updated_at "
        "ON public.tenant_subscriptions"
    )
    op.drop_index("ix_tenant_subscriptions_tenant_started", table_name="tenant_subscriptions")
    op.drop_index("uq_tenant_subscriptions_current", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")
    op.execute("DROP TRIGGER IF EXISTS trg_tenants_updated_at ON public.tenants")
    op.drop_index("ix_tenants_status_active", table_name="tenants")
    op.drop_index("uq_tenants_slug_active", table_name="tenants")
    op.drop_table("tenants")
