"""Public event types for the scouting module.

Versioned per ARCHITECTURE.md § 6.1 — bumping the suffix is a breaking schema
change for subscribers.

``ScoutingVisitAssignedV1`` is what makes a scout's phone announce the work.
It fires when a visit acquires an assignee, whoever did it: a routing rule, a
supervisor, or an ad-hoc dispatch that named someone. It deliberately does
**not** fire when a scout claims a visit themselves — pushing "you have a
visit" to the person who just tapped "I'll take it" is noise.

The payload carries everything a notification needs to render. Like the alert
and recommendation events, a sync subscriber runs on a separate connection and
cannot read the not-yet-committed ``scouting_visits`` row, so the content has
to ride on the event itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class ScoutingVisitAssignedV1(Event):
    event_name: ClassVar[str] = "scouting.visit_assigned.v1"

    visit_id: UUID
    farm_id: UUID
    block_id: UUID
    # Sub-block grid cell when the anomaly is narrower than the block.
    cell_id: UUID | None = None
    assignee_user_id: UUID
    origin: str
    severity: str
    priority: str
    title: str
    due_by: datetime | None = None
    assigned_at: datetime
    # Tenant context, so a cross-module subscriber can scope its writes without
    # walking every tenant.
    tenant_schema: str | None = None
    # NULL when a routing rule assigned it rather than a person — the
    # difference a supervisor board reads, and worth carrying into the audit
    # trail of who told whom to walk somewhere.
    assigned_by_user_id: UUID | None = None
    # The supervisor's own words, on `ad_hoc` visits only.
    instruction: str | None = None
