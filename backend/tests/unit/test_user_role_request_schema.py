"""Validation of the role half of the invite and role-change payloads.

The pair `(role, farm_ids)` is the whole contract between the Team & roles
screen and the two role tables. Getting it wrong does not raise anywhere
downstream — a farm-tier role with no farms writes no role row at all, and a
tenant-tier role with farms would drop them silently — so it is checked as a
unit before any handler sees it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.iam.schemas import UserInviteRequest, UserRoleAssignRequest
from app.shared.rbac import FARM_TIER_ROLES, PLATFORM_TIER_ROLES, TENANT_TIER_ROLES

_INVITE_BASE = {"email": "someone@example.com", "full_name": "Someone"}


@pytest.mark.parametrize("role", TENANT_TIER_ROLES)
def test_tenant_tier_role_needs_no_farms(role: str) -> None:
    payload = UserInviteRequest(**_INVITE_BASE, role=role)
    assert payload.role == role
    assert payload.farm_ids == []
    assert payload.role_tier == "tenant"


@pytest.mark.parametrize("role", TENANT_TIER_ROLES)
def test_tenant_tier_role_with_farms_is_refused(role: str) -> None:
    """Refused, not ignored: dropping the farms would read as a restriction."""
    with pytest.raises(ValidationError, match="every farm in the tenant"):
        UserInviteRequest(**_INVITE_BASE, role=role, farm_ids=[uuid4()])


@pytest.mark.parametrize("role", FARM_TIER_ROLES)
def test_farm_tier_role_requires_at_least_one_farm(role: str) -> None:
    with pytest.raises(ValidationError, match="granted per farm"):
        UserInviteRequest(**_INVITE_BASE, role=role)

    payload = UserInviteRequest(**_INVITE_BASE, role=role, farm_ids=[uuid4()])
    assert payload.role_tier == "farm"


@pytest.mark.parametrize("role", PLATFORM_TIER_ROLES)
def test_platform_roles_are_refused(role: str) -> None:
    """The point of the whole allow-list: no platform role inside a tenant."""
    with pytest.raises(ValidationError, match="cannot be assigned by a tenant"):
        UserInviteRequest(**_INVITE_BASE, role=role)
    with pytest.raises(ValidationError, match="cannot be assigned by a tenant"):
        UserRoleAssignRequest(role=role)


def test_unknown_role_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be assigned by a tenant"):
        UserInviteRequest(**_INVITE_BASE, role="Sysadmin")


def test_duplicate_farm_ids_are_refused() -> None:
    """A repeat would hit the farm_scopes unique index as a 500."""
    farm_id = uuid4()
    with pytest.raises(ValidationError, match="duplicates"):
        UserInviteRequest(**_INVITE_BASE, role="Scout", farm_ids=[farm_id, farm_id])


def test_tenant_role_is_still_accepted_as_an_alias() -> None:
    """The field was `tenant_role` while only tenant roles could be assigned.

    Kept as an alias so an in-flight frontend build keeps working across the
    deploy, rather than every invite failing validation for the minutes the
    two versions overlap.
    """
    payload = UserInviteRequest(**_INVITE_BASE, tenant_role="TenantAdmin")
    assert payload.role == "TenantAdmin"


def test_role_change_defaults_are_not_silently_valid() -> None:
    """The default role is farm-tier, so an empty body cannot be a change.

    A payload with nothing in it must not resolve to "grant Viewer on no
    farms" — which is a member with no role and no error.
    """
    with pytest.raises(ValidationError, match="granted per farm"):
        UserRoleAssignRequest()
