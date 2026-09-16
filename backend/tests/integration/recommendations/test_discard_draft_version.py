"""Discarding an unpublished draft version.

Before this existed there was no way back from a save the author did not want.
The editor hydrates from the newest version and ``append_version`` returns the
existing row when the compiled hash is unchanged, so re-saving the old body did
nothing and the unwanted draft stayed in front of every later author.

Four things are refused, and each one has a reader that would be left holding
a version that is gone:

  * a published version — ``recommendations.tree_version`` and
    ``decision_tree_block_verdicts.tree_version`` are bare integers;
  * the current version — it is what the engine reads;
  * the tree's only version — the editor would have nothing to open;
  * a pinned version — ``tenant_tree_version_pins.version`` is a bare integer
    too, so the sweep would resolve a version that does not exist.

Exercises the service directly, like the sibling metadata tests.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _DecisionTreeNotFoundError,
    _DecisionTreeVersionNotDiscardableError,
    _DecisionTreeVersionNotFoundError,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


def _tree_yaml(code: str, text_en: str) -> str:
    return textwrap.dedent(
        f"""\
        code: {code}
        name_en: "Test tree {code}"
        root: leaf
        nodes:
          leaf:
            outcome:
              action_type: no_action
              text_en: "{text_en}"
        """
    )


async def _svc(admin_session: AsyncSession, slug: str) -> DecisionTreesAuthorService:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    return DecisionTreesAuthorService(public_session=admin_session, tenant_id=tenant.tenant_id)


async def _tree_with_published_v1_and_draft_v2(
    admin_session: AsyncSession, label: str
) -> tuple[DecisionTreesAuthorService, str]:
    svc = await _svc(admin_session, f"dt-{label}-{uuid4().hex[:8]}")
    code = f"dt_{label}_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code, crop_code=None, tree_yaml=_tree_yaml(code, "first"), actor_user_id=None
    )
    await svc.publish_version(code=code, version=1, actor_user_id=None)
    await svc.append_version(
        code=code, tree_yaml=_tree_yaml(code, "second"), notes=None, actor_user_id=None
    )
    return svc, code


@pytest.mark.asyncio
async def test_discards_an_unpublished_draft(admin_session: AsyncSession) -> None:
    svc, code = await _tree_with_published_v1_and_draft_v2(admin_session, "discard")
    before = await svc.get_tree_detail(code=code)
    assert before is not None
    assert [v["version"] for v in before["versions"]] == [2, 1]

    await svc.discard_version(code=code, version=2, actor_user_id=None)

    after = await svc.get_tree_detail(code=code)
    assert after is not None
    assert [v["version"] for v in after["versions"]] == [1]
    # The published version and what the engine reads are untouched.
    assert after["current_version"] == 1


@pytest.mark.asyncio
async def test_the_discarded_number_is_free_again(admin_session: AsyncSession) -> None:
    """The next save takes the number back.

    Nothing can be holding it: only a published version is ever recorded on a
    recommendation or a verdict, and the row that just went was never
    published.
    """
    svc, code = await _tree_with_published_v1_and_draft_v2(admin_session, "renum")
    await svc.discard_version(code=code, version=2, actor_user_id=None)

    await svc.append_version(
        code=code, tree_yaml=_tree_yaml(code, "third"), notes=None, actor_user_id=None
    )
    detail = await svc.get_tree_detail(code=code)
    assert detail is not None
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert "third" in detail["versions"][0]["tree_yaml"]


@pytest.mark.asyncio
async def test_refuses_a_published_version(admin_session: AsyncSession) -> None:
    svc, code = await _tree_with_published_v1_and_draft_v2(admin_session, "pub")
    with pytest.raises(_DecisionTreeVersionNotDiscardableError) as exc:
        await svc.discard_version(code=code, version=1, actor_user_id=None)
    # v1 is both published and current; published is the rule that answers.
    assert exc.value.reason == "published"

    detail = await svc.get_tree_detail(code=code)
    assert detail is not None
    assert [v["version"] for v in detail["versions"]] == [2, 1]


@pytest.mark.asyncio
async def test_refuses_the_only_version(admin_session: AsyncSession) -> None:
    svc = await _svc(admin_session, f"dt-only-{uuid4().hex[:8]}")
    code = f"dt_only_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code, crop_code=None, tree_yaml=_tree_yaml(code, "first"), actor_user_id=None
    )

    with pytest.raises(_DecisionTreeVersionNotDiscardableError) as exc:
        await svc.discard_version(code=code, version=1, actor_user_id=None)
    assert exc.value.reason == "only_version"


@pytest.mark.asyncio
async def test_refuses_a_pinned_version(admin_session: AsyncSession) -> None:
    svc, code = await _tree_with_published_v1_and_draft_v2(admin_session, "pinned")
    detail = await svc.get_tree_detail(code=code)
    assert detail is not None
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_tree_version_pins (tenant_id, tree_id, version) "
            "VALUES (:tenant, :tree, 2)"
        ),
        {"tenant": uuid4(), "tree": detail["id"]},
    )

    with pytest.raises(_DecisionTreeVersionNotDiscardableError) as exc:
        await svc.discard_version(code=code, version=2, actor_user_id=None)
    assert exc.value.reason == "pinned"

    after = await svc.get_tree_detail(code=code)
    assert after is not None
    assert [v["version"] for v in after["versions"]] == [2, 1]


@pytest.mark.asyncio
async def test_unknown_version_is_not_found(admin_session: AsyncSession) -> None:
    svc, code = await _tree_with_published_v1_and_draft_v2(admin_session, "missing")
    with pytest.raises(_DecisionTreeVersionNotFoundError):
        await svc.discard_version(code=code, version=99, actor_user_id=None)


@pytest.mark.asyncio
async def test_cannot_discard_another_tenants_draft(admin_session: AsyncSession) -> None:
    svc_a, code = await _tree_with_published_v1_and_draft_v2(admin_session, "cross")
    svc_b = await _svc(admin_session, f"dt-cross-b-{uuid4().hex[:8]}")

    # Tenant B's scoped lookup never sees the row, so it reads as absent —
    # the same answer every other authoring write gives across tenants.
    with pytest.raises(_DecisionTreeNotFoundError):
        await svc_b.discard_version(code=code, version=2, actor_user_id=None)

    after = await svc_a.get_tree_detail(code=code)
    assert after is not None
    assert [v["version"] for v in after["versions"]] == [2, 1]
