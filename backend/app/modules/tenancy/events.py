"""Public event types for the tenancy module.

Cross-module reactions (audit, billing, notifications, ...) subscribe
via `app.shared.eventbus`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.shared.eventbus import Event


class TenantCreatedV1(Event):
    """A new tenant was created — schema bootstrapped, settings written."""

    event_name = "tenancy.tenant_created.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    contact_email: str
    created_at: datetime
    actor_user_id: UUID | None = None
