"""Tenant Keycloak-provisioning columns + 'pending_provision' status.

PR-B of the admin-portal rollout. Lets `create_tenant` mark a tenant as
needing a follow-up Keycloak provisioning attempt, and gives the retry
endpoint enough context (owner email/full name, KC group id once known)
to resume without re-prompting the operator.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("keycloak_group_id", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenants",
        sa.Column("pending_owner_email", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "tenants",
        sa.Column("pending_owner_full_name", sa.Text(), nullable=True),
        schema="public",
    )

    op.drop_constraint("ck_tenants_status", "tenants", schema="public", type_="check")
    op.create_check_constraint(
        "ck_tenants_status",
        "tenants",
        "status IN ('active','suspended','pending_delete','pending_provision','archived')",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenants_status", "tenants", schema="public", type_="check")
    op.create_check_constraint(
        "ck_tenants_status",
        "tenants",
        "status IN ('active','suspended','pending_delete','archived')",
        schema="public",
    )
    op.drop_column("tenants", "pending_owner_full_name", schema="public")
    op.drop_column("tenants", "pending_owner_email", schema="public")
    op.drop_column("tenants", "keycloak_group_id", schema="public")
