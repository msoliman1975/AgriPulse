"""Pydantic request/response schemas for the notifications module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InboxItemResponse(BaseModel):
    """One row from the current user's in-app inbox."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID | None = None
    recommendation_id: UUID | None = None
    severity: str | None = None
    title: str
    body: str
    link_url: str | None = None
    read_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime


class InboxUnreadCountResponse(BaseModel):
    count: int = Field(ge=0)


class InboxTransitionRequest(BaseModel):
    """``PATCH /inbox/{id}`` body — exactly one action."""

    action: Literal["read", "archive"]


class DeviceRegisterRequest(BaseModel):
    """``POST /devices:register`` body.

    The token is an FCM registration string — long, opaque, and rotated by the
    OS. The app sends it at sign-in and again whenever Firebase refreshes it.
    """

    token: str = Field(min_length=16, max_length=4096)
    platform: Literal["android", "ios", "web"] = "android"
    app_version: str | None = Field(default=None, max_length=32)
    # Diagnostic only: the push body is rendered from the user's saved
    # preference, not from whatever the handset happens to be set to.
    locale: str | None = Field(default=None, max_length=16)


class DeviceResponse(BaseModel):
    """A registered device. The token is deliberately not echoed back — it is a
    push credential, and nothing in the UI needs it to identify a handset."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    platform: str
    app_version: str | None = None
    locale: str | None = None
    last_seen_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
