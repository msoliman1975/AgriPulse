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
