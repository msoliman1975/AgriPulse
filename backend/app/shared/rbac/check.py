"""Capability-based RBAC: load YAML, resolve, and enforce.

Two YAML files in this package describe the policy:

  - capabilities.yaml      â€” every capability string the platform recognizes
  - role_capabilities.yaml â€” which capabilities each role grants

Code never checks roles directly. It either asks
`has_capability(context, "alert.acknowledge", farm_id=...)` or attaches
`Depends(requires_capability("alert.acknowledge", farm_id_param="farm_id"))`
to a FastAPI route.

Resolution order on every request, per ARCHITECTURE.md Â§ 7:

  1. PlatformRole â€” if it grants the capability, allow.
  2. TenantRole   â€” if it grants the capability, allow.
  3. FarmScope    â€” if a scope on the matching farm_id grants it, allow.

First match wins; otherwise PermissionDeniedError (HTTP 403).

At each step the answer is the YAML baseline *merged with* any runtime
override a Platform Admin has applied — see `overlay.py`. The merge is two
dict lookups against a cached snapshot, so every caller here stays
synchronous. `PlatformAdmin`'s wildcard is never overridable.
"""

# NOTE: deliberately NO `from __future__ import annotations`. The
# inner `_check` dependency below uses `request: Request`, and FastAPI
# can't resolve string annotations to the FastAPI Request injection â€”
# it would silently demote the parameter to a query param and break
# every route that depends on this factory.

from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

import yaml
from fastapi import Depends, Request, status

from app.core.errors import APIError
from app.shared.auth.context import (
    FarmRole,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.auth.middleware import get_current_context
from app.shared.rbac import overlay

WILDCARD = "*"

# Role -> the JWT layer that can grant it. Derived from the three StrEnums in
# auth.context rather than restated, so a role added there cannot silently miss
# a tier here. `Viewer` is a FarmRole, but public migration 0036 also lets it
# sit in tenant_role_assignments — see role_tier's docstring.
_ROLE_TIERS: dict[str, str] = {
    **{r.value: "platform" for r in PlatformRole},
    **{r.value: "tenant" for r in TenantRole},
    **{r.value: "farm" for r in FarmRole},
}


class UnknownRoleError(ValueError):
    """A role name that is in neither the YAML nor the enums."""


def role_tier(role: str) -> str:
    """`platform` | `tenant` | `farm` for a role name.

    Raises `UnknownRoleError` rather than defaulting, so a divergence between
    role_capabilities.yaml and the enums fails loudly at the one place that
    enumerates roles instead of quietly mislabelling a row in the admin UI.

    Note this is the tier a role is *defined* at, not every tier it can be
    assigned at: `Viewer` is a FarmRole here, yet public migration 0036 permits
    it in `tenant_role_assignments` too.
    """
    try:
        return _ROLE_TIERS[role]
    except KeyError:
        raise UnknownRoleError(f"unknown role: {role!r}") from None


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
            type_="https://agripulse.cloud/problems/permission-denied",
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
        role_descriptions: dict[str, str] | None = None,
        overlay_provider: "Callable[[], Mapping[str, Mapping[str, bool]]] | None" = None,
    ) -> None:
        self._capabilities = capabilities
        self._role_capabilities = role_capabilities
        self._role_descriptions = role_descriptions or {}
        # Injectable so the merge can be unit-tested against a literal dict
        # without touching module state. Production lets it default to the
        # process-wide cache the auth middleware keeps fresh.
        self._overlay_provider = overlay_provider or overlay.current

    @classmethod
    def from_files(
        cls, capabilities_path: Path, role_capabilities_path: Path
    ) -> "CapabilityRegistry":
        return cls.from_yaml(
            capabilities_path.read_text(encoding="utf-8"),
            role_capabilities_path.read_text(encoding="utf-8"),
        )

    @classmethod
    def from_yaml(cls, capabilities_yaml: str, role_capabilities_yaml: str) -> "CapabilityRegistry":
        caps_doc = yaml.safe_load(capabilities_yaml) or {}
        roles_doc = yaml.safe_load(role_capabilities_yaml) or {}

        capabilities = caps_doc.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            raise ValueError("capabilities.yaml: 'capabilities' must be a mapping")

        role_caps_raw = roles_doc.get("roles") or {}
        if not isinstance(role_caps_raw, dict):
            raise ValueError("role_capabilities.yaml: 'roles' must be a mapping")

        compiled: dict[str, frozenset[str]] = {}
        descriptions: dict[str, str] = {}
        for role_name, body in role_caps_raw.items():
            if not isinstance(body, dict):
                raise ValueError(f"role_capabilities.yaml: '{role_name}' must be a mapping")
            descriptions[role_name] = str(body.get("description") or "").strip()
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

        return cls(
            capabilities=capabilities,
            role_capabilities=compiled,
            role_descriptions=descriptions,
        )

    def known(self, capability: str) -> bool:
        return capability in self._capabilities

    def capabilities(self) -> Mapping[str, Mapping[str, Any]]:
        """The capability catalogue: name -> {description, scope, status}.

        Read-only view for the RBAC admin surface. Enforcement never reads
        this — `role_grants` is the only authorization path.
        """
        return MappingProxyType(self._capabilities)

    def roles(self) -> Mapping[str, frozenset[str]]:
        """Compiled role -> granted capability names.

        PlatformAdmin's set is the literal `{"*"}`; callers that need the
        expanded list should substitute `capabilities()` themselves.
        """
        return MappingProxyType(self._role_capabilities)

    def role_description(self, role: str) -> str:
        return self._role_descriptions.get(role, "")

    def effective_capabilities(self, role: str) -> list[str]:
        """Every capability `role` grants right now, overrides included.

        Returns the literal `["*"]` for a wildcard role rather than the
        expanded catalogue, so the frontend's existing `roleGrants` shortcut
        keeps working and the payload stays small.
        """
        baseline = self._role_capabilities.get(role)
        if baseline is None:
            return []
        if WILDCARD in baseline:
            return [WILDCARD]
        return sorted(c for c in self._capabilities if self.role_grants(role, c))

    def baseline_grants(self, role: str, capability: str) -> bool:
        """What `role_capabilities.yaml` alone says, ignoring any override.

        The admin surface shows this beside the effective answer so a row can
        be marked "modified from default" and offered a Reset.
        """
        granted = self._role_capabilities.get(role)
        if granted is None:
            return False
        if WILDCARD in granted:
            return True
        return capability in granted

    def role_grants(self, role: str, capability: str) -> bool:
        """The effective answer: runtime override first, then the baseline.

        Synchronous and memory-only by design — see `rbac/overlay.py`. Two
        dict lookups on the authorization hot path; never builds a merged set.
        """
        granted = self._role_capabilities.get(role)
        if granted is None:
            # An unknown role denies, and no override can rescue it. Preserves
            # the pre-overlay contract that only the YAML names real roles.
            return False
        if WILDCARD in granted:
            # PlatformAdmin. The overlay is never consulted, so no row — and no
            # bug in the merge — can strip the platform's last way back in.
            return True
        role_overrides = self._overlay_provider().get(role)
        if role_overrides is not None:
            decided = role_overrides.get(capability)
            if decided is not None:
                return decided
        return capability in granted

    def has_capability(
        self,
        context: RequestContext,
        capability: str,
        *,
        farm_id: UUID | None = None,
    ) -> bool:
        """Resolve PlatformRole -> TenantRole -> FarmScope; first match wins.

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
def get_default_registry() -> "CapabilityRegistry":
    """Singleton registry loaded from the bundled YAML files."""
    return CapabilityRegistry.from_files(_CAPABILITIES_FILE, _ROLE_CAPABILITIES_FILE)


def has_capability(
    context: RequestContext,
    capability: str,
    *,
    farm_id: UUID | None = None,
    registry: "CapabilityRegistry | None" = None,
) -> bool:
    """Module-level convenience over the default registry.

    Pass an explicit `registry` from tests; production code lets it default.
    """
    return (registry or get_default_registry()).has_capability(context, capability, farm_id=farm_id)


def effective_capabilities_for(
    context: RequestContext,
    *,
    registry: "CapabilityRegistry | None" = None,
) -> dict[str, list[str]]:
    """Effective grants per role, for the roles *this* context actually holds.

    Served on `GET /v1/me` so the frontend stops resolving capabilities from a
    compiled-in copy of the matrix. Once the matrix is editable at runtime, a
    bundled constant is wrong by construction: an admin toggles a permission
    and every browser keeps showing the old affordances until the next deploy.

    Keyed by role rather than flattened to one list on purpose — the frontend
    resolves platform -> tenant -> farm, and a farm-scoped grant only applies on
    the farms that scope covers. Flattening would silently widen it to every
    farm. Only the caller's own roles are included; there is no reason to hand
    every user the whole policy.
    """
    registry = registry or get_default_registry()
    roles: set[str] = set()
    if context.platform_role is not None:
        roles.add(context.platform_role.value)
    if context.tenant_role is not None:
        roles.add(context.tenant_role.value)
    for scope in context.farm_scopes:
        roles.add(scope.role.value)
    return {role: registry.effective_capabilities(role) for role in sorted(roles)}


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
