"""U-3 (identity unification) — optionally link a worker to a login member.

Adds a nullable ``membership_id`` to ``resources``. A worker record is now
one of two flavours:

  * LINKED   — ``membership_id`` points at a ``public.tenant_memberships``
    row, i.e. a real login member who also does field work. Invite the
    person once and they're available as a worker; activity logs join back
    to their identity.
  * UNLINKED — ``membership_id IS NULL``, the common case: day-labour with
    no account. Behaves exactly as before this migration.

Only workers can be linked; equipment rows keep ``membership_id NULL``
(enforced in the schema/service layer, mirroring the existing kind-shape
rules — we don't add a DB CHECK for it here to keep the constraint set
lean, consistent with how ``farm_id`` cross-schema refs are handled).

No foreign key: ``tenant_memberships`` lives in the ``public`` schema while
``resources`` is tenant-scoped, so the reference is logical only — the same
pattern ``farm_scopes.farm_id`` and other cross-schema columns use. A plain
btree index supports the "which worker record is this member?" /
"every activity this member logged" lookups that motivate the link.

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column(
            "membership_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    # Active linked workers only — keeps the index small and supports the
    # member -> worker-record / member -> activity-history joins.
    op.execute(
        """
        CREATE INDEX ix_resources_membership_id
        ON resources (membership_id)
        WHERE membership_id IS NOT NULL AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resources_membership_id")
    op.drop_column("resources", "membership_id")
