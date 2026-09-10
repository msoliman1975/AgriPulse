"""A tenant can pin one tree to one version.

Publishing a platform tree reaches every tenant at their next sweep. That is
the point — a fixed threshold should not wait for anybody. But a tenant who has
built a season's work around a specific version needs a way to hold it.

A pin is the only thing that stops a tenant following the current version.
Absent, the tenant runs `decision_trees.current_version_id`, which is what
every tenant has always done, so this table being empty is the status quo.

Not a foreign key to `public.tenants` on purpose in spirit — but this one is
public-to-public, and `tree_id` genuinely references a public row, so the FK is
real and cascades. Deleting a tree takes its pins with it, which is right: a
pin to a tree that no longer exists is not information.

`version` is an int, not a version-row id, because that is what the author
reads on screen and what the API takes. Resolution joins on
`(tree_id, version)`, and a pin to an unpublished version resolves to no row,
so the tree is skipped rather than run from a draft. The API only offers
published versions, so reaching that state takes a hand-written row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0086"
down_revision: str | Sequence[str] | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_tree_version_pins",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("pinned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "tree_id"),
        sa.ForeignKeyConstraint(["tree_id"], ["public.decision_trees.id"], ondelete="CASCADE"),
        sa.CheckConstraint("version >= 1", name="ck_tree_pin_version_positive"),
        schema="public",
    )
    # The sweep resolves pins one tenant at a time, so this is the read shape.
    op.create_index(
        "ix_tenant_tree_version_pins_tenant",
        "tenant_tree_version_pins",
        ["tenant_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_tree_version_pins_tenant",
        table_name="tenant_tree_version_pins",
        schema="public",
    )
    op.drop_table("tenant_tree_version_pins", schema="public")
