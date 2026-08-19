"""One card per anomalous block, not one per index that noticed.

0079 collapsed *cell-scoped* output into group parents. It left block-scoped
alerts alone on the reasoning that one alert per block per rule is already the
right unit. Measured against prod, that reasoning was half wrong.

Every block-scoped alert in the live tenant — 444 of 445 — comes from the grid
spatial-anomaly sweep, which raises one alert per block **per index**. NDVI,
SAVI, EVI, GNDVI and MSAVI are correlated vegetation-vigour measures, so a
single physical anomaly lights up five to nine of them at once:

    1 index on a block+severity ..... 39 pairs
    2-5 indices .................... 49 pairs
    6-9 indices .................... 38 pairs

So 87 of 126 block-severity pairs were carrying more than one card for one
problem, and 38 were carrying six or more. Worse, each one published its own
`AlertOpenedV1` — so one anomalous block generated up to nine notifications for
a single trip.

This groups them on `(block_id, grid:spatial_anomaly:<action>:<severity>)`. The
parent is block-scoped, so `alerts.block_id NOT NULL` still holds and nothing
downstream has to learn about an alert with no block.

**Why not group the other way round.** One index across many blocks collapses
harder — 445 into 77 rather than 126 — but produces a card nobody can act on:
"NDVI anomaly on 40 blocks" is still forty separate visits. The block is the
unit of work, so the block is the unit of aggregation. Which indices fired is
detail, and the drill-down carries it.

The members keep their own `grid:<index>_spatial_anomaly` rule_codes, which is
what keeps each index deduping independently under
`uq_alerts_block_rule_open`; the parent takes `grid:spatial_anomaly`, a code no
member can collide with, and is governed by `uq_alerts_group_open` instead.

Backfill covers open/acknowledged/snoozed rows only. Resolved history is not
rewritten.

Revision ID: 0080
Revises: 0079
"""

from __future__ import annotations

from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

_ACTIVE = "status IN ('open', 'acknowledged', 'snoozed')"
_GRID_PARENT_RULE = "grid:spatial_anomaly"

# `action_type` is NULL on every grid alert (the sweep names no verb), but the
# key is built with the same COALESCE the engine uses so a backfilled group and
# the next sweep's firing land on the same string rather than forking.
_GROUP_KEY = (
    "'grid:spatial_anomaly:' || COALESCE(a.action_type, 'unclassified') || ':' || a.severity"
)


def upgrade() -> None:
    op.execute(
        f"""
        WITH keyed AS (
            SELECT a.*, {_GROUP_KEY} AS gkey
              FROM alerts a
             WHERE a.deleted_at IS NULL
               AND a.{_ACTIVE}
               AND a.cell_id IS NULL
               AND a.group_parent_id IS NULL
               AND a.is_group = FALSE
               AND a.rule_code LIKE 'grid:%'
               AND a.rule_code <> '{_GRID_PARENT_RULE}'
        ),
        agg AS (
            SELECT block_id, gkey, severity,
                   count(*)                                  AS members,
                   min(created_at)                           AS first_at,
                   max(created_at)                           AS last_at,
                   (array_agg(id ORDER BY created_at, id))[1] AS rep_id
              FROM keyed
             GROUP BY block_id, gkey, severity
        ),
        ins AS (
            INSERT INTO alerts (
                block_id, cell_id, rule_code, severity, action_type, status,
                diagnosis_en, diagnosis_ar, signal_snapshot,
                created_by, updated_by, created_at, updated_at,
                group_key, is_group, member_count, previous_member_count,
                last_counted_day, occurrence_count, day_streak,
                first_seen_at, last_seen_at, last_seen_day
            )
            SELECT k.block_id, NULL, '{_GRID_PARENT_RULE}', k.severity,
                   k.action_type, 'open',
                   -- The parent stands for a block, so its text cannot name an
                   -- index. Which ones fired is on the members.
                   'Spatial anomaly detected on this block. Open it to see '
                     || 'which indices flagged it.',
                   'تم رصد شذوذ مكاني في هذا الحقل. افتحه لمعرفة المؤشرات التي رصدته.',
                   NULL,
                   k.created_by, k.updated_by, a.first_at, now(),
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
        """  # noqa: S608 - every interpolation is a module constant
    )


def downgrade() -> None:
    # Detach first, then drop the parents this migration invented. A parent is
    # not a finding anybody recorded — leaving one behind after a rollback
    # would be a phantom card with no index under it.
    op.execute(
        f"UPDATE alerts SET group_parent_id = NULL, group_key = NULL "  # noqa: S608
        f" WHERE group_parent_id IN (SELECT id FROM alerts WHERE rule_code = '{_GRID_PARENT_RULE}')"
    )
    op.execute(
        f"DELETE FROM alerts WHERE is_group = TRUE AND rule_code = '{_GRID_PARENT_RULE}'"  # noqa: S608
    )
