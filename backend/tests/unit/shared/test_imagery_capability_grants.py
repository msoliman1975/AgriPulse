"""Verify the imagery / index RBAC matrix matches the PR-A plan.

The ground rules from the prompt's gate criteria:

  * Viewer cannot trigger refresh; can read scenes and the trend.
  * Agronomist cannot manage subscriptions; can read scenes and the trend
    and can trigger refresh.
  * FarmManager / TenantAdmin / TenantOwner manage subscriptions.
  * imagery.subscription.manage is a new capability added in PR-A.

This test reads the *real* YAML files via the default registry so
typos / missing entries are caught.
"""

from __future__ import annotations

import pytest

from app.shared.rbac.check import get_default_registry


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return get_default_registry()


# --- Capability presence ---------------------------------------------------


@pytest.mark.parametrize(
    "capability",
    [
        "imagery.read",
        "imagery.refresh",
        "imagery.subscription.manage",
        "index.read",
        "index.compute_custom",
    ],
)
def test_imagery_capability_is_known(registry, capability: str) -> None:  # type: ignore[no-untyped-def]
    assert registry.known(capability), f"capabilities.yaml missing {capability}"


# --- Roles that MUST grant `imagery.subscription.manage` -------------------


@pytest.mark.parametrize("role", ["TenantOwner", "TenantAdmin", "FarmManager"])
def test_role_grants_subscription_manage(registry, role: str) -> None:  # type: ignore[no-untyped-def]
    assert registry.role_grants(
        role, "imagery.subscription.manage"
    ), f"{role} should grant imagery.subscription.manage"


# --- Roles that MUST NOT grant `imagery.subscription.manage` ---------------


@pytest.mark.parametrize(
    "role",
    [
        "Agronomist",
        "FieldOperator",
        "Scout",
        "Viewer",
        "BillingAdmin",
        "PlatformSupport",
    ],
)
def test_role_does_not_grant_subscription_manage(registry, role: str) -> None:  # type: ignore[no-untyped-def]
    assert not registry.role_grants(
        role, "imagery.subscription.manage"
    ), f"{role} must not grant imagery.subscription.manage"


# --- Refresh: gate criterion 14 -------------------------------------------


@pytest.mark.parametrize(
    "role",
    [
        "TenantOwner",
        "TenantAdmin",
        "FarmManager",
        "Agronomist",
    ],
)
def test_role_grants_imagery_refresh(registry, role: str) -> None:  # type: ignore[no-untyped-def]
    assert registry.role_grants(role, "imagery.refresh")


def test_viewer_cannot_refresh(registry) -> None:  # type: ignore[no-untyped-def]
    assert not registry.role_grants("Viewer", "imagery.refresh")


# --- imagery.read is universally available to assigned roles --------------


@pytest.mark.parametrize(
    "role",
    [
        "TenantOwner",
        "TenantAdmin",
        "FarmManager",
        "Agronomist",
        "FieldOperator",
        "Scout",
        "Viewer",
        "PlatformSupport",
    ],
)
def test_assigned_role_can_read_imagery(registry, role: str) -> None:  # type: ignore[no-untyped-def]
    assert registry.role_grants(role, "imagery.read")
    assert registry.role_grants(role, "index.read")


# --- BillingAdmin shouldn't be in the imagery world at all -----------------


def test_billing_admin_cannot_read_imagery(registry) -> None:  # type: ignore[no-untyped-def]
    assert not registry.role_grants("BillingAdmin", "imagery.read")
    assert not registry.role_grants("BillingAdmin", "imagery.refresh")
    assert not registry.role_grants("BillingAdmin", "imagery.subscription.manage")
