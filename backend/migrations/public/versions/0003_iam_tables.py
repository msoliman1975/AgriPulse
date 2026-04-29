"""IAM tables: users, user_preferences, tenant_memberships,
tenant_role_assignments, farm_scopes, platform_role_assignments.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column[object]]:
    """The five audit columns from data_model § 1.4."""
    return [
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
    ]


def upgrade() -> None:
    # ---- public.users --------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("keycloak_subject", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint("keycloak_subject", name="uq_users_keycloak_subject"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "status IN ('active','suspended','archived')",
            name="ck_users_status",
        ),
    )
    op.create_index(
        "ix_users_status_active",
        "users",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_users_updated_at "
        "BEFORE UPDATE ON public.users "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.user_preferences ---------------------------------------
    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "language",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column(
            "numerals",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'western'"),
        ),
        sa.Column(
            "unit_system",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'feddan'"),
        ),
        sa.Column(
            "timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Africa/Cairo'"),
        ),
        sa.Column(
            "date_format",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'YYYY-MM-DD'"),
        ),
        sa.Column(
            "notification_channels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['in_app','email']::text[]"),
        ),
        sa.Column(
            "dashboard_layout",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_preferences_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("language IN ('en','ar')", name="ck_user_preferences_language"),
        sa.CheckConstraint(
            "numerals IN ('western','arabic_eastern')",
            name="ck_user_preferences_numerals",
        ),
        sa.CheckConstraint(
            "unit_system IN ('feddan','acre','hectare')",
            name="ck_user_preferences_unit_system",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_user_preferences_updated_at "
        "BEFORE UPDATE ON public.user_preferences "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.tenant_memberships -------------------------------------
    op.create_table(
        "tenant_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_memberships_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name="fk_tenant_memberships_invited_by_users",
        ),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            name="uq_tenant_memberships_user_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('invited','active','suspended','archived')",
            name="ck_tenant_memberships_status",
        ),
    )
    op.create_index(
        "ix_tenant_memberships_tenant_status",
        "tenant_memberships",
        ["tenant_id", "status"],
    )
    op.execute(
        "CREATE TRIGGER trg_tenant_memberships_updated_at "
        "BEFORE UPDATE ON public.tenant_memberships "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.tenant_role_assignments --------------------------------
    op.create_table(
        "tenant_role_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["tenant_memberships.id"],
            name="fk_tenant_role_assignments_membership_id_tenant_memberships",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_tenant_role_assignments_granted_by_users",
        ),
        sa.CheckConstraint(
            "role IN ('TenantOwner','TenantAdmin','BillingAdmin')",
            name="ck_tenant_role_assignments_role",
        ),
    )
    op.create_index(
        "uq_tenant_role_assignments_active",
        "tenant_role_assignments",
        ["membership_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # data_model § 4.5: at most one TenantOwner per tenant. Enforced via
    # partial unique index on (tenant_id, role) joined through membership.
    # Implemented as an index on a precomputed pair via a generated column
    # would require a join; simplest form is a deferred constraint trigger.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.check_single_tenant_owner()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            owner_count INT;
            tid UUID;
        BEGIN
            IF NEW.role <> 'TenantOwner' OR NEW.revoked_at IS NOT NULL THEN
                RETURN NEW;
            END IF;
            SELECT tm.tenant_id INTO tid
                FROM public.tenant_memberships tm
                WHERE tm.id = NEW.membership_id;
            SELECT count(*) INTO owner_count
                FROM public.tenant_role_assignments tra
                JOIN public.tenant_memberships tm ON tm.id = tra.membership_id
                WHERE tm.tenant_id = tid
                  AND tra.role = 'TenantOwner'
                  AND tra.revoked_at IS NULL
                  AND tra.id <> NEW.id;
            IF owner_count > 0 THEN
                RAISE EXCEPTION
                    'tenant % already has an active TenantOwner', tid;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_single_tenant_owner "
        "AFTER INSERT OR UPDATE ON public.tenant_role_assignments "
        "DEFERRABLE INITIALLY IMMEDIATE "
        "FOR EACH ROW EXECUTE FUNCTION public.check_single_tenant_owner()"
    )

    # ---- public.farm_scopes --------------------------------------------
    op.create_table(
        "farm_scopes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["tenant_memberships.id"],
            name="fk_farm_scopes_membership_id_tenant_memberships",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_farm_scopes_granted_by_users",
        ),
        sa.CheckConstraint(
            "role IN ('FarmManager','Agronomist','FieldOperator','Scout','Viewer')",
            name="ck_farm_scopes_role",
        ),
    )
    op.create_index(
        "uq_farm_scopes_active",
        "farm_scopes",
        ["membership_id", "farm_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_farm_scopes_membership_active",
        "farm_scopes",
        ["membership_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_farm_scopes_farm_active",
        "farm_scopes",
        ["farm_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # ---- public.platform_role_assignments ------------------------------
    op.create_table(
        "platform_role_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_platform_role_assignments_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_platform_role_assignments_granted_by_users",
        ),
        sa.CheckConstraint(
            "role IN ('PlatformAdmin','PlatformSupport')",
            name="ck_platform_role_assignments_role",
        ),
    )
    op.create_index(
        "uq_platform_role_assignments_active",
        "platform_role_assignments",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_platform_role_assignments_active", table_name="platform_role_assignments")
    op.drop_table("platform_role_assignments")
    op.drop_index("ix_farm_scopes_farm_active", table_name="farm_scopes")
    op.drop_index("ix_farm_scopes_membership_active", table_name="farm_scopes")
    op.drop_index("uq_farm_scopes_active", table_name="farm_scopes")
    op.drop_table("farm_scopes")
    op.execute("DROP TRIGGER IF EXISTS trg_single_tenant_owner ON public.tenant_role_assignments")
    op.execute("DROP FUNCTION IF EXISTS public.check_single_tenant_owner()")
    op.drop_index("uq_tenant_role_assignments_active", table_name="tenant_role_assignments")
    op.drop_table("tenant_role_assignments")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_tenant_memberships_updated_at ON public.tenant_memberships"
    )
    op.drop_index("ix_tenant_memberships_tenant_status", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.execute("DROP TRIGGER IF EXISTS trg_user_preferences_updated_at ON public.user_preferences")
    op.drop_table("user_preferences")
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users")
    op.drop_index("ix_users_status_active", table_name="users")
    op.drop_table("users")
