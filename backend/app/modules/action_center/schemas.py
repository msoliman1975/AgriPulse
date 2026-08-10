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

    # One-line "because …" derived from the deciding condition. Always present
    # for both kinds; the full decision path lives behind the trace endpoint
    # and may have been purged.
    why: str | None = None
    reasoning: dict[str, Any] = Field(default_factory=dict)


class ActionItemGroup(BaseModel):
    """Server-side grouping, so the client is not the thing that decides what a
    group is. Counts are of the whole group, not the returned page."""

    key: str
    label: str
    count: int
    critical_count: int
    block_count: int
    cell_count: int
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
