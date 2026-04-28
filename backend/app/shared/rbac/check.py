"""Capability-based RBAC: load YAML, resolve, and enforce.

Two YAML files in this package describe the policy:

  - capabilities.yaml      — every capability string the platform recognizes
  - role_capabilities.yaml — which capabilities each role grants

Code never checks roles directly. It either asks
`has_capability(context, "alert.acknowledge", farm_id=...)` or attaches
`Depends(requires_capability("alert.acknowledge", farm_id_param="farm_id"))`
to a FastAPI route.

Resolution order on every request, per ARCHITECTURE.md § 7:

  1. PlatformRole — if it grants the capability, allow.
  2. TenantRole   — if it grants the capability, allow.
  3. FarmScope    — if a scope on the matching farm_id grants it, allow.

First match wins; otherwise PermissionDeniedError (HTTP 403).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi import Depends, Request, status

from app.core.errors import APIError
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context

WILDCARD = "*"

_RBAC_DIR = Path(__file__).resolve().parent
_CAPABILITIES_FILE = _RBAC_DIR / "capabilities.yaml"
_ROLE_CAPABILITIES_FILE = _RBAC_DIR / "role_capabilities.yaml"


class PermissionDeniedError(APIError):
    """403 Forbidden surfaced as RFC 7807 problem+json."""

    def __init__(self, capability: str, farm_id: UUID | None = None) -> None:
        extras: dict[str, Any] = {"capability": capability}
        if farm_id is not None:
            extras["farm_id"] = str(farm_id)
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail=f"Missing capability: {capability}",
            type_="https://missionagre.io/problems/permission-denied",
            extras=extras,
        )


class CapabilityRegistry:
    """Compiled RBAC tables: capability set per role.

    Built once via `get_default_registry()` and reused. Tests construct
    one from inline YAML via `from_yaml()`.
    """

    def __init__(
        self,
        *,
        capabilities: dict[str, dict[str, Any]],
        role_capabilities: dict[str, frozenset[str]],
    ) -> None:
        self._capabilities = capabilities
        self._role_capabilities = role_capabilities

    @classmethod
    def from_files(
        cls, capabilities_path: Path, role_capabilities_path: Path
    ) -> CapabilityRegistry:
        return cls.from_yaml(
            capabilities_path.read_text(encoding="utf-8"),
            role_capabilities_path.read_text(encoding="utf-8"),
        )

    @classmethod
    def from_yaml(cls, capabilities_yaml: str, role_capabilities_yaml: str) -> CapabilityRegistry:
        caps_doc = yaml.safe_load(capabilities_yaml) or {}
        roles_doc = yaml.safe_load(role_capabilities_yaml) or {}

        capabilities = caps_doc.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            raise ValueError("capabilities.yaml: 'capabilities' must be a mapping")

        role_caps_raw = roles_doc.get("roles") or {}
        if not isinstance(role_caps_raw, dict):
            raise ValueError("role_capabilities.yaml: 'roles' must be a mapping")

        compiled: dict[str, frozenset[str]] = {}
        for role_name, body in role_caps_raw.items():
            if not isinstance(body, dict):
                raise ValueError(f"role_capabilities.yaml: '{role_name}' must be a mapping")
            caps = body.get("capabilities") or []
            if not isinstance(caps, list):
                raise ValueError(
                    f"role_capabilities.yaml: '{role_name}.capabilities' must be a list"
                )
            for cap in caps:
                if cap == WILDCARD:
                    continue
                if cap not in capabilities:
                    raise ValueError(
                        f"role_capabilities.yaml: '{role_name}' references "
                        f"unknown capability '{cap}'"
                    )
            compiled[role_name] = frozenset(caps)

        return cls(capabilities=capabilities, role_capabilities=compiled)

    def known(self, capability: str) -> bool:
        return capability in self._capabilities

    def role_grants(self, role: str, capability: str) -> bool:
        granted = self._role_capabilities.get(role)
        if granted is None:
            return False
        if WILDCARD in granted:
            return True
        return capability in granted

    def has_capability(
        self,
        context: RequestContext,
        capability: str,
        *,
        farm_id: UUID | None = None,
    ) -> bool:
        """Resolve PlatformRole → TenantRole → FarmScope; first match wins.

        Unknown capabilities deny: a typo must never silently grant.
        """
        if not self.known(capability):
            return False

        if context.platform_role is not None and self.role_grants(
            context.platform_role.value, capability
        ):
            return True

        if context.tenant_role is not None and self.role_grants(
            context.tenant_role.value, capability
        ):
            return True

        if farm_id is not None:
            scope_role = context.role_on_farm(farm_id)
            if scope_role is not None and self.role_grants(scope_role.value, capability):
                return True

        return False


@lru_cache(maxsize=1)
def get_default_registry() -> CapabilityRegistry:
    """Singleton registry loaded from the bundled YAML files."""
    return CapabilityRegistry.from_files(_CAPABILITIES_FILE, _ROLE_CAPABILITIES_FILE)


def has_capability(
    context: RequestContext,
    capability: str,
    *,
    farm_id: UUID | None = None,
    registry: CapabilityRegistry | None = None,
) -> bool:
    """Module-level convenience over the default registry.

    Pass an explicit `registry` from tests; production code lets it default.
    """
    return (registry or get_default_registry()).has_capability(context, capability, farm_id=farm_id)


def requires_capability(
    capability: str,
    *,
    farm_id_param: str | None = None,
) -> Callable[..., RequestContext]:
    """FastAPI dependency factory.

    Usage:

        @router.post("/farms/{farm_id}/alerts/{alert_id}/ack")
        async def acknowledge(
            ctx: RequestContext = Depends(
                requires_capability("alert.acknowledge", farm_id_param="farm_id")
            ),
        ): ...

    `farm_id_param` is the path or query parameter to read the farm UUID
    from. Omit it for tenant- or platform-scoped capabilities. The
    dependency returns the RequestContext on success, so a single
    `Depends(...)` covers both auth and authorization for the route.
    """

    def _check(
        request: Request,
        context: RequestContext = Depends(get_current_context),
    ) -> RequestContext:
        farm_id: UUID | None = None
        if farm_id_param is not None:
            raw = request.path_params.get(farm_id_param) or request.query_params.get(farm_id_param)
            if raw is not None:
                try:
                    farm_id = UUID(str(raw))
                except ValueError as exc:
                    raise PermissionDeniedError(capability) from exc
        registry = get_default_registry()
        if not registry.has_capability(context, capability, farm_id=farm_id):
            raise PermissionDeniedError(capability, farm_id=farm_id)
        return context

    return _check
