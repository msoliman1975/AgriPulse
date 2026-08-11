"""Unit tests for the RBAC capability resolver."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.rbac.check import (
    CapabilityRegistry,
    PermissionDeniedError,
    UnknownRoleError,
    get_default_registry,
    has_capability,
    role_tier,
)


@pytest.fixture
def registry() -> CapabilityRegistry:
    return get_default_registry()


def _ctx(
    *,
    platform: PlatformRole | None = None,
    tenant: TenantRole | None = None,
    scopes: tuple[FarmScope, ...] = (),
) -> RequestContext:
    return RequestContext(
        user_id=uuid4(),
        keycloak_subject="kc",
        tenant_id=uuid4(),
        platform_role=platform,
        tenant_role=tenant,
        farm_scopes=scopes,
    )


def test_unknown_capability_denies_even_for_admin(registry: CapabilityRegistry) -> None:
    ctx = _ctx(platform=PlatformRole.PLATFORM_ADMIN)
    assert has_capability(ctx, "no.such.capability", registry=registry) is False


def test_platform_admin_wildcard_grants_anything(registry: CapabilityRegistry) -> None:
    ctx = _ctx(platform=PlatformRole.PLATFORM_ADMIN)
    assert has_capability(ctx, "alert.acknowledge", farm_id=uuid4(), registry=registry) is True
    assert has_capability(ctx, "tenant.update", registry=registry) is True
    assert has_capability(ctx, "audit.read", registry=registry) is True


def test_platform_support_is_read_only(registry: CapabilityRegistry) -> None:
    ctx = _ctx(platform=PlatformRole.PLATFORM_SUPPORT)
    assert has_capability(ctx, "tenant.read", registry=registry) is True
    assert has_capability(ctx, "tenant.update", registry=registry) is False


def test_tenant_admin_grants_user_invite(registry: CapabilityRegistry) -> None:
    ctx = _ctx(tenant=TenantRole.TENANT_ADMIN)
    assert has_capability(ctx, "user.invite", registry=registry) is True
    assert has_capability(ctx, "subscription.manage", registry=registry) is False


def test_billing_admin_only_billing(registry: CapabilityRegistry) -> None:
    ctx = _ctx(tenant=TenantRole.BILLING_ADMIN)
    assert has_capability(ctx, "subscription.manage", registry=registry) is True
    assert has_capability(ctx, "user.invite", registry=registry) is False


def test_farm_scope_restricted_to_own_farm(registry: CapabilityRegistry) -> None:
    farm = uuid4()
    other = uuid4()
    ctx = _ctx(scopes=(FarmScope(farm_id=farm, role=FarmRole.SCOUT),))
    assert has_capability(ctx, "scouting.record", farm_id=farm, registry=registry) is True
    assert has_capability(ctx, "scouting.record", farm_id=other, registry=registry) is False


def test_resolution_order_platform_then_tenant_then_farm(
    registry: CapabilityRegistry,
) -> None:
    farm = uuid4()
    # A user with both TenantAdmin and FarmManager — TenantAdmin grants
    # alert.read tenant-wide so the answer should be True without needing
    # a farm match.
    ctx = _ctx(
        tenant=TenantRole.TENANT_ADMIN,
        scopes=(FarmScope(farm_id=farm, role=FarmRole.VIEWER),),
    )
    assert has_capability(ctx, "alert_rule.manage", registry=registry) is True
    # Capability not granted by TenantAdmin is granted only via FarmScope.
    # Viewer has farm.read; check it works on the matching farm.
    assert has_capability(ctx, "farm.read", farm_id=farm, registry=registry) is True


def test_unknown_role_in_yaml_validates_at_load() -> None:
    bad_caps = "capabilities:\n  x.read: {description: x, scope: tenant, status: stub}\n"
    bad_roles = "roles:\n  Bogus:\n    capabilities:\n      - not_in_caps\n"
    with pytest.raises(ValueError, match="unknown capability"):
        CapabilityRegistry.from_yaml(bad_caps, bad_roles)


def test_permission_denied_carries_capability() -> None:
    err = PermissionDeniedError("alert.acknowledge", farm_id=uuid4())
    assert err.status_code == 403
    assert err.title == "Forbidden"
    assert err.extras["capability"] == "alert.acknowledge"
    assert "farm_id" in err.extras


# --- Read-only accessors backing the RBAC admin matrix -------------------


def test_capabilities_accessor_exposes_metadata(registry: CapabilityRegistry) -> None:
    caps = registry.capabilities()
    assert len(caps) > 50
    entry = caps["farm.read"]
    assert entry["scope"] == "farm"
    assert entry["status"] in {"active", "stub"}
    assert entry["description"]


def test_accessors_return_immutable_views(registry: CapabilityRegistry) -> None:
    # The registry is a process-wide singleton on the authorization path;
    # handing out a mutable dict would let one caller edit everyone's policy.
    with pytest.raises(TypeError):
        registry.capabilities()["x.read"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        registry.roles()["Bogus"] = frozenset()  # type: ignore[index]


def test_roles_accessor_keeps_wildcard_unexpanded(registry: CapabilityRegistry) -> None:
    # Expansion is a presentation concern; the registry stays literal so
    # role_grants can keep short-circuiting on WILDCARD.
    assert registry.roles()["PlatformAdmin"] == frozenset({"*"})


def test_role_description_reads_from_yaml(registry: CapabilityRegistry) -> None:
    assert "cross-tenant" in registry.role_description("PlatformAdmin")
    assert registry.role_description("NoSuchRole") == ""


def test_every_yaml_role_has_a_tier() -> None:
    # Binds role_capabilities.yaml to the three StrEnums in auth.context.
    # If someone adds a role to one and not the other, this is where it fails.
    for role in get_default_registry().roles():
        assert role_tier(role) in {"platform", "tenant", "farm"}


def test_role_tier_matches_the_defining_enum() -> None:
    assert role_tier(PlatformRole.PLATFORM_SUPPORT.value) == "platform"
    assert role_tier(TenantRole.BILLING_ADMIN.value) == "tenant"
    # Viewer is defined as a farm role even though public migration 0036 also
    # permits it in tenant_role_assignments.
    assert role_tier(FarmRole.VIEWER.value) == "farm"


def test_role_tier_raises_on_unknown_role() -> None:
    with pytest.raises(UnknownRoleError):
        role_tier("Sysadmin")
