"""Runtime overrides for the RBAC role->capability matrix.

`role_capabilities.yaml` stays the code-reviewed baseline. This table holds
only the *deltas* a Platform Admin applies at runtime, so the effective matrix
is `baseline merged with overrides` and "reset to default" is a row DELETE
rather than a value the UI has to reconstruct.

Two shape decisions worth stating, because both are load-bearing:

  - **No `tenant_id`.** Overrides are platform-wide for now. A nullable
    discriminator would make `UNIQUE (role, capability)` useless — Postgres
    treats NULLs as distinct, so the same override could be inserted
    endlessly — and it would put a tenant-shaped column on a public table,
    which the purge manifest's information_schema guard scrutinises
    (OWNERSHIP_COLUMNS = tenant_id/farm_id/block_id). A future per-tenant tier
    adds the column *and* registers the table then.
  - **No CHECK on `role` or `capability`.** Both vocabularies live in the app
    (the three StrEnums in auth.context, and capabilities.yaml). Validating in
    the router means adding a role or capability never needs a migration; a
    CHECK here would be a fourth place role names are restated.

`rbac_change_log` exists because reset *deletes* the override row. Without an
append-only trail, undoing a change on a security-sensitive surface would erase
the evidence that it ever happened. It is deliberately not `audit_events`:
that table lives in the per-tenant schema and a platform-wide policy change has
no tenant to attribute itself to.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rbac_role_capability_overrides",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        # The delta itself: True re-grants a capability the baseline withholds,
        # False revokes one the baseline grants. A row that agrees with the
        # baseline is legal but pointless; the router deletes instead.
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        # No FK to public.users: this is a platform audit trail that must
        # survive the user row being removed.
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.UniqueConstraint("role", "capability", name="uq_rbac_override_role_capability"),
        schema="public",
    )

    op.create_table(
        "rbac_change_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        # grant | revoke | reset
        sa.Column("action", sa.Text(), nullable=False),
        # The effective yes/no before and after, not the override value: a
        # reset's meaning is "back to whatever the baseline says", and only the
        # resolved booleans make that readable a year later.
        sa.Column("previous_effective", sa.Boolean(), nullable=False),
        sa.Column("new_effective", sa.Boolean(), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by_email", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="public",
    )
    # Named "action", not "rbac_change_log_action": the metadata naming
    # convention is `ck_%(table_name)s_%(constraint_name)s`, so it prefixes
    # whatever it is given. Passing the table name here too lands
    # `ck_rbac_change_log_rbac_change_log_action` on disk — the doubling
    # migration 0054 had to work around. This yields `ck_rbac_change_log_action`.
    op.create_check_constraint(
        "action",
        "rbac_change_log",
        "action IN ('grant', 'revoke', 'reset')",
        schema="public",
    )
    # The change log is read newest-first on an admin screen and never joined.
    op.create_index(
        "ix_rbac_change_log_changed_at",
        "rbac_change_log",
        [sa.text("changed_at DESC")],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_rbac_change_log_changed_at", table_name="rbac_change_log", schema="public")
    op.drop_table("rbac_change_log", schema="public")
    op.drop_table("rbac_role_capability_overrides", schema="public")
