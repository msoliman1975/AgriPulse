"""Schemas for the Action Center — one queue over recommendations + alerts.

The screen's premise is that a supervisor does not think "is this an alert or a
recommendation", they think "what needs doing today and who does it". So the
API hands back one row shape for both, with ``kind`` kept as a field rather
than as two endpoints.

Two vocabularies exist here on purpose:

``status`` is the unified lifecycle the screen's tabs are built from.
``native_status`` is the row's real state in its own table. Both travel,
because the tabs need the first and the row's buttons and audit trail need the
second — collapsing them would make an acknowledged alert indistinguishable
from a deferred recommendation in the UI.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.action_items import RecurrenceState, SpreadTrend

# What a group's members are. `cell` is a place on the map — a grid cell that
# fired. `signal` is a measurement — one index that flagged the whole block.
# The client needs the difference to label the count at all: "12 zones" and
# "8 signals" are not the same sentence, and rendering one as the other tells
# a supervisor to walk somewhere that does not exist.
MemberKind = Literal["cell", "signal"]

ItemKind = Literal["recommendation", "alert"]

# Unified lifecycle. The mapping from the native states is in service.py and
# is the single place that knows it.
UnifiedStatus = Literal["needs_action", "dispatched", "done", "dismissed"]

# Derived urgency bucket. ``monitoring`` is not a deadline — it is the standing
# "keep watching this" horizon — and ``none`` means the item declared no
# deadline at all. Keeping them apart stops a monitoring item from being
# rendered as overdue the moment it ages.
DueBucket = Literal["overdue", "today", "week", "later", "monitoring", "none"]

GroupBy = Literal["none", "action_type", "block", "due"]

# The four time horizons a decision-tree leaf can author guidance for. Alerts
# never carry them; a recommendation carries whichever ones its leaf filled in.
ActionHorizon = Literal["immediate", "short_term", "long_term", "monitoring"]


class ActionGuidance(BaseModel):
    """One line of guidance inside one horizon.

    The same shape `RecommendationResponse.actions` uses. It is repeated rather
    than imported so the Action Center schema stays readable on its own and a
    change to the recommendations module cannot silently reshape this one.
    """

    text_en: str
    text_ar: str | None = None


class TreePathStep(BaseModel):
    """One node of the walk that produced a recommendation.

    ``matched`` is None on the leaf: a leaf is where the walk stopped, not a
    condition that passed or failed, and rendering it as "no match" reads as a
    failure. ``values`` holds what the condition actually compared, which is
    the part a user checks the finding against.
    """

    model_config = ConfigDict(extra="allow")

    node_id: str
    matched: bool | None = None
    label_en: str | None = None
    label_ar: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class CellLocation(BaseModel):
    """Where a cell-scoped item actually is.

    ``row``/``col`` are kept because they identify the cell in the grid config,
    but the UI leads with the centroid: a zone code means nothing to someone
    standing in a field, and decimal degrees paste straight into a phone's map.
    """

    cell_id: UUID
    row: int
    col: int
    # Cell ordinal within its grid ("cell 3 of 36") — cheaper to read than
    # row/col arithmetic when two rows on the same block need telling apart.
    ordinal: int | None = None
    total: int | None = None
    lat: float | None = None
    lon: float | None = None
    area_m2: Decimal | None = None


class Aggregation(BaseModel):
    """How many cells this one row stands for.

    Present on every item so the client never has to branch on its absence.
    `is_group` false with `member_count` 0 is an ordinary block-scoped item —
    one place, one finding. `is_group` true means the row is the aggregate of
    `member_count` grid cells that all hit the same leaf of the same tree at
    the same severity on the same block, and the cells themselves are one
    request away at `/action-items/{id}/members`.
    """

    is_group: bool = False
    member_count: int = 0
    member_kind: MemberKind = "cell"
    # What the count was at the end of the previous evaluation day, and which
    # way that makes this finding move. Without the baseline the aggregation
    # would hide the one thing it must not: a 12-cell finding and a 20-cell one
    # render identically, because a count with no baseline is not a trend.
    previous_member_count: int = 0
    trend: SpreadTrend = "unknown"


class Recurrence(BaseModel):
    """How long this finding has been true, and whether anyone has moved.

    The counters are facts recorded by the evaluator; `state` is the reading
    the UI badges. Severity is deliberately not derived from any of this — the
    tree decided the agronomy, and how long a supervisor has left it alone is a
    different fact that must not be allowed to rewrite the first.
    """

    state: RecurrenceState = "new"
    # Distinct days this item has fired, first day included.
    occurrence_count: int = 1
    # Consecutive firing days. 6 means six mornings in a row.
    day_streak: int = 1
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class ActionItemMember(BaseModel):
    """One cell under a group.

    Not actionable on its own — the group is the unit a supervisor decides
    about. This is what the map colours and what the drill-down lists, so it
    carries the cell's own location, its own severity and its own clock.
    """

    id: UUID
    cell: CellLocation | None = None
    # Set on a `signal` member: the thing that fired, e.g. the index code
    # `ndvi`. A cell member has a location instead and leaves this None.
    label: str | None = None
    severity: str
    native_status: str
    text_en: str | None = None
    text_ar: str | None = None
    created_at: datetime
    last_seen_at: datetime | None = None
    # Set once this cell stopped firing. The member stays attached — a cell
    # that has gone quiet is how a receding outbreak looks, and dropping it
    # would make that indistinguishable from one that never spread.
    cleared_at: datetime | None = None
    occurrence_count: int = 1
    day_streak: int = 1


class ActionItemMembersResponse(BaseModel):
    item_id: UUID
    kind: ItemKind
    total: int
    # Members still firing as of the last evaluation.
    active: int
    members: list[ActionItemMember]


class ActionItem(BaseModel):
    """One row of the unified queue."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ItemKind
    status: UnifiedStatus
    native_status: str

    farm_id: UUID
    block_id: UUID
    block_code: str
    block_name: str | None
    # NULL for a block-scoped item; the whole block is the unit there.
    cell: CellLocation | None = None

    # NULL only for alerts opened before migration 0063 — the UI shows those as
    # unclassified rather than inventing a verb someone might act on.
    action_type: str | None
    severity: str
    title_en: str
    title_ar: str | None
    # Alerts carry a prescription line; recommendations put their guidance in
    # `actions` by horizon. Both are optional.
    detail_en: str | None = None
    detail_ar: str | None = None

    tree_code: str | None
    tree_version: int | None
    # 1.0 for alerts — they express certainty, not probability.
    confidence: Decimal | None

    created_at: datetime
    valid_until: datetime | None = None
    due_bucket: DueBucket
    due_date: date | None = None

    # The member responsible for this item's BLOCK (blocks.agronomist_membership_id).
    # Present whether or not the item has been dispatched — it is what dispatch
    # defaults to, so the dialog has to know it for a single item and not only
    # when the queue happens to be grouped by block.
    responsible_membership_id: UUID | None = None

    # Set once dispatched, read off the linked board activity.
    assigned_membership_id: UUID | None = None
    activity_id: UUID | None = None
    scheduled_date: date | None = None

    # When each lifecycle step happened, in the item's own vocabulary. An alert
    # fills the first two, a recommendation the second two, and each kind
    # leaves the other pair NULL — one shared "closed_at" would report an
    # applied recommendation and a resolved alert as the same event.
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    applied_at: datetime | None = None
    dismissed_at: datetime | None = None
    # How long the item is hidden for. `deferred_until` is a recommendation,
    # `snoozed_until` an alert; both mean "do not ask me again until then".
    deferred_until: datetime | None = None
    snoozed_until: datetime | None = None

    # One-line "because …" derived from the deciding condition. Always present
    # for both kinds.
    why: str | None = None
    reasoning: dict[str, Any] = Field(default_factory=dict)
    # The full walk behind a recommendation, deciding step included. Empty for
    # an alert, which has a signal snapshot rather than a path. This is the
    # row's own copy, written when it fired — not the evaluation trace, which
    # is purged after 100 days.
    tree_path: list[TreePathStep] = Field(default_factory=list)
    # Guidance by horizon, as the leaf authored it. Empty for an alert and for
    # a recommendation whose leaf carried only a one-line summary.
    actions: dict[ActionHorizon, list[ActionGuidance]] = Field(default_factory=dict)

    # Both always present, so a client never has to branch on absence.
    aggregation: Aggregation = Field(default_factory=Aggregation)
    recurrence: Recurrence = Field(default_factory=Recurrence)


class ActionItemGroup(BaseModel):
    """Server-side grouping, so the client is not the thing that decides what a
    group is. Counts are of the whole group, not the returned page."""

    key: str
    label: str
    count: int
    critical_count: int
    block_count: int
    # Cells covered, not rows shown: a group of 14 contributes 14. Counting
    # rows here would report a quieter farm every time the aggregation worked.
    cell_count: int
    # Rows in this group that are themselves aggregates of several cells.
    aggregate_count: int = 0
    # Aggregates that covered materially more cells today than yesterday. The
    # count a supervisor should read first — a spreading finding outranks a
    # merely persistent one.
    spreading_count: int = 0
    # Rows firing on consecutive days with nobody acting on them.
    recurring_count: int = 0
    # Only populated when grouping by block: the member responsible for it.
    responsible_membership_id: UUID | None = None
    items: list[ActionItem]


class ActionItemListResponse(BaseModel):
    total: int
    # Per-tab counts for the whole filtered set (date range and filters
    # applied, tab NOT applied) so a tab never promises rows the active
    # filters have already excluded.
    status_counts: dict[str, int]
    grouped_by: GroupBy
    groups: list[ActionItemGroup]


class DispatchRequest(BaseModel):
    """Send one or more items to a team member, as board work or a field visit."""

    model_config = ConfigDict(extra="forbid")

    item_ids: list[UUID] = Field(min_length=1, max_length=200)
    # Omit to let the server default each item to its block's responsible
    # member. Explicit wins for the whole batch.
    assigned_membership_id: UUID | None = None
    scheduled_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    # `board` writes a plan activity, as before. `scout` opens a scouting visit
    # the mobile app can claim, start and submit against, and pushes it to the
    # assignee's handset. Default stays `board` so existing callers are
    # untouched — a silent change of destination is how work disappears.
    target: Literal["board", "scout"] = "board"


class DispatchResultItem(BaseModel):
    item_id: UUID
    kind: ItemKind
    activity_id: UUID | None
    # Set instead of activity_id when target is `scout`. None with no error and
    # `already_dispatched` true means a live visit already covered the item —
    # usually one the auto-dispatch rules opened first.
    visit_id: UUID | None = None
    already_dispatched: bool = False
    assigned_membership_id: UUID | None
    # True when the assignee came from the block rather than the request, so
    # the UI can say where a default came from instead of assigning silently.
    assignee_defaulted: bool = False
    error: str | None = None


class DispatchResponse(BaseModel):
    dispatched: int
    failed: int
    results: list[DispatchResultItem]
