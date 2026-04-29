"""Public event types for the iam module."""

from __future__ import annotations

from uuid import UUID

from app.shared.eventbus import Event


class UserUpsertedV1(Event):
    """A user record was created or refreshed from a Keycloak login."""

    event_name = "iam.user_upserted.v1"

    user_id: UUID
    keycloak_subject: str
    email: str
    is_new: bool
