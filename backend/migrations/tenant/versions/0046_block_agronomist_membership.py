"""U-4b (identity unification) — repoint blocks.agronomist_id to a membership.

The per-block agronomist stays, but its reference target moves from a raw
``public.users.id`` to a ``public.tenant_memberships.id`` — the same
canonical reference the U-3 worker link uses. This unifies "who is the
agronomist on this block" with the IAM membership model (no more raw user
ids floating disconnected from tenancy).

Value-only repoint of a logical (no-FK) cross-schema reference:

  1. add ``agronomist_membership_id uuid`` (nullable).
  2. backfill: map the stored user id to THAT user's membership *in this
     tenant*. The migration runs per-tenant (migrate_tenants sets the
     search_path), so ``current_schema()`` is the tenant schema
     ``tenant_<uuid_hex>``; match it to ``tenant_memberships.tenant_id`` by
     stripping dashes. ``UNIQUE (user_id, tenant_id)`` guarantees at most one
     membership per block, so the join can't fan out.
  3. drop ``agronomist_id``.

Stale rows whose ``agronomist_id`` user is not a member of this tenant get a
NULL membership (the raw value was read nowhere, so nothing is lost).
Reversible: downgrade re-adds ``agronomist_id`` and back-maps via
``tenant_memberships.user_id``.

Revision ID: 0046
Revises: 0045
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column(
            "agronomist_membership_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.execute(
        """
        UPDATE blocks b
        SET agronomist_membership_id = tm.id
        FROM public.tenant_memberships tm
        WHERE tm.user_id = b.agronomist_id
          AND replace(tm.tenant_id::text, '-', '') = replace(current_schema(), 'tenant_', '')
          AND b.agronomist_id IS NOT NULL
        """
    )
    op.drop_column("blocks", "agronomist_id")


def downgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("agronomist_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE blocks b
        SET agronomist_id = tm.user_id
        FROM public.tenant_memberships tm
        WHERE tm.id = b.agronomist_membership_id
          AND b.agronomist_membership_id IS NOT NULL
        """
    )
    op.drop_column("blocks", "agronomist_membership_id")
