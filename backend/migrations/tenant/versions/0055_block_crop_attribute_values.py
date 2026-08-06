"""Crop attribute values on the crop → block assignment, plus their history.

The value side of ``public.crop_attribute_definitions`` (public migration
0050). One row per (block_crop, definition): the establishment method of a
mango block, the date its grafted tree was transplanted, the age of a date
palm offshoot at planting, the grade of a potato seed tuber.

**Typed columns, not a JSONB blob on ``block_crops``.** Two reasons, both
learned here. The report column picker and the decision-tree evaluator both
*compare* these values, and JSONB forces a CAST on every comparison — the
CAST-plus-string-bind family caused three production incidents in one day
(#331/#332/#335). And history rows need a stable shape to diff against.
``signal_observations`` already proved the one-column-per-kind pattern.

``block_crop_attribute_value_log`` is append-only and carries both the
previous and the new value, so a row is self-describing. It is written by the
service in the same transaction as the value write, not by a trigger: a
trigger has no access to the acting user. It buys two things —

* reports resolve a value **as of the period end** (the latest log row at or
  before ``until``), instead of silently back-dating today's number onto a
  Q1 report;
* ``cleared_by_gate`` is recorded distinctly from a user clearing a field, so
  "who deleted the transplant date?" has an answer when the real cause was
  someone switching the establishment method back to Seed.

Definitions are referenced logically (``definition_id`` + denormalised
``definition_code``) with no DB FK — they live in ``public`` and this is a
tenant schema, the same arrangement ``block_crops.crop_id`` already uses.

Revision ID: 0055
Revises: 0054
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANGE_KINDS = "'set', 'updated', 'cleared', 'cleared_by_gate'"

# Exactly one value column carries the value. Without this a row can hold a
# numeric *and* a date and every reader picks a different one.
_EXACTLY_ONE_VALUE = (
    "(value_numeric IS NOT NULL)::int"
    " + (value_text IS NOT NULL)::int"
    " + (value_boolean IS NOT NULL)::int"
    " + (value_date IS NOT NULL)::int"
    " + (value_option IS NOT NULL)::int"
    " + (value_options IS NOT NULL)::int"
)


def _value_columns(prefix: str = "") -> list[sa.Column]:
    return [
        sa.Column(f"{prefix}value_numeric", sa.Numeric(14, 4), nullable=True),
        sa.Column(f"{prefix}value_text", sa.Text(), nullable=True),
        sa.Column(f"{prefix}value_boolean", sa.Boolean(), nullable=True),
        sa.Column(f"{prefix}value_date", sa.Date(), nullable=True),
        # single_select: the chosen option code.
        sa.Column(f"{prefix}value_option", sa.Text(), nullable=True),
        # multi_select: the chosen option codes.
        sa.Column(f"{prefix}value_options", postgresql.ARRAY(sa.Text()), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "block_crop_attribute_values",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "block_crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("block_crops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Logical cross-schema refs to public.crop_attribute_definitions.
        # The code is denormalised because every consumer keys by code (the
        # decision-tree ref, the report column, the form field) and because
        # it keeps the history readable after a definition is retired.
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_code", sa.Text(), nullable=False),
        *_value_columns(),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"{_EXACTLY_ONE_VALUE} = 1", name="one_value"),
        # An empty array is not "no options" — it is a multi_select saved with
        # nothing ticked, which the exactly-one-value check would then accept
        # as a present value. Clearing means deleting the row.
        sa.CheckConstraint(
            "value_options IS NULL OR array_length(value_options, 1) > 0",
            name="options_non_empty",
        ),
        sa.UniqueConstraint(
            "block_crop_id", "definition_id", name="uq_block_crop_attribute_values_pair"
        ),
    )
    op.create_index(
        "ix_block_crop_attribute_values_block_crop",
        "block_crop_attribute_values",
        ["block_crop_id"],
    )
    # The report column picker filters by code across a farm's assignments.
    op.create_index(
        "ix_block_crop_attribute_values_code",
        "block_crop_attribute_values",
        ["definition_code"],
    )

    op.create_table(
        "block_crop_attribute_value_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # CASCADE, not SET NULL: the log is scoped to an assignment. Deleting
        # the assignment deletes the values, and a history of values that no
        # longer exist has nothing to describe.
        sa.Column(
            "block_crop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("block_crops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_code", sa.Text(), nullable=False),
        *_value_columns(),
        *_value_columns(prefix="prev_"),
        sa.Column("change_kind", sa.Text(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(f"change_kind IN ({_CHANGE_KINDS})", name="change_kind"),
    )
    # "Value as of <date>" — the report path. Descending on changed_at so the
    # lookup is a single backwards index scan per (assignment, code).
    op.create_index(
        "ix_block_crop_attribute_value_log_as_of",
        "block_crop_attribute_value_log",
        ["block_crop_id", "definition_code", sa.text("changed_at DESC")],
    )

    op.execute(
        "CREATE TRIGGER trg_block_crop_attribute_values_updated_at "
        "BEFORE UPDATE ON block_crop_attribute_values "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_block_crop_attribute_values_updated_at "
        "ON block_crop_attribute_values"
    )
    op.drop_index(
        "ix_block_crop_attribute_value_log_as_of",
        table_name="block_crop_attribute_value_log",
    )
    op.drop_table("block_crop_attribute_value_log")
    op.drop_index("ix_block_crop_attribute_values_code", table_name="block_crop_attribute_values")
    op.drop_index(
        "ix_block_crop_attribute_values_block_crop", table_name="block_crop_attribute_values"
    )
    op.drop_table("block_crop_attribute_values")
