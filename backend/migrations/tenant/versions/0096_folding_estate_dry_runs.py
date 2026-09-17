"""Estate dry runs — one report row per run, never per cell.

A beta (folding) tree is validated before a tenant is switched on by running
it over every active block, and over every cell when the tree is cell-scoped,
without writing a card. Design section 9 calls this stage B. The run answers
four questions: which finding sets the tree produces and how often, which
combination rules never fire, how often the fold composes its text, and how
many cells error before a card is ever written.

**One row, not one row per cell.** A 121-cell grid over 36 blocks is 4,356
cells, and the whole point of the run is the summary. Per-cell rows would be a
table nobody reads twice, and they would have to be purged, indexed and
retained for an answer that is 40 lines of JSON. The counts live in ``report``
and the cells are not kept.

**Nothing here is written by the dry run itself.** The dry run writes no
recommendation, no alert and no evaluation trace — that is its contract, and
the integration test counts rows before and after to hold it. This table
records that a run happened and what it found. It is the only write the estate
dry run makes.

**Not on the schedule.** A run is started by a person, from the platform
screen. There is no Beat entry, because the report is read by an agronomist
before a decision, not collected nightly.

**Ownership.** The table carries no ``tenant_id``, ``farm_id`` or ``block_id``:
a run spans every farm in the tenant, and the tenant schema is the tenancy. So
it is not in the purge manifest, for the same reason
``tenant_*.decision_tree_findings`` is not — see the note in
``backend/app/shared/purge/registry.py``. ``DROP SCHEMA ... CASCADE`` takes it.

``tree_id`` points at ``public.decision_trees`` and is a logical reference with
no foreign key, which is the rule for every tenant-to-public pointer in this
schema.

Design: docs/proposals/unified-decision-tree-engine.md section 9.

Revision ID: 0096
Revises: 0095
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0096"
down_revision: str | Sequence[str] | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `running` is set when the task starts, `done` when the report is stored and
# `failed` when the run raised. A reader polling the run needs to tell "still
# working" from "finished with nothing", and a missing report is not an answer.
_RUN_STATES = "'running', 'done', 'failed'"
_SCOPES = "'block', 'cell'"


def upgrade() -> None:
    op.create_table(
        "decision_tree_estate_dry_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # Logical reference to public.decision_trees. Cross-schema, so no FK.
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalised so a report stays readable after the tree is renamed,
        # archived, or a newer version is published. The same reason
        # decision_tree_eval_traces carries tree_code and tree_version.
        sa.Column("tree_code", sa.Text(), nullable=False),
        sa.Column("tree_name", sa.Text(), nullable=True),
        # The version the run folded. NULL when the tree had no stored version
        # and the caller passed a definition inline.
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False, server_default=sa.text("'block'")),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("public.app_now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("blocks_evaluated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("blocks_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cells_evaluated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cells_errored", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # The whole report, as the screen renders it. Kept as one document
        # rather than a column per number because the shape is the report's,
        # it is read whole, and it is never filtered on.
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        # `name=` fills the convention's %(constraint_name)s slot. Passing the
        # full name doubles the prefix and the downgrade cannot drop it.
        sa.CheckConstraint(f"state IN ({_RUN_STATES})", name="state"),
        sa.CheckConstraint(f"scope IN ({_SCOPES})", name="scope"),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finish_after_start"
        ),
    )
    # "the last N runs of this tree", newest first. `id` breaks the tie because
    # started_at is the transaction timestamp and is identical for rows opened
    # in one transaction; uuid_generate_v7 is time-ordered.
    op.create_index(
        "ix_dt_estate_dry_runs_tree",
        "decision_tree_estate_dry_runs",
        ["tree_id", sa.text("started_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_dt_estate_dry_runs_tree", table_name="decision_tree_estate_dry_runs")
    op.drop_table("decision_tree_estate_dry_runs")
