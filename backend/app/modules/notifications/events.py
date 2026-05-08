"""Public event types for the notifications module.

PR-B emits this event from the in-app channel after a row lands in
``in_app_inbox`` so SSE listeners (PR-C) can fan it out to connected
users without re-querying.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class InboxItemCreatedV1(Event):
    event_name: ClassVar[str] = "notifications.inbox_item_created.v1"

    inbox_item_id: UUID
    user_id: UUID
    tenant_id: UUID
    alert_id: UUID | None = None
    # Source-of-truth id when the inbox item carries a recommendation
    # (mutually exclusive with ``alert_id`` per the in_app_inbox/dispatches
    # check constraint). Optional with default for back-compat.
    recommendation_id: UUID | None = None
    severity: str | None = None
    title: str
    body: str
    link_url: str | None = None
    created_at: datetime
