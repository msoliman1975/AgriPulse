"""Capability-based RBAC. See ARCHITECTURE.md § 7."""

from app.shared.rbac.check import (
    FARM_TIER_ROLES,
    PLATFORM_TIER_ROLES,
    TENANT_ASSIGNABLE_ROLES,
    TENANT_TIER_ROLES,
    CapabilityRegistry,
    PermissionDeniedError,
    RoleNotAssignableError,
    assignment_tier,
    get_default_registry,
    has_capability,
    requires_capability,
    role_tier,
)

__all__ = [
    "FARM_TIER_ROLES",
    "PLATFORM_TIER_ROLES",
    "TENANT_ASSIGNABLE_ROLES",
    "TENANT_TIER_ROLES",
    "CapabilityRegistry",
    "PermissionDeniedError",
    "RoleNotAssignableError",
    "assignment_tier",
    "get_default_registry",
    "has_capability",
    "requires_capability",
    "role_tier",
]
