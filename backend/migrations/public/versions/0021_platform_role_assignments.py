"""platform_role_assignments — mirror of Keycloak `platform_role` user attribute.

Keycloak holds the source of truth (attribute → JWT claim). This table
mirrors the assignment so /platform/admins can list users without
querying the Keycloak admin API on every page load. Writes go through
the platform-admins service, which keeps the two sides in sync.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_role_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "role IN ('PlatformAdmin','PlatformSupport')",
            name="ck_platform_role_assignments_role",
        ),
        schema="public",
    )
    # At most one active row per (user, role) so re-inviting is a no-op.
    op.create_index(
        "uq_platform_role_assignments_active",
        "platform_role_assignments",
        ["user_id", "role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_platform_role_assignments_active",
        table_name="platform_role_assignments",
        schema="public",
    )
    op.drop_table("platform_role_assignments", schema="public")
