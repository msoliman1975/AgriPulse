"""Capability-based RBAC. See ARCHITECTURE.md § 7."""

from app.shared.rbac.check import (
    CapabilityRegistry,
    PermissionDeniedError,
    get_default_registry,
    has_capability,
    requires_capability,
)

__all__ = [
    "CapabilityRegistry",
    "PermissionDeniedError",
    "get_default_registry",
    "has_capability",
    "requires_capability",
]
