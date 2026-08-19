"""Grouping and recurrence, shared by the two tables that need them.

`recommendations` and `alerts` are read through one UNION in the Action Center
and dispatched to one queue, so an aggregation concept that lived in only one
of them would be a concept the screen cannot use. Both the column set and the
key derivation live here so the two sides cannot drift — the failure mode this
codebase has already paid for more than once with mirrored constants.

Nothing here talks to a session. The repositories own the SQL; this module owns
the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

# Recurrence vocabulary. `new` is the absence of a badge, not a badge.
RecurrenceState = Literal["new", "recurring", "persistent"]

# Which way a group is moving between evaluation days. `steady` is the absence
# of a badge; `unknown` is a group with no yesterday to compare against, which
# is not the same thing and must not be drawn as steadiness.
SpreadTrend = Literal["unknown", "steady", "spreading", "receding"]

# A group has to move by BOTH of these to count as spreading or receding. One
# cell either way on a 30-cell block is noise — the grid re-evaluates every
# morning against imagery that moves on its own — and an arrow that flickers
# daily is an arrow people stop reading.
SPREAD_MIN_CELLS = 2
SPREAD_MIN_RATIO = 0.2

# Consecutive firing days at which an item stops being news. Two is the
# smallest number that means anything — one day is just "it fired".
RECURRING_AFTER_DAYS = 2
# Consecutive firing days with nobody acting, at which the item is being
# ignored rather than merely repeating.
PERSISTENT_AFTER_DAYS = 5


def build_group_key(
    *,
    tree_code: str,
    leaf_node_id: str | None,
    action_type: str | None,
    severity: str,
) -> str:
    """The aggregation identity of one finding.

    "Same block, same tree, same action, same kind, same severity" — block is
    the other half of the unique index and is not repeated in the string, and
    kind is implied by the table the row lives in.

    `leaf_node_id` is in the key because two leaves of one tree are two
    different findings even when they agree on verb and severity; the leaf is
    what the text and the prescription come from. It falls back to the literal
    ``leaf`` to match ``_open_alert_from_tree``'s own fallback — a row whose
    path was not recorded must still land on a stable key rather than a new one
    every evaluation.
    """
    return ":".join(
        (
            tree_code,
            leaf_node_id or "leaf",
            action_type or "unclassified",
            severity,
        )
    )


# The rule_code every grid-anomaly group parent carries. The per-index members
# keep their own `grid:<index>_spatial_anomaly` codes, which is what keeps each
# index deduping on its own; the parent needs a code of its own that no member
# can collide with.
GRID_GROUP_RULE_CODE = "grid:spatial_anomaly"

# Today in the tenant's own timezone. Shared by both repositories because both
# write recurrence counters and the day boundary must be the same one — a
# streak cut at a different midnight on each table is worse than no streak.
TENANT_TODAY_SQL = (
    "SELECT (now() AT TIME ZONE default_timezone)::date "
    "FROM public.tenants WHERE schema_name = :s"
)


def build_grid_group_key(*, action_type: str | None, severity: str) -> str:
    """The aggregation identity of one block's spatial anomaly.

    Deliberately NOT keyed on the index. NDVI, SAVI, EVI, GNDVI and MSAVI are
    correlated vegetation-vigour measures, so one physical anomaly lights up
    five to nine of them at once and the block gets a card per index for a
    single problem. Measured on prod: 87 of 126 block-severity pairs carried
    two or more indices, 38 carried six or more.

    Grouped the other way round — one index across many blocks — the count
    collapses harder but the card becomes unactionable: "NDVI anomaly on 40
    blocks" is still forty separate visits. The block is the unit of work, so
    the block is the unit of aggregation, and which indices fired is detail the
    drill-down carries.
    """
    return ":".join(("grid", "spatial_anomaly", action_type or "unclassified", severity))


def derive_recurrence(
    *,
    day_streak: int,
    occurrence_count: int,
    acted: bool,
) -> RecurrenceState:
    """How loudly the queue should say "this again".

    `acted` means somebody has dispatched, acknowledged or deferred the item.
    An item under active treatment that keeps firing is expected — the tree has
    no way to know a spray happened yesterday — so it never escalates past
    `recurring`. Escalation is about neglect, not about persistence.

    Severity is deliberately not a function of this. The tree decided what the
    agronomy is; how long a supervisor has left it alone is a different fact,
    and folding the second into the first would make the row disagree with the
    decision that produced it.
    """
    streak = max(day_streak, 0)
    if streak >= PERSISTENT_AFTER_DAYS and not acted:
        return "persistent"
    if streak >= RECURRING_AFTER_DAYS or occurrence_count > 1:
        return "recurring"
    return "new"


def derive_spread(
    *,
    is_group: bool,
    member_count: int,
    previous_member_count: int,
) -> SpreadTrend:
    """Which way an aggregated finding is moving.

    This exists because aggregation can hide the one thing it must not: with
    only a current count on the card, a 12-cell finding and a 20-cell one read
    identically. A count with no baseline is not a trend.

    `unknown` covers the group's first day, where `previous_member_count` was
    seeded to match and there is genuinely nothing to compare — reporting that
    as `steady` would claim a stability nobody has observed yet.
    """
    if not is_group or member_count <= 0:
        return "unknown"
    if previous_member_count <= 0:
        return "unknown"
    delta = member_count - previous_member_count
    if abs(delta) < SPREAD_MIN_CELLS:
        return "steady"
    if abs(delta) < previous_member_count * SPREAD_MIN_RATIO:
        return "steady"
    return "spreading" if delta > 0 else "receding"


class GroupingMixin:
    """The columns tenant migration 0079 adds to both tables.

    A parent (`is_group`) is the actionable unit: it carries `cell_id IS NULL`
    and is what every list, dispatch and transition addresses. Children hang
    off it by `group_parent_id`, keep their own cell and their own snapshot,
    and are filtered out of the queue.

    A block-scoped item is neither — it has no parent and is not a parent, and
    it uses the same recurrence counters directly.
    """

    group_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    @declared_attr
    @classmethod
    def group_parent_id(cls) -> Mapped[object]:
        # Self-referential FK: the target table is whichever table the mixin
        # lands on, so it has to be resolved per class rather than declared
        # once with a literal name.
        return mapped_column(
            PG_UUID(as_uuid=True),
            ForeignKey(f"{cls.__tablename__}.id", ondelete="CASCADE"),  # type: ignore[attr-defined]
            nullable=True,
        )

    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    # Children still firing. A cell that has gone quiet stays attached for
    # history but stops counting.
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # The baseline `member_count` is read against. Rolled once per tenant-day.
    previous_member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_counted_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    day_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Tenant-local calendar day of the last firing. Stored, not derived: the
    # boundary is the tenant's timezone and a UTC-derived day would split or
    # merge streaks for every tenant that is not on it.
    last_seen_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class GroupingSQL:
    """SQL the two tables need in identical shape but cannot literally share.

    They disagree on two names — `recommendations.state` vs `alerts.status`,
    and which values of it count as still-live — and on nothing else that
    matters here. Parameterising those two and generating the rest keeps the
    recurrence arithmetic in one place; writing it twice is how the streak on
    one table ends up a day out from the streak on the other.

    `table`, `state_column` and `active` are module constants, never caller
    input, which is why the f-strings below are not an injection surface.
    """

    table: str
    state_column: str
    # SQL predicate for "not yet closed", in this table's vocabulary.
    active: str

    @property
    def bump(self) -> str:
        """Record one more firing of a row that already exists.

        The whole point of this statement is that it runs on the path where
        the old code returned `None` and wrote nothing. `occurrence_count`
        moves once per day, not once per evaluation, so a sweep that runs
        twice in one morning does not read as two days of trouble.

        `day_streak` is the consecutive run: unchanged if today is already
        counted, +1 if yesterday was the last one, reset to 1 otherwise —
        including the NULL case, where there is no previous day to be
        consecutive with.
        """
        return f"""
            UPDATE {self.table}
               SET last_seen_at = now(),
                   occurrence_count = occurrence_count + CASE
                       WHEN last_seen_day IS DISTINCT FROM CAST(:today AS date) THEN 1
                       ELSE 0 END,
                   day_streak = CASE
                       WHEN last_seen_day = CAST(:today AS date) THEN day_streak
                       WHEN last_seen_day = CAST(:today AS date) - 1 THEN day_streak + 1
                       ELSE 1 END,
                   last_seen_day = CAST(:today AS date),
                   first_seen_at = COALESCE(first_seen_at, created_at),
                   updated_at = now(),
                   updated_by = :actor
             WHERE id = :id
         RETURNING id, occurrence_count, day_streak
        """  # noqa: S608

    @property
    def refresh_member_count(self) -> str:
        """Recount a parent's still-firing children, and roll the baseline.

        Counts children that are open AND not cleared: a cell that stopped
        firing stays attached so the group keeps its history, but it is not
        part of "how big is this right now".

        The baseline moves at most once per tenant-day. A sweep can run several
        times a morning, and a baseline that moved with it would decay to "same
        as five minutes ago" — always steady, never a trend. Postgres evaluates
        every SET expression against the OLD row, so reading `p.member_count`
        here captures the pre-recount value even though the same statement
        replaces it.
        """
        return f"""
            UPDATE {self.table} p
               SET previous_member_count = CASE
                       WHEN p.last_counted_day IS DISTINCT FROM CAST(:today AS date)
                       THEN p.member_count ELSE p.previous_member_count END,
                   last_counted_day = CAST(:today AS date),
                   member_count = (
                       SELECT count(*) FROM {self.table} c
                        WHERE c.group_parent_id = p.id
                          AND c.deleted_at IS NULL
                          AND c.cleared_at IS NULL
                          AND c.{self.state_column} IN ({self.active})
                   ),
                   updated_at = now()
             WHERE p.id = :parent_id
         RETURNING p.member_count
        """  # noqa: S608

    def clear_stale_children(self, scope: str) -> str:
        """Mark children that did not fire in this pass as cleared.

        `scope` narrows to the tree whose sweep just finished — clearing must
        never reach a group some other tree owns, and it must run even when
        that tree fired nowhere, which is the case a "for each fired row"
        loop silently skips.

        Returns the parents that lost a child so the caller can recount them.
        """
        return f"""
            UPDATE {self.table}
               SET cleared_at = now(), updated_at = now()
             WHERE block_id = :block_id
               AND {scope}
               AND group_parent_id IS NOT NULL
               AND cleared_at IS NULL
               AND deleted_at IS NULL
               AND {self.state_column} IN ({self.active})
               AND NOT (id = ANY(:fired))
         RETURNING group_parent_id
        """  # noqa: S608

    def refresh_member_counts_scoped(self, scope: str) -> str:
        """Recount every live group one tree owns on one block, in one write.

        The per-parent form would be an N+1 inside a sweep that already walks
        every cell of every block — and the counts all move for the same
        reason, at the same moment, so there is nothing to gain by doing them
        one at a time.
        """
        return f"""
            UPDATE {self.table} p
               SET previous_member_count = CASE
                       WHEN p.last_counted_day IS DISTINCT FROM CAST(:today AS date)
                       THEN p.member_count ELSE p.previous_member_count END,
                   last_counted_day = CAST(:today AS date),
                   member_count = (
                       SELECT count(*) FROM {self.table} c
                        WHERE c.group_parent_id = p.id
                          AND c.deleted_at IS NULL
                          AND c.cleared_at IS NULL
                          AND c.{self.state_column} IN ({self.active})
                   ),
                   updated_at = now()
             WHERE p.block_id = :block_id
               AND {scope}
               AND p.is_group = TRUE
               AND p.deleted_at IS NULL
               AND p.{self.state_column} IN ({self.active})
        """  # noqa: S608

    def open_parent_ids(self, scope: str) -> str:
        """Every live group this tree owns on this block."""
        return f"""
            SELECT id FROM {self.table}
             WHERE block_id = :block_id
               AND {scope}
               AND is_group = TRUE
               AND deleted_at IS NULL
               AND {self.state_column} IN ({self.active})
        """  # noqa: S608


REC_SQL = GroupingSQL(table="recommendations", state_column="state", active="'open'")
ALERT_SQL = GroupingSQL(
    table="alerts",
    state_column="status",
    active="'open', 'acknowledged', 'snoozed'",
)


__all__ = [
    "ALERT_SQL",
    "GRID_GROUP_RULE_CODE",
    "TENANT_TODAY_SQL",
    "build_grid_group_key",
    "SPREAD_MIN_CELLS",
    "SPREAD_MIN_RATIO",
    "SpreadTrend",
    "derive_spread",
    "PERSISTENT_AFTER_DAYS",
    "RECURRING_AFTER_DAYS",
    "REC_SQL",
    "GroupingMixin",
    "GroupingSQL",
    "RecurrenceState",
    "build_group_key",
    "derive_recurrence",
]
