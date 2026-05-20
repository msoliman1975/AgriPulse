"""Tenant-isolation integration tests for the recommendations catalog (PR-A).

Exercises the new `public.decision_trees.tenant_id` scoping:

  * Tenant A authoring a tree stamps `tenant_id = A` on the row.
  * Tenant B's listing / lookup / evaluation does not see A's trees.
  * Platform-shipped trees (`tenant_id IS NULL`) are visible to every
    tenant (this is how built-in business knowledge ships).
  * A tenant cannot use a code that collides with a platform tree —
    keeps lookups by code unambiguous within any tenant's visibility
    scope.

We exercise the service layer directly (not the HTTP layer) so the
tests stay close to the scoping invariants and don't have to spin up
the FastAPI app + auth.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _DecisionTreeCodeAlreadyExistsError,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


def _minimal_tree_yaml(code: str) -> str:
    """A single-leaf tree that always returns `no_action` — enough to
    pass `compile_tree`, but the evaluator never emits a recommendation
    for it (we only care about catalog visibility here)."""
    return textwrap.dedent(
        f"""\
        code: {code}
        name_en: "Test tree {code}"
        root: leaf
        nodes:
          leaf:
            outcome:
              action_type: no_action
              text_en: "noop"
        """
    )


async def _insert_platform_tree_via_sql(
    admin_session: AsyncSession, *, code: str
) -> None:
    """Insert a platform tree (tenant_id NULL) directly via SQL — bypasses
    the authoring service which would stamp tenant_id from its caller."""
    await admin_session.execute(
        text(
            "INSERT INTO public.decision_trees "
            "(code, tenant_id, name_en, applicable_regions, is_active) "
            "VALUES (:c, NULL, :name, ARRAY[]::text[], TRUE)"
        ),
        {"c": code, "name": f"Platform {code}"},
    )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_tenant_a_tree_not_visible_to_tenant_b(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant_a = await tenancy.create_tenant(
        slug="pra-isolation-a",
        name="PR-A Isolation A",
        contact_email="ops@pra-a.test",
    )
    tenant_b = await tenancy.create_tenant(
        slug="pra-isolation-b",
        name="PR-A Isolation B",
        contact_email="ops@pra-b.test",
    )

    svc_a = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant_a.tenant_id
    )
    code = "pra_tenant_a_only"
    await svc_a.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(code),
        actor_user_id=None,
    )

    # Tenant A sees their own tree in the authoring list.
    a_trees = await svc_a.list_trees()
    assert any(t["code"] == code for t in a_trees), (
        "tenant A should see their own tree"
    )
    a_row = next(t for t in a_trees if t["code"] == code)
    assert a_row["tenant_id"] == tenant_a.tenant_id

    # Tenant B does not see it in their authoring list, nor by lookup.
    svc_b = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant_b.tenant_id
    )
    b_trees = await svc_b.list_trees()
    assert all(t["code"] != code for t in b_trees), (
        "tenant B must not see tenant A's tree"
    )
    assert await svc_b.get_tree_detail(code=code) is None


@pytest.mark.asyncio
async def test_platform_tree_visible_to_every_tenant(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant_a = await tenancy.create_tenant(
        slug="pra-platform-vis-a",
        name="PR-A Platform Visibility A",
        contact_email="ops@pra-pva.test",
    )
    tenant_b = await tenancy.create_tenant(
        slug="pra-platform-vis-b",
        name="PR-A Platform Visibility B",
        contact_email="ops@pra-pvb.test",
    )
    platform_code = f"pra_platform_{uuid4().hex[:8]}"
    await _insert_platform_tree_via_sql(admin_session, code=platform_code)

    svc_a = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant_a.tenant_id
    )
    svc_b = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant_b.tenant_id
    )
    a_listing = await svc_a.list_trees()
    b_listing = await svc_b.list_trees()
    assert any(t["code"] == platform_code and t["tenant_id"] is None for t in a_listing)
    assert any(t["code"] == platform_code and t["tenant_id"] is None for t in b_listing)


@pytest.mark.asyncio
async def test_tenant_cannot_shadow_platform_code(
    admin_session: AsyncSession,
) -> None:
    """A tenant authoring a tree must pick a code distinct from any
    platform code — otherwise `get_tree_by_code(include_platform=True)`
    becomes ambiguous and the wrong row could be returned by code lookups
    in subscribers / notifications."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pra-shadow-guard",
        name="PR-A Shadow Guard",
        contact_email="ops@pra-shadow.test",
    )
    platform_code = f"pra_shadowed_{uuid4().hex[:8]}"
    await _insert_platform_tree_via_sql(admin_session, code=platform_code)

    svc = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant.tenant_id
    )
    with pytest.raises(_DecisionTreeCodeAlreadyExistsError):
        await svc.create_tree(
            code=platform_code,
            crop_code=None,
            tree_yaml=_minimal_tree_yaml(platform_code),
            actor_user_id=None,
        )


@pytest.mark.asyncio
async def test_evaluator_listing_includes_platform_and_own_only(
    admin_session: AsyncSession,
) -> None:
    """`list_active_trees_with_current_version` is the query the sweep
    uses; it must return platform trees plus caller's own trees, and exclude
    other tenants' trees."""
    tenancy = get_tenant_service(admin_session)
    tenant_a = await tenancy.create_tenant(
        slug="pra-evalscope-a",
        name="PR-A Eval Scope A",
        contact_email="ops@pra-eva.test",
    )
    tenant_b = await tenancy.create_tenant(
        slug="pra-evalscope-b",
        name="PR-A Eval Scope B",
        contact_email="ops@pra-evb.test",
    )

    # Tenant A authors a tree and publishes v1.
    svc_a = DecisionTreesAuthorService(
        public_session=admin_session, tenant_id=tenant_a.tenant_id
    )
    a_code = f"pra_eval_a_{uuid4().hex[:8]}"
    await svc_a.create_tree(
        code=a_code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(a_code),
        actor_user_id=None,
    )
    await svc_a.publish_version(code=a_code, version=1, actor_user_id=None)

    # Platform tree, also published (needs a published version to appear
    # in the evaluator's listing).
    platform_code = f"pra_eval_platform_{uuid4().hex[:8]}"
    await _insert_platform_tree_via_sql(admin_session, code=platform_code)
    await admin_session.execute(
        text(
            "WITH t AS (SELECT id FROM public.decision_trees WHERE code = :c) "
            "INSERT INTO public.decision_tree_versions "
            "(tree_id, version, tree_yaml, tree_compiled, compiled_hash, published_at) "
            "VALUES ((SELECT id FROM t), 1, :yaml, "
            "        CAST(:compiled AS jsonb), :hash, now()) "
            "RETURNING id"
        ),
        {
            "c": platform_code,
            "yaml": _minimal_tree_yaml(platform_code),
            "compiled": '{"code":"' + platform_code + '","root":"leaf",'
            '"nodes":{"leaf":{"outcome":{"action_type":"no_action","text_en":"x"}}}}',
            "hash": "deadbeef",
        },
    )
    await admin_session.execute(
        text(
            "UPDATE public.decision_trees t "
            "SET current_version_id = v.id "
            "FROM public.decision_tree_versions v "
            "WHERE v.tree_id = t.id AND v.version = 1 AND t.code = :c"
        ),
        {"c": platform_code},
    )
    await admin_session.commit()

    repo = RecommendationsRepository(
        tenant_session=admin_session, public_session=admin_session
    )
    visible_to_b = await repo.list_active_trees_with_current_version(
        visible_to_tenant_id=tenant_b.tenant_id
    )
    codes = {t["tree_code"] for t in visible_to_b}
    assert platform_code in codes, "tenant B must see platform trees"
    assert a_code not in codes, (
        "tenant B must NOT see tenant A's trees in the evaluator listing"
    )
