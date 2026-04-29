"""RequestContext: typed view of the validated JWT claims for one request.

Mirrors the JWT shape in ARCHITECTURE.md § 7.3. The auth middleware
constructs a RequestContext after JWKS validation and attaches it to
request.state.context. Routes never read request.state directly —
they depend on `get_current_context` from app.shared.auth.middleware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import UUID


class PlatformRole(StrEnum):
    """Cross-tenant roles for platform staff (data_model § 4.7)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    PLATFORM_SUPPORT = "PlatformSupport"


class TenantRole(StrEnum):
    """Tenant-wide roles (data_model § 4.5).

    A tenant role grants access to every farm in the tenant.
    """

    TENANT_OWNER = "TenantOwner"
    TENANT_ADMIN = "TenantAdmin"
    BILLING_ADMIN = "BillingAdmin"


class FarmRole(StrEnum):
    """Per-farm roles (data_model § 4.6)."""

    FARM_MANAGER = "FarmManager"
    AGRONOMIST = "Agronomist"
    FIELD_OPERATOR = "FieldOperator"
    SCOUT = "Scout"
    VIEWER = "Viewer"


@dataclass(frozen=True, slots=True)
class FarmScope:
    """A user's role on a specific farm.

    farm_scopes are embedded directly in the JWT for MVP (revocation
    latency = token TTL = 15 min). A future P2 upgrade will fetch from
    Redis instead.
    """

    farm_id: UUID
    role: FarmRole


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Validated identity attached to request.state by the auth middleware.

    Frozen because middleware contracts depend on it not mutating
    mid-request.
    """

    user_id: UUID
    keycloak_subject: str
    tenant_id: UUID | None = None
    tenant_role: TenantRole | None = None
    platform_role: PlatformRole | None = None
    farm_scopes: tuple[FarmScope, ...] = field(default_factory=tuple)
    preferred_language: Literal["en", "ar"] = "en"
    preferred_unit: Literal["feddan", "acre", "hectare"] = "feddan"

    @property
    def tenant_schema(self) -> str | None:
        """The PostgreSQL schema for this user's tenant.

        Naming convention from data_model § 1.1 + § 3.2: `tenant_<uuid>`
        with hyphens replaced by underscores so the identifier is valid
        without quoting.
        """
        if self.tenant_id is None:
            return None
        return f"tenant_{self.tenant_id.hex}"

    def has_platform_role(self, role: PlatformRole) -> bool:
        return self.platform_role == role

    def has_tenant_role(self, role: TenantRole) -> bool:
        return self.tenant_role == role

    def role_on_farm(self, farm_id: UUID) -> FarmRole | None:
        """Return the user's farm-scope role on `farm_id`, or None."""
        for scope in self.farm_scopes:
            if scope.farm_id == farm_id:
                return scope.role
        return None
