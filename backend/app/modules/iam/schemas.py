"""Pydantic response models for the iam endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: str
    numerals: str
    unit_system: str
    timezone: str
    date_format: str
    notification_channels: list[str]


class TenantRoleResponse(BaseModel):
    role: str
    granted_at: datetime


class TenantMembershipResponse(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    status: str
    joined_at: datetime | None
    tenant_roles: list[TenantRoleResponse]


class FarmScopeResponse(BaseModel):
    farm_id: UUID
    role: str
    granted_at: datetime


class PlatformRoleResponse(BaseModel):
    role: str
    granted_at: datetime


class MeResponse(BaseModel):
    """Aggregate response for GET /api/v1/me."""

    id: UUID
    email: str
    full_name: str
    phone: str | None
    avatar_url: str | None
    status: str
    last_login_at: datetime | None
    preferences: UserPreferencesResponse
    platform_roles: list[PlatformRoleResponse]
    tenant_memberships: list[TenantMembershipResponse]
    farm_scopes: list[FarmScopeResponse]
