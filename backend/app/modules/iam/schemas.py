"""Pydantic response models for the iam endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
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


# =====================================================================
# Tenant user management (PATCH /v1/users etc.)
# =====================================================================


from pydantic import EmailStr, Field  # noqa: E402


class TenantUserResponse(BaseModel):
    """Row in `GET /v1/users`. Joined: user + their tenant_membership.

    `membership_id` is what the farms members API expects when assigning
    a per-farm role, so the frontend's member dropdown reads from here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    phone: str | None
    avatar_url: str | None
    status: str  # users.status
    last_login_at: datetime | None
    keycloak_subject: str | None
    membership_id: UUID
    membership_status: str
    joined_at: datetime | None
    tenant_roles: list[str]
    preferences: UserPreferencesResponse | None


class UserInviteRequest(BaseModel):
    """POST /v1/users:invite — invite a new user to the current tenant."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    tenant_role: str = Field(
        default="Viewer",
        description="One of TenantOwner / TenantAdmin / BillingAdmin / Viewer.",
    )


class UserInviteResponse(BaseModel):
    user_id: UUID
    membership_id: UUID
    keycloak_provisioning: str  # "succeeded" | "pending"
    keycloak_subject: str | None
    # IH-2: first-login credential outcome. When `keycloak_email_sent` is
    # False and provisioning succeeded, `temporary_password` carries a
    # one-time credential for the inviting admin to hand off (SMTP-free
    # onboarding). It's null when an email went out or when KC is pending.
    keycloak_email_sent: bool = False
    temporary_password: str | None = None


class UserResendInviteResponse(BaseModel):
    """POST /v1/users/{user_id}:resend-invite."""

    keycloak_provisioning: str  # "succeeded" | "pending"
    keycloak_email_sent: bool = False
    temporary_password: str | None = None


class UserUpdateRequest(BaseModel):
    """PATCH /v1/users/{user_id}."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=500)
    preferences: dict[str, Any] | None = None  # partial preferences patch
