"""Integration tests for decision-tree metadata edit + archive/restore.

Covers the experience-redesign backend (PR-1):

  * ``update_tree`` full-replaces the editable metadata (name,
    description, multi-axis targeting, execution scope) and persists
    every axis.
  * ``archive_tree`` soft-deletes — the tree drops out of the authoring
    list + the evaluator listing, but ``restore_tree`` brings it back
    loss-free.
  * Metadata edits + archive are scoped to the caller's own tenant.

Exercises the service layer directly (like ``test_tenant_isolation``)
so the tests stay close to the scoping invariants.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _DecisionTreeNotFoundError,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


def _minimal_tree_yaml(code: str) -> str:
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


async def _make_tenant_service(
    admin_session: AsyncSession, slug: str
) -> DecisionTreesAuthorService:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    return DecisionTreesAuthorService(public_session=admin_session, tenant_id=tenant.tenant_id)


@pytest.mark.asyncio
async def test_update_tree_persists_targeting(admin_session: AsyncSession) -> None:
    svc = await _make_tenant_service(admin_session, f"dt-update-{uuid4().hex[:8]}")
    code = f"dt_update_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(code),
        actor_user_id=None,
    )

    detail = await svc.update_tree(
        code=code,
        name_en="Renamed tree",
        name_ar="شجرة معاد تسميتها",
        description_en="A better description",
        description_ar=None,
        crop_paths=["citrus.orange"],
        country_codes=["EG", "JO"],
        soil_textures=["sandy_loam"],
        scope="cell",
        actor_user_id=None,
    )

    assert detail["name_en"] == "Renamed tree"
    assert detail["name_ar"] == "شجرة معاد تسميتها"
    assert detail["description_en"] == "A better description"
    assert detail["crop_paths"] == ["citrus.orange"]
    assert detail["country_codes"] == ["EG", "JO"]
    assert detail["soil_textures"] == ["sandy_loam"]
    assert detail["scope"] == "cell"

    # Re-read independently to confirm it persisted (not just echoed).
    reread = await svc.get_tree_detail(code=code)
    assert reread is not None
    assert reread["country_codes"] == ["EG", "JO"]
    assert reread["scope"] == "cell"


@pytest.mark.asyncio
async def test_archive_hides_from_list_and_restore_brings_back(
    admin_session: AsyncSession,
) -> None:
    svc = await _make_tenant_service(admin_session, f"dt-archive-{uuid4().hex[:8]}")
    code = f"dt_archive_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(code),
        actor_user_id=None,
    )

    await svc.archive_tree(code=code, actor_user_id=None)
    # Archived: absent from the authoring list + reads as not-found.
    assert all(t["code"] != code for t in await svc.list_trees())
    assert await svc.get_tree_detail(code=code) is None

    restored = await svc.restore_tree(code=code, actor_user_id=None)
    assert restored["code"] == code
    assert any(t["code"] == code for t in await svc.list_trees())
    assert await svc.get_tree_detail(code=code) is not None


@pytest.mark.asyncio
async def test_archived_tree_excluded_from_evaluator(
    admin_session: AsyncSession,
) -> None:
    svc = await _make_tenant_service(admin_session, f"dt-evalarch-{uuid4().hex[:8]}")
    repo = RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)
    code = f"dt_evalarch_{uuid4().hex[:8]}"
    created = await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(code),
        actor_user_id=None,
    )
    await svc.publish_version(code=code, version=1, actor_user_id=None)
    tenant_id = created["tenant_id"]

    before = await repo.list_active_trees_with_current_version(visible_to_tenant_id=tenant_id)
    assert any(t["tree_code"] == code for t in before)

    await svc.archive_tree(code=code, actor_user_id=None)
    after = await repo.list_active_trees_with_current_version(visible_to_tenant_id=tenant_id)
    assert all(t["tree_code"] != code for t in after)


@pytest.mark.asyncio
async def test_cannot_edit_or_archive_other_tenants_tree(
    admin_session: AsyncSession,
) -> None:
    svc_a = await _make_tenant_service(admin_session, f"dt-x-a-{uuid4().hex[:8]}")
    svc_b = await _make_tenant_service(admin_session, f"dt-x-b-{uuid4().hex[:8]}")
    code = f"dt_cross_{uuid4().hex[:8]}"
    await svc_a.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_minimal_tree_yaml(code),
        actor_user_id=None,
    )

    with pytest.raises(_DecisionTreeNotFoundError):
        await svc_b.update_tree(
            code=code,
            name_en="hijack",
            name_ar=None,
            description_en=None,
            description_ar=None,
            crop_paths=["citrus"],
            country_codes=[],
            soil_textures=[],
            scope="block",
            actor_user_id=None,
        )
    with pytest.raises(_DecisionTreeNotFoundError):
        await svc_b.archive_tree(code=code, actor_user_id=None)
