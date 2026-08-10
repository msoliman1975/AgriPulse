"""``block_responsible_log`` — who was responsible for a block, and when.

``blocks.agronomist_membership_id`` names one person and remembers nothing. Once
the Action Center started defaulting dispatch to that person (0063), the field
stopped being descriptive metadata and became the answer to "why did this task
go to them" — a question you can only answer after the fact if the *previous*
answers were kept.

**Why not the audit trail.** ``farms.block_updated`` audit events record
``changed_fields`` and no values, so they can say the responsible member changed
and never who it changed from or to. ``audit_data_changes`` does have
before/after JSONB — and is declared in ``audit/models.py`` and written by
nothing, so building on it would mean building it first.

**Why append-only.** A handover history that can be edited is not a history.
Rows are only ever inserted; correcting a mistake means recording the correction
as its own row, which is the same shape ``growth_stage_logs`` already uses for
phenology transitions.

``previous_membership_id`` is nullable because the first assignment has no
predecessor, and ``new_membership_id`` is nullable because *unassigning* is a
change worth recording — a block that silently lost its owner is exactly the
state that makes dispatch fall back to an arbitrary member.

No FK on either membership column: those ids live in the public schema's
identity tables and this codebase does not point tenant tables at them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "block_responsible_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL on the first assignment (nothing preceded it).
        sa.Column("previous_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        # NULL when the block is being unassigned — a change worth recording,
        # since an ownerless block is what sends dispatch to a fallback member.
        sa.Column("new_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # The only query this table serves: one block's history, newest first.
    op.create_index(
        "ix_block_responsible_log_block",
        "block_responsible_log",
        ["block_id", sa.text("changed_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_block_responsible_log_block", table_name="block_responsible_log")
    op.drop_table("block_responsible_log")
