"""Aggregate cell-scoped action items, and make a re-fire visible.

Two defects, one shape.

**Bombardment.** A cell-scoped decision tree evaluates once per grid cell, and
the dedup keys it hits are per cell — `uq_recommendations_cell_tree_open` on
`(block_id, cell_id, tree_id)` and, for alerts, the cell uuid smuggled into the
synthesised `rule_code` (`tree:<code>:<leaf>:cell:<uuid>`). So a 36-cell block
where one tree fires everywhere puts 36 rows in the Action Center saying the
same sentence. They are the same finding at 36 coordinates, not 36 findings.

**Silent re-fire.** The same dedup keys make a re-evaluation a no-op while the
first item is still open. Correct — but it writes nothing, so an item that has
been re-firing every morning for a week is indistinguishable from one raised
once and forgotten. Nothing on the row says "this is still true".

This adds one mechanism for both: a **group parent**.

* Cell-scoped output attaches to a parent row keyed on
  `(block_id, group_key)` where `group_key` is
  `<tree_code>:<leaf_node_id>:<action_type>:<severity>` — the caller's rule of
  "same block, same tree, same action, same kind, same severity". The parent
  carries `cell_id IS NULL` and `is_group = TRUE`; the per-cell rows become
  children via `group_parent_id` and drop out of every list.
* Day is deliberately **not** in the key. It decides when a group is born, not
  what it is: while a group is open, tomorrow's firing lands in it and bumps
  `occurrence_count` / `day_streak` / `last_seen_at` instead of minting a
  second card. One row per outbreak, not one per day.
* Block-scoped items (`cell_id IS NULL`, `is_group = FALSE`) get the same
  counters without a parent — they are already their own unit, and the
  recurrence half of the problem applies to them identically.

Index changes, both load-bearing:

* `uq_recommendations_block_tree_open` fired on `state='open' AND cell_id IS
  NULL`, which is exactly the shape of a parent. Two parents of one tree at
  one block (two leaves, or two severities) would have collided. Its predicate
  gains `AND is_group = FALSE`, and parents get their own
  `uq_recommendations_group_open` on `(block_id, group_key)`.
* `uq_alerts_block_rule_open` has the same problem for the same reason — a
  parent alert's `rule_code` is the un-suffixed `tree:<code>:<leaf>`, which a
  legacy block-scoped alert could already hold. Same treatment.

Backfill: the currently open/acknowledged/snoozed cell-scoped rows are grouped
retroactively, so the noise already sitting in the queue collapses on deploy
rather than waiting to be closed by hand. `first_seen_at` comes from the oldest
member and `occurrence_count` starts at 1 — the per-day history to derive a
truer count was never recorded, and inventing one would be worse than
under-reporting. Closed, applied and dismissed rows are not touched at all.

Revision ID: 0079
Revises: 0078
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


# Both tables get the identical column set: the Action Center reads them
# through one UNION and a column present on one side only would have to be
# faked with a NULL literal on the other, which is how the two halves of that
# query drift apart.
def _group_columns() -> tuple[sa.Column, ...]:
    """Fresh Column objects per call — a Column instance binds to the first
    table it is added to, so the two tables cannot share one tuple."""
    return (
        # `<tree_code>:<leaf_node_id>:<action_type>:<severity>`. NULL on rows that
        # predate this migration and on legacy rule-sourced alerts, which have no
        # tree and therefore no leaf to key on.
        sa.Column("group_key", sa.Text(), nullable=True),
        # Self-reference. FK within the same table and schema, so CASCADE is safe:
        # deleting a parent should not leave orphan children addressable by an id
        # nothing lists.
        sa.Column("group_parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        # Children still firing as of the last evaluation. Not a count of all
        # children ever — a cell that has gone quiet stays attached (history) but
        # stops counting, which is what lets the card say "9 cells today, 14
        # yesterday".
        sa.Column("member_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # What `member_count` was at the end of the previous evaluation day.
        # Without it, aggregation hides the one thing it must not hide: a
        # 12-cell finding and a 20-cell one render identically, because a count
        # with no baseline is not a trend. Rolled forward exactly once per
        # tenant-day by the same statement that recomputes `member_count`.
        sa.Column(
            "previous_member_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        # The tenant-local day `previous_member_count` was last rolled on. A
        # sweep can run several times a morning; the baseline must not move
        # with it, or it decays to "same as five minutes ago" and never shows
        # a trend at all.
        sa.Column("last_counted_day", sa.Date(), nullable=True),
        # Distinct days this item has fired, first day included.
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Consecutive firing days. Resets to 1 when a day is skipped, so "6 days
        # running" means six days running.
        sa.Column("day_streak", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        # The tenant-local calendar day of the last firing. Stored rather than
        # derived from `last_seen_at` because the boundary is the tenant's
        # timezone, not the server's, and a UTC-derived day would split or merge
        # streaks for every tenant east or west of it.
        sa.Column("last_seen_day", sa.Date(), nullable=True),
        # Set on a child whose cell stopped firing. Never set on a parent.
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
    )


_ALERT_ACTIVE = "status IN ('open', 'acknowledged', 'snoozed')"


def upgrade() -> None:
    for table in ("recommendations", "alerts"):
        for column in _group_columns():
            op.add_column(table, column)
        op.create_foreign_key(
            f"fk_{table}_group_parent",
            table,
            table,
            ["group_parent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # --- recommendations indexes -------------------------------------------
    # The old predicate matches a parent exactly (open, no cell), so without
    # the `is_group = FALSE` guard a second parent for the same tree — a
    # different leaf, or the same leaf at a different severity — would be
    # rejected as a duplicate of the first.
    op.drop_index("uq_recommendations_block_tree_open", table_name="recommendations")
    op.create_index(
        "uq_recommendations_block_tree_open",
        "recommendations",
        ["block_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND cell_id IS NULL AND is_group = FALSE"),
    )
    op.create_index(
        "uq_recommendations_group_open",
        "recommendations",
        ["block_id", "group_key"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND is_group = TRUE"),
    )
    op.create_index(
        "ix_recommendations_group_parent",
        "recommendations",
        ["group_parent_id"],
        postgresql_where=sa.text("group_parent_id IS NOT NULL"),
    )

    # --- alerts indexes -----------------------------------------------------
    op.drop_index("uq_alerts_block_rule_open", table_name="alerts")
    op.create_index(
        "uq_alerts_block_rule_open",
        "alerts",
        ["block_id", "rule_code"],
        unique=True,
        postgresql_where=sa.text(f"{_ALERT_ACTIVE} AND is_group = FALSE"),
    )
    op.create_index(
        "uq_alerts_group_open",
        "alerts",
        ["block_id", "group_key"],
        unique=True,
        postgresql_where=sa.text(f"{_ALERT_ACTIVE} AND is_group = TRUE"),
    )
    op.create_index(
        "ix_alerts_group_parent",
        "alerts",
        ["group_parent_id"],
        postgresql_where=sa.text("group_parent_id IS NOT NULL"),
    )

    # Existing rows: seed the recurrence clocks from what is already known, so
    # nothing reads as "first seen at the moment we deployed".
    for table in ("recommendations", "alerts"):
        op.execute(
            f"UPDATE {table} SET first_seen_at = created_at, last_seen_at = created_at "  # noqa: S608
            "WHERE first_seen_at IS NULL"
        )

    _backfill_recommendation_groups()
    _backfill_alert_groups()


def _backfill_recommendation_groups() -> None:
    """Collapse the open cell-scoped backlog into parents.

    The leaf id is recovered from the last step of the stored `tree_path`,
    which is the same place the engine reads it from when it synthesises a
    group key — a row whose path is empty falls back to the literal `leaf`,
    matching `_open_alert_from_tree`'s own fallback so a backfilled group and a
    freshly generated one land on the same key rather than forking.
    """
    op.execute(
        """
        WITH keyed AS (
            SELECT r.*,
                   r.tree_code || ':'
                     || COALESCE(r.tree_path -> -1 ->> 'node_id', 'leaf') || ':'
                     || r.action_type || ':' || r.severity AS gkey
              FROM recommendations r
             WHERE r.deleted_at IS NULL
               AND r.state = 'open'
               AND r.cell_id IS NOT NULL
               AND r.group_parent_id IS NULL
        ),
        agg AS (
            SELECT block_id, gkey,
                   count(*)                                  AS members,
                   min(created_at)                           AS first_at,
                   max(created_at)                           AS last_at,
                   (array_agg(id ORDER BY created_at, id))[1] AS rep_id
              FROM keyed
             GROUP BY block_id, gkey
        ),
        ins AS (
            INSERT INTO recommendations (
                block_id, cell_id, farm_id, tree_id, tree_code, tree_version,
                block_crop_id, action_type, severity, parameters, actions,
                confidence, tree_path, text_en, text_ar, valid_until,
                evaluation_snapshot, state, created_by, updated_by,
                created_at, updated_at,
                group_key, is_group, member_count, previous_member_count,
                last_counted_day, occurrence_count, day_streak,
                first_seen_at, last_seen_at, last_seen_day
            )
            SELECT k.block_id, NULL, k.farm_id, k.tree_id, k.tree_code,
                   k.tree_version, k.block_crop_id, k.action_type, k.severity,
                   k.parameters, k.actions, k.confidence, k.tree_path,
                   k.text_en, k.text_ar, k.valid_until, k.evaluation_snapshot,
                   'open', k.created_by, k.updated_by,
                   a.first_at, now(),
                   -- No baseline: a backfilled group has no yesterday, and
                   -- 0 is what `derive_spread` reads as `unknown` — a plain
                   -- count with no arrow. The first sweep after deploy rolls
                   -- a real baseline in.
                   a.gkey, TRUE, a.members, 0, NULL, 1, 1,
                   a.first_at, a.last_at, (a.last_at AT TIME ZONE 'UTC')::date
              FROM agg a
              JOIN keyed k ON k.id = a.rep_id
            RETURNING id, block_id, group_key
        )
        UPDATE recommendations r
           SET group_parent_id = ins.id,
               group_key       = ins.group_key,
               first_seen_at   = COALESCE(r.first_seen_at, r.created_at),
               last_seen_at    = COALESCE(r.last_seen_at, r.created_at),
               updated_at      = now()
          FROM ins, keyed k
         WHERE k.id = r.id
           AND k.block_id = ins.block_id
           AND k.gkey = ins.group_key
        """
    )


def _backfill_alert_groups() -> None:
    """Same collapse for alerts.

    Only tree-sourced alerts are grouped: a legacy rule alert has no leaf in
    its `rule_code` and nothing to aggregate against. The parent's `rule_code`
    is the un-suffixed `tree:<code>:<leaf>` — the Action Center splits the tree
    code out of exactly that shape, so stripping the `:cell:<uuid>` tail keeps
    a group's provenance readable by the query that already exists.
    """
    op.execute(
        f"""
        WITH keyed AS (
            SELECT a.*,
                   'tree:' || split_part(a.rule_code, ':', 2)
                           || ':' || split_part(a.rule_code, ':', 3) AS parent_rule,
                   split_part(a.rule_code, ':', 2) || ':'
                     || split_part(a.rule_code, ':', 3) || ':'
                     || COALESCE(a.action_type, 'unclassified') || ':'
                     || a.severity                                   AS gkey
              FROM alerts a
             WHERE a.deleted_at IS NULL
               AND {_ALERT_ACTIVE}
               AND a.cell_id IS NOT NULL
               AND a.group_parent_id IS NULL
               AND split_part(a.rule_code, ':', 1) = 'tree'
        ),
        agg AS (
            SELECT block_id, gkey,
                   count(*)                                  AS members,
                   min(created_at)                           AS first_at,
                   max(created_at)                           AS last_at,
                   (array_agg(id ORDER BY created_at, id))[1] AS rep_id
              FROM keyed
             GROUP BY block_id, gkey
        ),
        ins AS (
            INSERT INTO alerts (
                block_id, cell_id, rule_code, severity, action_type, status,
                diagnosis_en, diagnosis_ar, prescription_en, prescription_ar,
                signal_snapshot, created_by, updated_by, created_at, updated_at,
                group_key, is_group, member_count, previous_member_count,
                last_counted_day, occurrence_count, day_streak,
                first_seen_at, last_seen_at, last_seen_day
            )
            SELECT k.block_id, NULL, k.parent_rule, k.severity, k.action_type,
                   'open',
                   k.diagnosis_en, k.diagnosis_ar, k.prescription_en,
                   k.prescription_ar, k.signal_snapshot, k.created_by,
                   k.updated_by, a.first_at, now(),
                   a.gkey, TRUE, a.members, 0, NULL, 1, 1,
                   a.first_at, a.last_at, (a.last_at AT TIME ZONE 'UTC')::date
              FROM agg a
              JOIN keyed k ON k.id = a.rep_id
            RETURNING id, block_id, group_key
        )
        UPDATE alerts a
           SET group_parent_id = ins.id,
               group_key       = ins.group_key,
               first_seen_at   = COALESCE(a.first_seen_at, a.created_at),
               last_seen_at    = COALESCE(a.last_seen_at, a.created_at),
               updated_at      = now()
          FROM ins, keyed k
         WHERE k.id = a.id
           AND k.block_id = ins.block_id
           AND k.gkey = ins.group_key
        """
    )


def downgrade() -> None:
    # Detach children first, then drop the parents the backfill invented. A
    # parent is not a finding anyone recorded — leaving one behind after a
    # rollback would be a phantom item in the queue with no cell under it.
    for table in ("recommendations", "alerts"):
        op.execute(f"UPDATE {table} SET group_parent_id = NULL")  # noqa: S608
        op.execute(f"DELETE FROM {table} WHERE is_group = TRUE")  # noqa: S608

    op.drop_index("ix_alerts_group_parent", table_name="alerts")
    op.drop_index("uq_alerts_group_open", table_name="alerts")
    op.drop_index("uq_alerts_block_rule_open", table_name="alerts")
    op.create_index(
        "uq_alerts_block_rule_open",
        "alerts",
        ["block_id", "rule_code"],
        unique=True,
        postgresql_where=sa.text(_ALERT_ACTIVE),
    )

    op.drop_index("ix_recommendations_group_parent", table_name="recommendations")
    op.drop_index("uq_recommendations_group_open", table_name="recommendations")
    op.drop_index("uq_recommendations_block_tree_open", table_name="recommendations")
    op.create_index(
        "uq_recommendations_block_tree_open",
        "recommendations",
        ["block_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND cell_id IS NULL"),
    )

    for table in ("recommendations", "alerts"):
        op.drop_constraint(f"fk_{table}_group_parent", table, type_="foreignkey")
        for column in reversed(_group_columns()):
            op.drop_column(table, column.name)
