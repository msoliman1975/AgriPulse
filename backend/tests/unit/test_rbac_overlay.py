"""The overlay merge — the function that decides every authorization answer.

A bug here silently grants or denies across every tenant at once, so the merge
is tested exhaustively before any endpoint touches it. The cases that matter
are the ones where the override and the baseline disagree, and the ones where
the override must be ignored entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.rbac import overlay
from app.shared.rbac.check import (
    CapabilityRegistry,
    effective_capabilities_for,
    get_default_registry,
    has_capability,
)


def _registry(snapshot: Mapping[str, Mapping[str, bool]]) -> CapabilityRegistry:
    """The real YAML policy, with a literal overlay injected.

    Uses the shipped capability catalogue rather than a toy one so the tests
    exercise the same data production does.
    """
    base = get_default_registry()
    return CapabilityRegistry(
        capabilities=dict(base.capabilities()),
        role_capabilities=dict(base.roles()),
        role_descriptions={r: base.role_description(r) for r in base.roles()},
        overlay_provider=lambda: snapshot,
    )


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


# ---------- merge precedence ---------------------------------------------


def test_override_can_grant_what_the_baseline_withholds() -> None:
    # plan.manage is exactly one of the four grants that used to exist only on
    # the frontend and were removed in Phase 1. Re-granting it is the most
    # likely first real use of this feature.
    assert get_default_registry().role_grants("Agronomist", "plan.manage") is False
    registry = _registry({"Agronomist": {"plan.manage": True}})
    assert registry.role_grants("Agronomist", "plan.manage") is True
    assert registry.baseline_grants("Agronomist", "plan.manage") is False


def test_override_can_revoke_what_the_baseline_grants() -> None:
    assert get_default_registry().role_grants("Agronomist", "alert.read") is True
    registry = _registry({"Agronomist": {"alert.read": False}})
    assert registry.role_grants("Agronomist", "alert.read") is False
    assert registry.baseline_grants("Agronomist", "alert.read") is True


def test_untouched_capabilities_still_follow_the_baseline() -> None:
    registry = _registry({"Agronomist": {"plan.manage": True}})
    for cap in ("alert.read", "block.read", "index.read"):
        assert registry.role_grants("Agronomist", cap) is registry.baseline_grants(
            "Agronomist", cap
        )


def test_an_override_on_one_role_does_not_leak_to_another() -> None:
    registry = _registry({"Agronomist": {"alert.read": False}})
    assert registry.role_grants("Agronomist", "alert.read") is False
    assert registry.role_grants("Scout", "alert.read") is True


def test_empty_overlay_is_exactly_the_baseline() -> None:
    registry = _registry({})
    base = get_default_registry()
    for role in base.roles():
        for cap in base.capabilities():
            assert registry.role_grants(role, cap) == base.baseline_grants(role, cap)


# ---------- the guardrails ------------------------------------------------


@pytest.mark.parametrize(
    "capability",
    ["platform.manage_rbac", "platform.manage_tenants", "platform.read"],
)
def test_platform_admin_is_immune_to_overrides(capability: str) -> None:
    """The lock-out backstop: the wildcard is never consulted against a row.

    `platform.manage_tenants` is what the frontend's PlatformAdminGuard gates
    on and `platform.manage_rbac` is what would undo the change, so revoking
    either from PlatformAdmin is the one edit with no way back.
    """
    registry = _registry({"PlatformAdmin": {capability: False}})
    assert registry.role_grants("PlatformAdmin", capability) is True

    ctx = _ctx(platform=PlatformRole.PLATFORM_ADMIN)
    assert has_capability(ctx, capability, registry=registry) is True


def test_override_cannot_grant_to_an_unknown_role() -> None:
    registry = _registry({"SuperUser": {"tenant.delete": True}})
    assert registry.role_grants("SuperUser", "tenant.delete") is False


def test_override_cannot_grant_an_unknown_capability() -> None:
    """`known()` still gates: a typo must not become a live permission."""
    registry = _registry({"Scout": {"no.such.capability": True}})
    ctx = _ctx(scopes=(FarmScope(farm_id=uuid4(), role=FarmRole.SCOUT),))
    assert has_capability(ctx, "no.such.capability", registry=registry) is False


# ---------- resolution through the three tiers ----------------------------


def test_revoking_a_farm_role_still_leaves_the_tenant_grant() -> None:
    """First-match-wins is unchanged; an override only moves one tier's answer.

    This is the case that bit Phase 1's mirror fix: a user who also holds a
    tenant role keeps the capability through that tier.
    """
    farm = uuid4()
    registry = _registry({"Agronomist": {"alert.read": False}})
    ctx = _ctx(
        tenant=TenantRole.TENANT_OWNER,
        scopes=(FarmScope(farm_id=farm, role=FarmRole.AGRONOMIST),),
    )
    assert has_capability(ctx, "alert.read", farm_id=farm, registry=registry) is True

    scoped_only = _ctx(scopes=(FarmScope(farm_id=farm, role=FarmRole.AGRONOMIST),))
    assert has_capability(scoped_only, "alert.read", farm_id=farm, registry=registry) is False


def test_a_farm_grant_added_by_override_stays_farm_scoped() -> None:
    granted_farm, other_farm = uuid4(), uuid4()
    registry = _registry({"Scout": {"plan.manage": True}})
    ctx = _ctx(scopes=(FarmScope(farm_id=granted_farm, role=FarmRole.SCOUT),))
    assert has_capability(ctx, "plan.manage", farm_id=granted_farm, registry=registry) is True
    assert has_capability(ctx, "plan.manage", farm_id=other_farm, registry=registry) is False


# ---------- what /v1/me serves --------------------------------------------


def test_effective_capabilities_reflect_the_override() -> None:
    registry = _registry({"Agronomist": {"plan.manage": True, "alert.read": False}})
    ctx = _ctx(scopes=(FarmScope(farm_id=uuid4(), role=FarmRole.AGRONOMIST),))
    served = effective_capabilities_for(ctx, registry=registry)
    assert "plan.manage" in served["Agronomist"]
    assert "alert.read" not in served["Agronomist"]


def test_effective_capabilities_only_cover_the_callers_roles() -> None:
    """No reason to hand every signed-in user the whole policy."""
    ctx = _ctx(tenant=TenantRole.BILLING_ADMIN)
    served = effective_capabilities_for(ctx, registry=_registry({}))
    assert set(served) == {"BillingAdmin"}


def test_effective_capabilities_send_the_wildcard_unexpanded() -> None:
    ctx = _ctx(platform=PlatformRole.PLATFORM_ADMIN)
    served = effective_capabilities_for(ctx, registry=_registry({}))
    assert served["PlatformAdmin"] == ["*"]


# ---------- the write-path guard ------------------------------------------
#
# The other half of the immutability story. `validate_target` refuses the write
# and `overlay._load` drops the row; either alone would be one bug away from an
# unrecoverable platform.


def test_validate_target_refuses_platform_admin() -> None:
    from app.modules.platform_admins.rbac_service import validate_target

    with pytest.raises(APIError) as exc:
        validate_target("PlatformAdmin", "platform.manage_rbac", get_default_registry())
    assert exc.value.status_code == 422
    assert "PlatformAdmin" in str(exc.value.detail)


def test_validate_target_names_an_unknown_role() -> None:
    from app.modules.platform_admins.rbac_service import validate_target

    with pytest.raises(APIError) as exc:
        validate_target("Wizard", "alert.read", get_default_registry())
    assert exc.value.status_code == 422
    assert "Wizard" in str(exc.value.detail)


def test_validate_target_names_an_unknown_capability() -> None:
    from app.modules.platform_admins.rbac_service import validate_target

    with pytest.raises(APIError) as exc:
        validate_target("Scout", "alert.raed", get_default_registry())
    assert exc.value.status_code == 422
    assert "alert.raed" in str(exc.value.detail)


def test_validate_target_accepts_a_real_pair() -> None:
    from app.modules.platform_admins.rbac_service import validate_target

    validate_target("Agronomist", "plan.manage", get_default_registry())


def test_the_overlay_loader_drops_immutable_roles() -> None:
    """A row inserted straight into the database must still not take effect."""
    assert "PlatformAdmin" in overlay.IMMUTABLE_ROLES


# ---------- the module-level cache ----------------------------------------


def test_cache_starts_empty_so_the_baseline_applies() -> None:
    """Before the first load — and after a DB failure — the YAML governs."""
    overlay.clear_cache()
    assert overlay.current() == {}


def test_set_snapshot_for_test_round_trips() -> None:
    overlay.clear_cache()
    overlay.set_snapshot_for_test({"Scout": {"plan.manage": True}})
    assert overlay.current()["Scout"]["plan.manage"] is True
    overlay.clear_cache()
    assert overlay.current() == {}


def test_invalidate_marks_the_snapshot_stale_without_clearing_it() -> None:
    """The write path must not blank the policy while a reload is pending.

    If `invalidate()` emptied the snapshot, every request between the write and
    the next successful load would resolve against the bare baseline — a
    visible flap in authorization on an otherwise healthy system.
    """
    overlay.clear_cache()
    overlay.set_snapshot_for_test({"Scout": {"plan.manage": True}})
    overlay.invalidate()
    assert overlay.current()["Scout"]["plan.manage"] is True


@pytest.mark.asyncio
async def test_ensure_fresh_is_a_noop_while_the_snapshot_is_fresh() -> None:
    """The hot path must not touch the database on every request."""
    overlay.clear_cache()
    overlay.set_snapshot_for_test({"Scout": {"plan.manage": True}})
    # No DB is configured in unit tests, so a load attempt would surface as a
    # warning and an emptied snapshot. Reaching the assertion proves the TTL
    # short-circuit held.
    await overlay.ensure_fresh()
    assert overlay.current() == {"Scout": {"plan.manage": True}}
    overlay.clear_cache()
