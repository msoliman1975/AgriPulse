"""The tree-explain endpoint must be reachable by the people it was built for.

`GET /blocks/{id}/decision-trees:explain` backs the Farm Console's Conditions
tab. It was first written alongside its neighbours in the router, which are
gated on ``decision_tree.read`` — a capability only TenantOwner, TenantAdmin
and PlatformSupport hold. That made the tab 403 for every field role,
including the Agronomist, who is the whole audience for a "why did this tree
fire" screen.

It is gated on ``recommendation.read`` instead: the endpoint explains
recommendations, so anyone allowed to see one should be allowed to see why it
fired. Widening ``decision_tree.read`` is not an alternative — it also gates
``:evaluate`` and ``:dry-run``, both of which write.

These tests pin that down against the real YAML policy.
"""

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
from app.shared.rbac.check import CapabilityRegistry, get_default_registry, has_capability

EXPLAIN_CAPABILITY = "recommendation.read"

_FARM_ID = uuid4()


@pytest.fixture
def registry() -> CapabilityRegistry:
    return get_default_registry()


def _farm_ctx(role: FarmRole) -> RequestContext:
    return RequestContext(
        user_id=uuid4(),
        keycloak_subject="kc",
        tenant_id=uuid4(),
        platform_role=None,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=_FARM_ID, role=role),),
    )


def _tenant_ctx(role: TenantRole) -> RequestContext:
    return RequestContext(
        user_id=uuid4(),
        keycloak_subject="kc",
        tenant_id=uuid4(),
        platform_role=None,
        tenant_role=role,
        farm_scopes=(),
    )


@pytest.mark.parametrize(
    "role",
    [
        FarmRole.FARM_MANAGER,
        FarmRole.AGRONOMIST,
        FarmRole.FIELD_OPERATOR,
        FarmRole.SCOUT,
        FarmRole.VIEWER,
    ],
)
def test_every_farm_role_that_sees_recommendations_can_explain_them(
    role: FarmRole, registry: CapabilityRegistry
) -> None:
    ctx = _farm_ctx(role)
    # If a role can read a recommendation it must be able to read the reasoning.
    assert has_capability(ctx, "recommendation.read", farm_id=_FARM_ID, registry=registry) is True
    assert has_capability(ctx, EXPLAIN_CAPABILITY, farm_id=_FARM_ID, registry=registry) is True


@pytest.mark.parametrize("role", [TenantRole.TENANT_OWNER, TenantRole.TENANT_ADMIN])
def test_tenant_admins_keep_access(role: TenantRole, registry: CapabilityRegistry) -> None:
    assert has_capability(_tenant_ctx(role), EXPLAIN_CAPABILITY, registry=registry) is True


def test_the_old_gate_would_have_locked_out_the_agronomist(registry: CapabilityRegistry) -> None:
    """Regression: this is the bug the capability change fixes.

    Kept as an explicit assertion so that if someone ever "tidies" the
    explain route back onto decision_tree.read, the intent is on record.
    """
    ctx = _farm_ctx(FarmRole.AGRONOMIST)
    assert has_capability(ctx, "decision_tree.read", farm_id=_FARM_ID, registry=registry) is False


def test_read_only_roles_still_cannot_trigger_an_evaluation(registry: CapabilityRegistry) -> None:
    """The reason we did not simply widen decision_tree.read.

    POST :evaluate and POST :dry-run share that capability and both write, so
    granting it to Viewer to unblock a read-only screen would have handed a
    read-only role two write paths.
    """
    ctx = _farm_ctx(FarmRole.VIEWER)
    assert has_capability(ctx, EXPLAIN_CAPABILITY, farm_id=_FARM_ID, registry=registry) is True
    assert has_capability(ctx, "decision_tree.read", farm_id=_FARM_ID, registry=registry) is False


def test_billing_admin_has_no_business_here(registry: CapabilityRegistry) -> None:
    assert (
        has_capability(_tenant_ctx(TenantRole.BILLING_ADMIN), EXPLAIN_CAPABILITY, registry=registry)
        is False
    )


def test_platform_support_can_read_it_for_support_cases(registry: CapabilityRegistry) -> None:
    ctx = RequestContext(
        user_id=uuid4(),
        keycloak_subject="kc",
        tenant_id=uuid4(),
        platform_role=PlatformRole.PLATFORM_SUPPORT,
        tenant_role=None,
        farm_scopes=(),
    )
    assert has_capability(ctx, EXPLAIN_CAPABILITY, registry=registry) is True
