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


class TenantUpdatedV1(Event):
    """Tenant profile fields were edited."""

    event_name = "tenancy.tenant_updated.v1"

    tenant_id: UUID
    slug: str
    changed_fields: tuple[str, ...]
    actor_user_id: UUID | None = None


class TenantSuspendedV1(Event):
    """Tenant entered status='suspended'. Sign-ins blocked from now on."""

    event_name = "tenancy.tenant_suspended.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    suspended_at: datetime
    reason: str | None = None
    actor_user_id: UUID | None = None


class TenantReactivatedV1(Event):
    """Tenant returned to status='active'."""

    event_name = "tenancy.tenant_reactivated.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    reactivated_at: datetime
    actor_user_id: UUID | None = None


class TenantDeletionRequestedV1(Event):
    """Tenant marked status='pending_delete'; grace window started."""

    event_name = "tenancy.tenant_deletion_requested.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    requested_at: datetime
    purge_eligible_at: datetime
    reason: str | None = None
    actor_user_id: UUID | None = None


class TenantDeletionCancelledV1(Event):
    """Pending-delete grace window cancelled; tenant returns to suspended."""

    event_name = "tenancy.tenant_deletion_cancelled.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    cancelled_at: datetime
    actor_user_id: UUID | None = None


class TenantPurgedV1(Event):
    """Tenant schema dropped + public rows deleted. Irreversible."""

    event_name = "tenancy.tenant_purged.v1"

    tenant_id: UUID
    slug: str
    schema_name: str
    purged_at: datetime
    actor_user_id: UUID | None = None
