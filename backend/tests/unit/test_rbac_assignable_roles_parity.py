"""The frontend's assignable-role lists must equal the backend's.

`frontend/src/rbac/assignableRoles.ts` restates which roles a tenant
administrator may grant and which tier each belongs to, because the invite
form has to render its dropdown before any request completes.

This is the drift that made the lists disagree in the first place. The
Team & roles dropdown was a literal four-element array in
`UsersConfigPage.tsx` while the Roles & permissions page read ten roles from
the RBAC matrix endpoint, and nothing anywhere compared the two. Drift is
silent in both directions:

  * a role missing from the frontend list can never be granted, and no error
    is raised — the option simply is not there;
  * a role present only on the frontend renders an option whose request the
    server rejects with a 422 the moment anyone picks it.

The tier split matters as much as membership: a farm-tier role sent without
farm ids is refused, and a tenant-tier role sent with them is refused too, so
a role on the wrong side of the split is an option that always fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.shared.rbac import (
    FARM_TIER_ROLES,
    PLATFORM_TIER_ROLES,
    TENANT_ASSIGNABLE_ROLES,
    TENANT_TIER_ROLES,
    RoleNotAssignableError,
    assignment_tier,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIRROR = _REPO_ROOT / "frontend" / "src" / "rbac" / "assignableRoles.ts"

pytestmark = pytest.mark.skipif(
    not _MIRROR.exists(),
    reason="frontend/ is absent (backend-only checkout or Docker build context)",
)


def _mirror_list(name: str) -> list[str]:
    """The string literals of one exported array in the mirror.

    Only the literal `export const NAME: ... = [ "A", "B" ];` form is read.
    Building the list from a helper would make its real contents invisible to
    this check, which is the failure mode the whole test exists to prevent.
    """
    source = _MIRROR.read_text(encoding="utf-8")
    match = re.search(
        r"export const " + re.escape(name) + r"\s*:[^=]*=\s*\[(.*?)\];",
        source,
        re.DOTALL,
    )
    assert match is not None, f"{name} not found as a literal array in {_MIRROR.name}"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_tenant_tier_roles_match() -> None:
    assert _mirror_list("TENANT_TIER_ROLES") == list(TENANT_TIER_ROLES)


def test_farm_tier_roles_match() -> None:
    assert _mirror_list("FARM_TIER_ROLES") == list(FARM_TIER_ROLES)


def test_every_assignable_role_is_offered() -> None:
    """Order included: the picker shows the list in authority order."""
    offered = _mirror_list("TENANT_TIER_ROLES") + _mirror_list("FARM_TIER_ROLES")
    assert offered == list(TENANT_ASSIGNABLE_ROLES)


@pytest.mark.parametrize("role", PLATFORM_TIER_ROLES)
def test_platform_roles_are_not_offered_to_tenants(role: str) -> None:
    """PlatformAdmin and PlatformSupport must not reach a tenant picker."""
    assert role not in _mirror_list("TENANT_TIER_ROLES")
    assert role not in _mirror_list("FARM_TIER_ROLES")
    assert role not in TENANT_ASSIGNABLE_ROLES
    with pytest.raises(RoleNotAssignableError):
        assignment_tier(role)


@pytest.mark.parametrize("role", TENANT_ASSIGNABLE_ROLES)
def test_every_offered_role_has_a_label_and_a_hint(role: str) -> None:
    """A role with no label renders as a raw key like `roles.Agronomist`."""
    import json

    for locale in ("en", "ar"):
        path = _REPO_ROOT / "frontend" / "src" / "i18n" / "locales" / locale / "users.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert role in data["roles"], f"{locale}: no roles.{role} label"
        assert role in data["roleHints"], f"{locale}: no roleHints.{role} hint"


@pytest.mark.parametrize("role", TENANT_ASSIGNABLE_ROLES)
def test_every_assignable_role_grants_something(role: str) -> None:
    """A role that grants nothing is an option that produces a dead account.

    This is what a tenant-wide `Viewer` used to be: accepted by the CHECK
    constraint, written to `tenant_role_assignments`, and then dropped by the
    JWT parser because `Viewer` is not a member of the tenant-role enum.
    """
    from app.shared.rbac import get_default_registry

    granted = get_default_registry().roles().get(role)
    assert granted, f"{role} grants no capabilities"
