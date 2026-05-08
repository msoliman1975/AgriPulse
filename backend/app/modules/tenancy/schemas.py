"""Pydantic request and response models for the tenancy admin API."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9-]{3,32}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CreateTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="URL-safe identifier, 3-32 chars, [a-z0-9-].")
    name: str = Field(min_length=1, max_length=255, description="Display name.")
    contact_email: EmailStr
    legal_name: str | None = None
    tax_id: str | None = None
    contact_phone: str | None = None
    default_locale: Literal["en", "ar"] = "en"
    default_unit_system: Literal["feddan", "acre", "hectare"] = "feddan"
    initial_tier: Literal["free", "standard", "premium", "enterprise"] = "free"
    owner_email: EmailStr | None = Field(
        default=None,
        description=(
            "Initial TenantOwner. When set, the create flow also provisions "
            "the Keycloak group + invites this user."
        ),
    )
    owner_full_name: str | None = Field(default=None, max_length=255)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        if not _SLUG_RE.fullmatch(value):
            raise ValueError("slug must match [a-z0-9-]{3,32}")
        return value


class UpdateTenantRequest(BaseModel):
    """All fields optional. Only present keys are applied."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = None
    tax_id: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    default_locale: Literal["en", "ar"] | None = None
    default_unit_system: Literal["feddan", "acre", "hectare"] | None = None
    default_timezone: str | None = None
    default_currency: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    logo_url: str | None = None
    branding_color: str | None = None

    @field_validator("branding_color")
    @classmethod
    def _validate_branding_color(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _HEX_COLOR_RE.fullmatch(value):
            raise ValueError("branding_color must be a #RRGGBB hex string")
        return value


class SuspendTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=2000)


class RequestDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=2000)


class PurgeTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug_confirmation: str = Field(
        description="Type the tenant slug to confirm — typo-protection."
    )
    force: bool = Field(
        default=False,
        description="Bypass the grace-window check. PlatformAdmin may not always have this.",
    )


class TenantResponse(BaseModel):
    """Slim DTO returned from POST /admin/tenants (back-compat)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    schema_name: str
    contact_email: str
    default_locale: str
    default_unit_system: str
    status: str
    created_at: datetime
    provisioning_failed: bool = False
    owner_user_id: str | None = None


class TenantDetailResponse(BaseModel):
    """Full read projection used by list and detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    legal_name: str | None
    tax_id: str | None
    contact_email: str
    contact_phone: str | None
    schema_name: str
    status: str
    default_locale: str
    default_unit_system: str
    default_timezone: str
    default_currency: str
    country_code: str
    suspended_at: datetime | None
    deleted_at: datetime | None
    last_status_reason: str | None
    purge_eligible_at: datetime | None
    keycloak_group_id: str | None = None
    pending_owner_email: str | None = None
    created_at: datetime
    updated_at: datetime


class TenantListResponse(BaseModel):
    items: list[TenantDetailResponse]
    total: int
    limit: int
    offset: int


class TenantSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cloud_cover_threshold_visualization_pct: int
    cloud_cover_threshold_analysis_pct: int
    imagery_refresh_cadence_hours: int
    alert_notification_channels: list[str]
    webhook_endpoint_url: str | None
    dashboard_default_indices: list[str]


class TenantSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tier: str
    plan_type: str | None
    started_at: datetime
    expires_at: datetime | None
    is_current: bool
    trial_start: date | None
    trial_end: date | None
    feature_flags: dict[str, Any]


class ArchiveEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    event_type: str
    actor_user_id: UUID | None
    actor_kind: str
    details: dict[str, Any]
    correlation_id: UUID | None


class TenantSidecarResponse(BaseModel):
    """Detail-page sidecar bundling settings, subscription, members, audit."""

    tenant_id: UUID
    settings: TenantSettingsResponse | None
    subscription: TenantSubscriptionResponse | None
    active_member_count: int
    recent_events: list[ArchiveEventResponse]


class TenantMetaResponse(BaseModel):
    """Enum / picker values used by admin-portal forms.

    Returned by GET /admin/tenants/_meta so the frontend doesn't hard-code
    them — adding a new tier or status only needs a backend change.
    """

    statuses: list[str]
    tiers: list[str]
    locales: list[str]
    unit_systems: list[str]
    purge_grace_days: int
