"""Every tree evaluation leaves a verdict, including the ones that found nothing.

A decision tree leaf used to end as a recommendation or an alert, and every
branch that found nothing wrong ended in ``action_type: no_action`` and wrote
no row at all. Three different situations then looked identical on screen: the
tree ran and the block is fine, the tree was excluded by targeting, and the
tree never ran. Nobody could be told "this block was checked and it is fine".

This table is the missing record. One row per block (or grid cell) per tree,
carrying the status code the leaf resolved to. **A missing row is now
information**: it means that tree did not run for that block.

**Interval rows, not a row per night.** A sweep that returns the same status
as yesterday updates ``last_evaluated_at`` and writes nothing else. A sweep
that returns a different status closes the open row with ``valid_to`` and
inserts a new one. On the production farm — 72 active blocks, 8 trees each — a
row per evaluation would add about 576 rows every night for no new
information. Reading a past date stays one predicate::

    WHERE valid_from <= :at AND (valid_to IS NULL OR valid_to > :at)

That is what the replay asked for later reads.

**``COALESCE`` in the open-row unique index is load-bearing.** ``cell_id`` is
NULL for a block-scoped verdict, and Postgres treats two NULLs as distinct, so
a plain unique index on ``(block_id, cell_id, tree_id)`` would not constrain
block-scoped rows at all — every sweep would insert another open row and the
"current" verdict would become whichever one a query happened to return first.

**No foreign keys, on purpose.** ``tree_id`` names a row in
``public.decision_trees``, and a tenant table cannot reference public. The
alert and recommendation ids are logical too: those rows can be purged or hard
deleted, and the verdict outliving them is the point. ``tree_code`` and
``tree_version`` are denormalised for the same reason ``decision_tree_eval_traces``
denormalises them — the verdict stays readable after the tree is archived or a
new version is published.

Nothing writes to this table yet. The write path is the next phase.

Design: docs/proposals/decision-tree-status-verdicts.md

Revision ID: 0091
Revises: 0090
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The four leaf kinds and the five status codes. Kept in step with
# `app.modules.recommendations.status_codes`; a unit test pins the two lists
# to each other so a code added there cannot be rejected by this CHECK.
_KINDS = "'alert', 'recommendation', 'status', 'no_action'"
_STATUS_CODES = "'na', 'very_good', 'good', 'issue', 'alert'"
_SEVERITIES = "'info', 'warning', 'critical'"
_SCOPES = "'block', 'cell'"

# `uuid_nil()` needs uuid-ossp, which this schema does not install, so the
# all-zero UUID is written out.
_NIL_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


def upgrade() -> None:
    op.create_table(
        "decision_tree_block_verdicts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL = the whole block. Set = one grid cell's verdict. Logical
        # reference to grid_cells, no FK: a rezone retires cells and the
        # verdict has to survive to explain what the map showed that day.
        sa.Column("cell_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False, server_default=sa.text("'block'")),
        # Cross-schema, so no FK is possible. Code and version are
        # denormalised so the row stays readable after the tree changes.
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_code", sa.Text(), nullable=False),
        sa.Column("tree_version", sa.Integer(), nullable=False),
        sa.Column("leaf_node_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Text(), nullable=False),
        # Only the two kinds that ask for work carry a severity. A status
        # leaf has none: its status code already ranks and colours it.
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("text_en", sa.Text(), nullable=False),
        sa.Column("text_ar", sa.Text(), nullable=True),
        # The run that opened this interval, and the run that last confirmed
        # it. Both logical: eval runs are retained for a while and then
        # deleted, and the verdict must outlive its run.
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        # NULL = this is the current verdict. Set = it was replaced or the
        # tree stopped applying to this block.
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        # Logical refs to the work item this verdict came with, when it had
        # one. Null for status and no_action verdicts.
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        # `op.create_check_constraint` doubles a full name, so every CHECK
        # here is named by its SUFFIX only. Production carries the scars of
        # the other spelling: every CHECK on `blocks` is live as
        # `ck_blocks_ck_blocks_*`.
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="kind"),
        sa.CheckConstraint(f"status_code IN ({_STATUS_CODES})", name="status_code"),
        sa.CheckConstraint(
            f"severity IS NULL OR severity IN ({_SEVERITIES})",
            name="severity",
        ),
        sa.CheckConstraint(f"scope IN ({_SCOPES})", name="scope"),
        sa.CheckConstraint("cell_id IS NULL OR scope = 'cell'", name="cell_implies_cell_scope"),
        # An interval that ends before it starts would make the as-of read
        # return nothing for a day the block certainly had a verdict.
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="interval_ordered"),
        # A status leaf carries no severity, and the two kinds that ask for
        # work always do. This is what stops a status leaf being given one
        # by a later writer that forgot the rule.
        sa.CheckConstraint(
            "(kind IN ('alert', 'recommendation')) = (severity IS NOT NULL)",
            name="severity_iff_work_item",
        ),
    )

    # One open verdict per block, cell and tree. COALESCE because Postgres
    # treats two NULL cell_ids as distinct, which would leave every
    # block-scoped verdict unconstrained.
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_dt_verdicts_open
            ON decision_tree_block_verdicts (
                block_id, COALESCE(cell_id, {_NIL_UUID}), tree_id
            )
         WHERE valid_to IS NULL
        """
    )
    # The map's read: every current verdict on one farm, in one statement.
    op.execute(
        """
        CREATE INDEX ix_dt_verdicts_farm_open
            ON decision_tree_block_verdicts (farm_id, status_code)
         WHERE valid_to IS NULL
        """
    )
    # The block panel, and the as-of replay: one block's history by time.
    op.create_index(
        "ix_dt_verdicts_block_time",
        "decision_tree_block_verdicts",
        ["block_id", sa.text("valid_from DESC")],
    )
    # "how has this tree behaved lately", across blocks.
    op.create_index(
        "ix_dt_verdicts_tree_time",
        "decision_tree_block_verdicts",
        ["tree_code", sa.text("valid_from DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_dt_verdicts_tree_time", table_name="decision_tree_block_verdicts")
    op.drop_index("ix_dt_verdicts_block_time", table_name="decision_tree_block_verdicts")
    op.execute("DROP INDEX IF EXISTS ix_dt_verdicts_farm_open")
    op.execute("DROP INDEX IF EXISTS uq_dt_verdicts_open")
    op.drop_table("decision_tree_block_verdicts")
