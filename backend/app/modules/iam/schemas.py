"""Pydantic response models for the iam endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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


class NotificationChannelAvailability(BaseModel):
    """Whether a channel the caller ticked can actually deliver to them.

    Separate from the choice itself. A person can select `email` while their
    tenant has email switched off; the screen has to be able to say so rather
    than accept the tick and drop the message.
    """

    channel: Literal["in_app", "email", "push"]
    deliverable: bool
    # None when deliverable. Otherwise one of: tenant_disabled,
    # no_email_address, no_registered_device.
    reason: str | None = None


class MyNotificationPreferencesResponse(BaseModel):
    """GET/PATCH /v1/me/notification-preferences."""

    # The caller's stored choice, or the fan-out's own defaults when they
    # have no preferences row yet.
    channels: list[str]
    # Which locale the alert and recommendation templates render in. Read
    # only by the notification fan-out — see iam/notification_prefs.py.
    language: Literal["en", "ar"]
    email_address: str | None
    registered_device_count: int
    # What the tenant allows, before the caller's own choice narrows it.
    tenant_channels: list[str]
    availability: list[NotificationChannelAvailability]


class MyNotificationPreferencesUpdate(BaseModel):
    """PATCH body. Omitting a field leaves it as it is.

    An empty `channels` list is a valid choice, not a mistake, so the field is
    optional rather than defaulted — `None` means "do not touch", `[]` means
    "send me nothing".
    """

    model_config = ConfigDict(extra="forbid")

    channels: list[str] | None = None
    language: Literal["en", "ar"] | None = None


class TenantRoleResponse(BaseModel):
    role: str
    granted_at: datetime


class TenantMembershipResponse(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    # Arabic display name (public migration 0075). Null when nobody has
    # written one; the shell falls back to `tenant_name`.
    tenant_name_ar: str | None = None
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
    # Arabic display name (public migration 0076). Never written by the login
    # upsert, so it stays NULL until somebody sets it; readers fall back.
    full_name_ar: str | None = None
    phone: str | None
    avatar_url: str | None
    status: str
    last_login_at: datetime | None
    preferences: UserPreferencesResponse
    platform_roles: list[PlatformRoleResponse]
    tenant_memberships: list[TenantMembershipResponse]
    farm_scopes: list[FarmScopeResponse]
    #: role -> the capabilities it grants *right now*, for this caller's roles
    #: only. Includes any runtime override a Platform Admin has applied, which
    #: is why the frontend must resolve against this rather than its bundled
    #: mirror of the YAML. A wildcard role is sent as the literal `["*"]`.
    capabilities: dict[str, list[str]] = {}


# =====================================================================
# Tenant user management (PATCH /v1/users etc.)
# =====================================================================


from pydantic import AliasChoices, EmailStr, Field, model_validator  # noqa: E402

from app.shared.rbac import (  # noqa: E402
    FARM_TIER_ROLES,
    TENANT_ASSIGNABLE_ROLES,
    RoleNotAssignableError,
    assignment_tier,
)


class FarmRoleGrantResponse(BaseModel):
    """One active row of `public.farm_scopes` for a tenant member."""

    farm_id: UUID
    role: str


class TenantUserResponse(BaseModel):
    """Row in `GET /v1/users`. Joined: user + their tenant_membership.

    `membership_id` is what the farms members API expects when assigning
    a per-farm role, so the frontend's member dropdown reads from here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    # Which of email/phone is this person's real handle. A field worker signs
    # in with a phone and carries a synthetic, undeliverable address, so a UI
    # that falls back to `full_name || email` shows `+2010…@scouts…` where a
    # name belongs — and implies somewhere you could write to.
    identity_kind: Literal["email", "phone"] = "email"
    full_name: str
    full_name_ar: str | None = None
    phone: str | None
    avatar_url: str | None
    status: str  # users.status
    last_login_at: datetime | None
    keycloak_subject: str | None
    membership_id: UUID
    membership_status: str
    joined_at: datetime | None
    tenant_roles: list[str]
    # Farm-tier roles this member holds, one entry per farm. Without this the
    # roles column is blank for anyone who is not a tenant-tier member, which
    # reads as "no role" rather than "Agronomist on two farms". Farm names are
    # not joined here: `farm_scopes` lives in `public` and the names live in
    # the tenant schema, so the frontend joins them against its farms list.
    farm_roles: list[FarmRoleGrantResponse]
    preferences: UserPreferencesResponse | None


class RoleAssignmentMixin(BaseModel):
    """The `role` + `farm_ids` pair, shared by invite and role change.

    Two tiers reach this field and they are stored in different tables, so
    the payload is validated as a unit rather than field by field:

      * tenant tier (TenantOwner / TenantAdmin / BillingAdmin) applies to
        the whole tenant, and `farm_ids` is meaningless — sending it is an
        error, not something to ignore, because silently dropping it would
        look like the farms had been restricted.
      * farm tier (FarmManager / Agronomist / FieldOperator / Scout /
        Viewer) is granted one farm at a time, so at least one farm id is
        required. Without it the user signs in and is 403 everywhere, which
        is the failure this validation exists to prevent.

    PlatformAdmin and PlatformSupport are refused here with a 422. The
    allow-list comes from `app.shared.rbac`, which builds it from the role
    enums, so this is not a blocklist that can fall behind.
    """

    role: str = Field(
        default="Viewer",
        # The field was called `tenant_role` while only tenant-tier roles
        # could be assigned. Kept as an accepted alias so an in-flight
        # frontend build and the stored OpenAPI clients keep working.
        validation_alias=AliasChoices("role", "tenant_role"),
        description=(
            "One of " + " / ".join(TENANT_ASSIGNABLE_ROLES) + ". "
            "Platform roles cannot be assigned from inside a tenant."
        ),
    )
    farm_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Required, non-empty, for a farm-tier role. Must be empty for a " "tenant-tier role."
        ),
    )

    @model_validator(mode="after")
    def _check_role_and_farms(self) -> RoleAssignmentMixin:
        try:
            tier = assignment_tier(self.role)
        except RoleNotAssignableError as exc:
            raise ValueError(str(exc)) from exc
        if tier == "farm" and not self.farm_ids:
            raise ValueError(
                f"role {self.role!r} is granted per farm; farm_ids must name "
                f"at least one farm (farm-tier roles: {', '.join(FARM_TIER_ROLES)})"
            )
        if tier == "tenant" and self.farm_ids:
            raise ValueError(
                f"role {self.role!r} applies to every farm in the tenant; " "farm_ids must be empty"
            )
        if len(set(self.farm_ids)) != len(self.farm_ids):
            raise ValueError("farm_ids contains duplicates")
        return self

    @property
    def role_tier(self) -> str:
        """`tenant` | `farm`. Safe after validation."""
        return assignment_tier(self.role)


class UserInviteRequest(RoleAssignmentMixin):
    """POST /v1/users:invite — invite a new user to the current tenant."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    full_name_ar: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)


class RevokedRolesResponse(BaseModel):
    """What the change took away, echoed back so the caller can show it."""

    tenant_roles: list[str]
    farm_roles: list[FarmRoleGrantResponse]


class UserRoleAssignResponse(BaseModel):
    """PUT /v1/users/{user_id}/role."""

    membership_id: UUID
    role: str
    role_tier: Literal["tenant", "farm"]
    farm_ids: list[UUID]
    revoked: RevokedRolesResponse


class UserRoleAssignRequest(RoleAssignmentMixin):
    """PUT /v1/users/{user_id}/role — replace a member's role.

    A replacement, not an addition: whatever the member held before is
    revoked in the same transaction. Roles do not stack in this product —
    the resolver takes the first tier that grants a capability — so an
    additive endpoint would leave a member holding two roles with no screen
    able to show which one is in force.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


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
    full_name_ar: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=500)
    preferences: dict[str, Any] | None = None  # partial preferences patch


class WorkItemResponse(BaseModel):
    """One thing assigned to the signed-in person, whatever surface set it.

    Deliberately flat and shared across kinds. The phone renders one list, and
    a client that had to branch on `kind` before it could show a title would be
    doing the merge this endpoint exists to have already done.
    """

    kind: Literal["scouting_visit", "plan_activity"]
    id: UUID
    farm_id: UUID
    block_id: UUID | None = None
    title: str
    detail: str | None = None
    status: str
    # `origin` for a visit, `activity_type` for board work.
    category: str | None = None
    severity: str | None = None
    priority: str | None = None
    # ISO date or timestamp. A visit carries a deadline; board work carries the
    # day it is scheduled for.
    due_at: str | None = None
    # The signal template a visit was dispatched with, when the supervisor
    # named one. It is what turns "go and look" into "record these three
    # things". Null on board work, which carries no template.
    template_id: UUID | None = None
    # When this was closed, for both kinds. Null on anything still open.
    #
    # It arrives on the open feed too, always null there, rather than only on
    # the closed one. One response shape for one endpoint: a field that appears
    # and disappears with a query parameter is the kind of thing a typed client
    # marks optional and then reads as undefined for ever.
    completed_at: str | None = None
