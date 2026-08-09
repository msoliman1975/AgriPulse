"""Decision-tree evaluation lineage — ``decision_tree_eval_runs`` + ``_traces``.

Answers the question the product could not answer before: **why did this tree
fire, or why did it not?** — after the fact, for a run that has already
happened.

**Why the existing surfaces are not enough.**

Three things exist today and none of them is a trace.

1. ``recommendations.tree_path`` / ``evaluation_snapshot`` record the walk, but
   only for a leaf that *opened a recommendation*. A tree that came out clear,
   errored, or was excluded by targeting leaves no row anywhere — and those are
   precisely the cases an author needs to debug.
2. ``GET /blocks/{id}/decision-trees:explain`` covers every tree including the
   clear ones, but it **re-evaluates live**. It answers "what would happen
   now", never "what happened in last night's sweep" — by the time anyone
   looks, the signals have moved.
3. The sweep logs two counters (``blocks_processed``, ``recommendations_opened``)
   and nothing per tree.

**Why targeting skips get first-class columns.** A tree excluded by the
crop / country / soil filter never reaches the engine at all — the walk that
would explain it does not happen. Without ``skip_axis`` + ``skip_detail`` the
row would say only "skipped", which is the same non-answer as today. Country in
particular is inherited from the *farm*, not the block, and an unset country
silently disables every country-targeted tree; that failure is invisible until
something records which axis rejected the tree and what the two sides held.

**Storage grain — deliberately uneven.**

    status     what is stored
    ---------  -------------------------------------------------------
    fired      node_path + resolved_values + outcome  (full)
    error      node_path + resolved_values + error    (full)
    skipped    skip_axis + skip_detail                (full; no walk
               happened, so there is no path to store)
    clear      node_path only, resolved_values '{}'   (compact)

``clear`` is the overwhelming majority of rows — most trees do not fire on most
blocks on most days — and it is the cheapest case to reconstruct: the path
alone shows which branch the block took, and the explain endpoint can recover
the values for a block whose data has not moved. Paying full JSONB for it would
multiply the table's size for the least-asked question.

**Volume.** Rows are (blocks x targeted trees) per run, plus
(cells x cell-scoped trees) for gridded blocks. A 36-block farm with ~21 active
trees writes ~750 block-scoped rows per daily sweep; one cell-scoped tree over
121-cell grids adds ~4.4k more. Order 5k rows/tenant/day.

**No retention policy and not a hypertable — yet.** Both are real decisions
that need numbers from a real tenant rather than a guess made the day the table
is created, and a retention policy on a lineage table deletes exactly the audit
trail that justifies the table. ``run_id`` carries ``ON DELETE CASCADE``
specifically so that whatever retention we agree on can be expressed as
"delete old runs" and the traces follow. Converting to a hypertable later is
not blocked by shipping it flat now.

**Ownership.** ``decision_tree_eval_traces`` carries ``farm_id`` and
``block_id`` and is registered in the purge manifest under both. The runs table
deliberately carries **no** ownership column: a sweep spans every farm in the
tenant, so there is no single owner to name, and the tenant schema is dropped
wholesale on tenant purge. Traces cascade off the run; a block purge deletes
that block's traces and leaves the run row as an honest record that the run
covered blocks which no longer exist.

Revision ID: 0062
Revises: 0061
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `sweep` is the nightly Beat pass over every block; `on_demand` is the
# per-block :evaluate endpoint. Dry-runs are deliberately absent — they write
# nothing, so authoring experiments never pollute the execution history.
_RUN_KINDS = "'sweep', 'on_demand'"
_RUN_OUTCOMES = "'ok', 'failed'"
# Mirrors ExplainTree.status minus `per_cell`: a per-cell tree writes one real
# trace per cell here rather than a block-level placeholder.
_TRACE_STATUSES = "'fired', 'clear', 'skipped', 'error'"
_SKIP_AXES = "'crop', 'country', 'soil'"
_SCOPES = "'block', 'cell'"


def upgrade() -> None:
    op.create_table(
        "decision_tree_eval_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        # NULL for the Beat sweep, which has no human behind it.
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("blocks_evaluated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trees_evaluated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trees_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "recommendations_opened", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("alerts_opened", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("traces_written", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error", sa.Text(), nullable=True),
        # The `name=` here fills the convention's `%(constraint_name)s` slot and
        # renders as `ck_decision_tree_eval_runs_<name>`. Passing the full name
        # doubles the prefix and the downgrade then cannot drop it — the bug
        # this repo has hit before.
        sa.CheckConstraint(f"kind IN ({_RUN_KINDS})", name="kind"),
        sa.CheckConstraint(f"outcome IN ({_RUN_OUTCOMES})", name="outcome"),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finish_after_start"
        ),
    )
    # "the last N runs", newest first. `id` breaks the tie because started_at
    # defaults to now() — the transaction timestamp — which is identical for
    # runs opened in one transaction; uuid_generate_v7 is time-ordered.
    op.create_index(
        "ix_decision_tree_eval_runs_started",
        "decision_tree_eval_runs",
        [sa.text("started_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "decision_tree_eval_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "decision_tree_eval_runs.id",
                ondelete="CASCADE",
                name="fk_dt_eval_traces_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        # NULL = block-scoped evaluation. Set = this row is one cell's verdict.
        # Logical reference to grid_cells, no FK: a rezone retires cells and the
        # trace must survive to explain a recommendation that referenced one.
        sa.Column("cell_id", postgresql.UUID(as_uuid=True), nullable=True),
        # tree_id points at public.decision_trees — cross-schema, so no FK is
        # possible. code + version are denormalised so a trace stays readable
        # after the tree is archived or a new version is published.
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tree_code", sa.Text(), nullable=False),
        sa.Column("tree_version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default=sa.text("'block'")),
        sa.Column("status", sa.Text(), nullable=False),
        # Which targeting axis rejected the tree, and the two sides of that
        # comparison: {"required": [...], "actual": "..."}. Only ever set on a
        # skipped row.
        sa.Column("skip_axis", sa.Text(), nullable=True),
        sa.Column("skip_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # The ordered node walk: [{node_id, matched, label_en, label_ar,
        # condition, values}]. Empty on a skipped row — no walk happened.
        sa.Column(
            "node_path",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Merged resolved refs, {"indices.ndvi.mean": "0.39"}. A ref that
        # resolved to null is stored as null rather than omitted — that is how a
        # fail-closed miss is told apart from a genuine comparison. Empty on
        # `clear` by design (see the storage-grain table above).
        sa.Column(
            "resolved_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Tenant parameter overrides in force for this walk, so a threshold that
        # differs from the tree's declared default is visible in the trace.
        sa.Column(
            "param_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # {kind, action_type, severity, confidence, leaf_node_id} on a fired row.
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Logical refs, no FK: the row they point at can be purged or hard
        # deleted, and the trace outliving it is the point.
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(f"status IN ({_TRACE_STATUSES})", name="status"),
        sa.CheckConstraint(f"scope IN ({_SCOPES})", name="scope"),
        sa.CheckConstraint(f"skip_axis IS NULL OR skip_axis IN ({_SKIP_AXES})", name="skip_axis"),
        # One-directional on purpose: a skipped row must name an axis, but a
        # future status is not forced to leave skip_axis empty.
        sa.CheckConstraint(
            "status <> 'skipped' OR skip_axis IS NOT NULL", name="skipped_names_axis"
        ),
        sa.CheckConstraint("cell_id IS NULL OR scope = 'cell'", name="cell_implies_cell_scope"),
    )
    # The debugger's primary read: "this block's last verdicts", newest first.
    op.create_index(
        "ix_decision_tree_eval_traces_block",
        "decision_tree_eval_traces",
        ["block_id", sa.text("evaluated_at DESC"), sa.text("id DESC")],
    )
    # "how has this tree behaved lately", across blocks.
    op.create_index(
        "ix_decision_tree_eval_traces_tree",
        "decision_tree_eval_traces",
        ["tree_code", sa.text("evaluated_at DESC")],
    )
    # Run drill-down, and the counts-by-status the run summary shows.
    op.create_index(
        "ix_decision_tree_eval_traces_run",
        "decision_tree_eval_traces",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_decision_tree_eval_traces_run", table_name="decision_tree_eval_traces")
    op.drop_index("ix_decision_tree_eval_traces_tree", table_name="decision_tree_eval_traces")
    op.drop_index("ix_decision_tree_eval_traces_block", table_name="decision_tree_eval_traces")
    op.drop_table("decision_tree_eval_traces")
    op.drop_index("ix_decision_tree_eval_runs_started", table_name="decision_tree_eval_runs")
    op.drop_table("decision_tree_eval_runs")
