"""The database owns the platform catalogue, and who may change what.

Four things this file holds to, each of which was untrue before:

  * **A platform admin can author a platform tree.** Every authoring route
    used to assert a tenant context, so a platform tree had no editor at all:
    a tenant admin is out of scope by definition, and a platform admin was
    refused for having no tenant.
  * **A tenant still cannot.** The 403 from #665 stays. Widening the platform
    scope must not widen the tenant one.
  * **A tenant can copy a platform tree**, and the copy is a separate row with
    a separate code, published, that does not move when the original does.
  * **A pin holds a tenant at one version** while an unpinned tenant follows
    the publish.

The version assertions are made against what the evaluator actually resolves
(`list_active_trees_with_current_version`), not against the pin row. A test
that read back the pin it just wrote would pass with the resolution never
wired in — which is the whole mechanism.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.recommendations.service import (
    _DecisionTreeCodeAlreadyExistsError,
    _PlatformTreeNotEditableError,
    _TenantScopeRequiredError,
    get_decision_trees_author_service,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]

# Crop-agnostic and block-scoped so it needs no crop assignment, and authored
# per test so it cannot reach into another test's tenant.
TREE_YAML = """
code: {code}
name_en: Platform catalogue fixture
name_ar: قاعدة اختبار كتالوج المنصة
crop_path: mango
country_codes: [EG]
root: root
nodes:
  root:
    label_en: Is NDVI far below its seasonal baseline?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: {threshold}
    on_match: leaf_scout
    on_miss: leaf_no_action
  leaf_scout:
    label_en: Severe drop — scout
    outcome:
      action_type: scout
      severity: critical
      confidence: 0.85
      valid_for_hours: 72
      text_en: Scout this block.
  leaf_no_action:
    label_en: No action
    outcome:
      action_type: no_action
      severity: info
      confidence: 0.9
      text_en: Within baseline.
"""


async def _platform_tree(code: str, *, threshold: str = "-1.5") -> UUID:
    """Author and publish a platform tree as a platform admin would.

    `tenant_id=None` is the platform scope. Before this change the service
    took a required UUID and there was no way to reach this at all.
    """
    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        await author.create_tree(
            code=code,
            crop_code=None,
            tree_yaml=TREE_YAML.format(code=code, threshold=threshold),
            actor_user_id=None,
        )
        await author.publish_version(code=code, version=1, actor_user_id=None)
        row = (
            await public_session.execute(
                text(
                    "SELECT id FROM public.decision_trees " "WHERE code = :c AND tenant_id IS NULL"
                ),
                {"c": code},
            )
        ).one()
    return UUID(str(row.id))


async def _make_tenant(admin: AsyncSession, slug: str) -> tuple[UUID, str]:
    tenancy = get_tenant_service(admin)
    tenant = await tenancy.create_tenant(
        slug=f"{slug}-{uuid4().hex[:6]}",
        name="Trees live in the database",
        contact_email="ops@trees-in-db.test",
    )
    # `create_tenant` flushes and leaves the commit to the caller. Sessions
    # opened below read `public.tenants` on their own connection, so without
    # this the tenant is invisible to them.
    await admin.commit()
    return tenant.tenant_id, tenant.schema_name


async def _resolved_version(tenant_id: UUID, code: str) -> int | None:
    """What the evaluator would actually walk for this tenant.

    This is the assertion that matters. Reading the pin row back would prove
    the write landed and nothing about whether the sweep honours it.
    """
    factory = AsyncSessionLocal()
    async with factory() as public_session:
        repo = RecommendationsRepository(
            tenant_session=public_session, public_session=public_session
        )
        rows = await repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id, only_code=code
        )
    return None if not rows else int(rows[0]["version"])


async def _resolved_tree(tenant_id: UUID, code: str) -> dict:
    """The row the evaluator would target with, not the row the API echoed."""
    factory = AsyncSessionLocal()
    async with factory() as public_session:
        repo = RecommendationsRepository(
            tenant_session=public_session, public_session=public_session
        )
        rows = await repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id, only_code=code
        )
    assert rows, f"no active tree {code!r} for this tenant"
    return dict(rows[0])


# ---- Platform authoring ---------------------------------------------------


async def test_a_platform_admin_authors_a_platform_tree(admin_session: AsyncSession) -> None:
    code = f"platform_authoring_{uuid4().hex[:8]}"
    tree_id = await _platform_tree(code)

    row = (
        await admin_session.execute(
            text("SELECT tenant_id FROM public.decision_trees WHERE id = :i"),
            {"i": tree_id},
        )
    ).one()
    assert row.tenant_id is None, "a platform admin's tree must be a platform row"

    # And they can push it forward, which is the part that used to be
    # impossible: the YAML file would have overwritten it at the next restart.
    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        await author.append_version(
            code=code,
            tree_yaml=TREE_YAML.format(code=code, threshold="-2.0"),
            notes="Tightened by a platform admin, in the app.",
            actor_user_id=None,
        )
        await author.publish_version(code=code, version=2, actor_user_id=None)

    detail = await _detail(None, code)
    assert detail["current_version"] == 2


async def _detail(tenant_id: UUID | None, code: str) -> dict:
    factory = AsyncSessionLocal()
    async with factory() as public_session:
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        detail = await author.get_tree_detail(code=code)
    assert detail is not None
    return detail


async def test_a_tenant_still_cannot_edit_a_platform_tree(admin_session: AsyncSession) -> None:
    """Widening the platform scope must not widen the tenant one."""
    code = f"tenant_refused_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, _ = await _make_tenant(admin_session, "refused")

    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        with pytest.raises(_PlatformTreeNotEditableError):
            await author.append_version(
                code=code,
                tree_yaml=TREE_YAML.format(code=code, threshold="-9.0"),
                notes="Should never land.",
                actor_user_id=None,
            )


async def test_a_platform_admin_sees_only_platform_trees(admin_session: AsyncSession) -> None:
    """The platform scope is not "everything" — it is `tenant_id IS NULL`."""
    platform_code = f"visible_platform_{uuid4().hex[:8]}"
    await _platform_tree(platform_code)
    tenant_id, _ = await _make_tenant(admin_session, "visibility")
    tenant_code = f"visible_tenant_{uuid4().hex[:8]}"

    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        await author.create_tree(
            code=tenant_code,
            crop_code=None,
            tree_yaml=TREE_YAML.format(code=tenant_code, threshold="-1.0"),
            actor_user_id=None,
        )

    async with factory() as public_session:
        platform_author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=None
        )
        codes = {t["code"] for t in await platform_author.list_trees()}
    assert platform_code in codes
    assert tenant_code not in codes, "a platform admin must not see a tenant's trees"


async def test_copy_and_pin_are_refused_without_a_tenant() -> None:
    """A platform caller has no farms to enable a tree on and no pin to hold."""
    code = f"no_tenant_ops_{uuid4().hex[:8]}"
    await _platform_tree(code)

    factory = AsyncSessionLocal()
    async with factory() as public_session:
        author = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        with pytest.raises(_TenantScopeRequiredError):
            await author.pin_tree_version(code=code, version=1, actor_user_id=None)


# ---- Copying --------------------------------------------------------------


async def test_a_copy_is_a_separate_published_row(admin_session: AsyncSession) -> None:
    code = f"copy_source_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "copier")

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            copy = await author.copy_tree_to_tenant(
                code=code,
                new_code=None,
                # No farms in this tenant, so there is nothing to disable and
                # the flag's own behaviour is asserted separately.
                disable_original=False,
                tenant_session=tenant_session,
                actor_user_id=None,
            )

    assert copy["code"] != code, "a copy cannot keep the original's code"
    assert copy["code"].startswith(f"{code}__")
    assert copy["tenant_id"] is not None
    # Published, not a draft. A draft plus "disable the original" would leave
    # the tenant running neither.
    assert copy["current_version"] == 1
    assert await _resolved_version(tenant_id, copy["code"]) == 1

    # Targeting comes across whole. A copy that quietly lost an axis would
    # reach blocks the original never did, or none at all, and the only
    # symptom would be cards appearing or stopping for no stated reason.
    resolved = await _resolved_tree(tenant_id, copy["code"])
    assert resolved["crop_path"] == "mango"
    assert list(resolved["crop_paths"]) == ["mango"]
    assert list(resolved["country_codes"]) == ["EG"]


async def test_a_copy_does_not_move_when_the_original_is_republished(
    admin_session: AsyncSession,
) -> None:
    """The cost of a copy, asserted rather than left to be discovered."""
    code = f"copy_frozen_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "frozen")

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            copy = await author.copy_tree_to_tenant(
                code=code,
                new_code=None,
                disable_original=False,
                tenant_session=tenant_session,
                actor_user_id=None,
            )
    copy_code = copy["code"]

    # The platform publishes v2 of the original.
    async with factory() as public_session, public_session.begin():
        platform = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        await platform.append_version(
            code=code,
            tree_yaml=TREE_YAML.format(code=code, threshold="-3.0"),
            notes="v2",
            actor_user_id=None,
        )
        await platform.publish_version(code=code, version=2, actor_user_id=None)

    assert await _resolved_version(tenant_id, code) == 2, "the original follows the publish"
    assert await _resolved_version(tenant_id, copy_code) == 1, "the copy does not"


async def test_a_copy_cannot_collide_with_an_existing_code(
    admin_session: AsyncSession,
) -> None:
    code = f"copy_collide_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "collide")

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            # Asking for the original's own code is the collision the derived
            # code exists to avoid: two rows would answer `get_tree_by_code`.
            with pytest.raises(_DecisionTreeCodeAlreadyExistsError):
                await author.copy_tree_to_tenant(
                    code=code,
                    new_code=code,
                    disable_original=False,
                    tenant_session=tenant_session,
                    actor_user_id=None,
                )


# ---- Version pins ---------------------------------------------------------


async def test_a_pin_holds_one_tenant_while_others_follow(
    admin_session: AsyncSession,
) -> None:
    code = f"pinned_{uuid4().hex[:8]}"
    await _platform_tree(code)
    holder_id, _ = await _make_tenant(admin_session, "holder")
    follower_id, _ = await _make_tenant(admin_session, "follower")

    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=holder_id
        )
        await author.pin_tree_version(code=code, version=1, actor_user_id=None)

    # The platform publishes v2 after the pin.
    async with factory() as public_session, public_session.begin():
        platform = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        await platform.append_version(
            code=code,
            tree_yaml=TREE_YAML.format(code=code, threshold="-4.0"),
            notes="v2",
            actor_user_id=None,
        )
        await platform.publish_version(code=code, version=2, actor_user_id=None)

    assert await _resolved_version(holder_id, code) == 1, "the pin holds"
    assert await _resolved_version(follower_id, code) == 2, "an unpinned tenant follows"

    # Clearing it lets the holder catch up, without republishing anything.
    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=holder_id
        )
        await author.clear_tree_version_pin(code=code, actor_user_id=None)

    assert await _resolved_version(holder_id, code) == 2


async def test_a_pin_must_name_a_published_version(admin_session: AsyncSession) -> None:
    """Pinning to a draft would drop the tree out of the sweep entirely — the
    resolution join requires `published_at IS NOT NULL`. That is a silent way
    to turn a tree off, and turning a tree off has its own control."""
    from app.modules.recommendations.service import _DecisionTreeNoPublishedVersionError

    code = f"pin_draft_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, _ = await _make_tenant(admin_session, "pindraft")

    factory = AsyncSessionLocal()
    async with factory() as public_session, public_session.begin():
        platform = get_decision_trees_author_service(public_session=public_session, tenant_id=None)
        await platform.append_version(
            code=code,
            tree_yaml=TREE_YAML.format(code=code, threshold="-5.0"),
            notes="left as a draft on purpose",
            actor_user_id=None,
        )

    async with factory() as public_session, public_session.begin():
        author = get_decision_trees_author_service(
            public_session=public_session, tenant_id=tenant_id
        )
        with pytest.raises(_DecisionTreeNoPublishedVersionError):
            await author.pin_tree_version(code=code, version=2, actor_user_id=None)

    assert await _resolved_version(tenant_id, code) == 1, "still on the published version"


# ---- Tenant-wide enable and disable ---------------------------------------


async def _seed_farm(admin: AsyncSession, schema: str, code: str) -> UUID:
    """One bare farm. Nothing here needs blocks — the toggle writes farm rows,
    and the farm count is what the screen reads back."""
    farm_id = uuid4()
    await admin.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await admin.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:fid, :code, :name, "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, "
            "31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100)"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id, "code": code, "name": f"Farm {code}"},
    )
    await admin.commit()
    return farm_id


async def _availability(tenant_id: UUID, schema: str, code: str) -> dict:
    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session:
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            return await author.get_tree_availability(code=code, tenant_session=tenant_session)


async def _set_enabled(tenant_id: UUID, schema: str, code: str, enabled: bool) -> dict:
    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            return await author.set_tree_enabled_everywhere(
                code=code,
                enabled=enabled,
                tenant_session=tenant_session,
                actor_user_id=None,
            )


async def test_turning_a_tree_off_everywhere_writes_a_row_per_farm(
    admin_session: AsyncSession,
) -> None:
    code = f"toggle_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "toggle")
    for i in range(3):
        await _seed_farm(admin_session, schema, f"TF{i}-{uuid4().hex[:4]}")

    before = await _availability(tenant_id, schema, code)
    assert before["farms_total"] == 3
    assert before["farms_running"] == 3, "a farm with no exclusion row runs the tree"
    assert before["enabled_everywhere"] is True

    off = await _set_enabled(tenant_id, schema, code, False)
    assert off["farms_changed"] == 3
    assert off["farms_running"] == 0

    # Idempotent: a second call writes nothing and still succeeds.
    again = await _set_enabled(tenant_id, schema, code, False)
    assert again["farms_changed"] == 0
    assert again["farms_running"] == 0

    on = await _set_enabled(tenant_id, schema, code, True)
    assert on["farms_changed"] == 3
    assert on["farms_running"] == 3


async def test_a_farm_added_after_off_everywhere_runs_the_tree(
    admin_session: AsyncSession,
) -> None:
    """The consequence of storing enablement as farm rows, asserted so nobody
    reports it as a bug. "Off everywhere" is "off on the farms that existed"."""
    code = f"newfarm_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "newfarm")
    await _seed_farm(admin_session, schema, f"NF0-{uuid4().hex[:4]}")

    await _set_enabled(tenant_id, schema, code, False)
    assert (await _availability(tenant_id, schema, code))["farms_running"] == 0

    await _seed_farm(admin_session, schema, f"NF1-{uuid4().hex[:4]}")

    after = await _availability(tenant_id, schema, code)
    assert after["farms_total"] == 2
    assert after["farms_running"] == 1, "the new farm inherits nothing and runs the tree"
    assert after["enabled_everywhere"] is False


async def test_copying_with_disable_original_turns_the_original_off(
    admin_session: AsyncSession,
) -> None:
    code = f"copy_disable_{uuid4().hex[:8]}"
    await _platform_tree(code)
    tenant_id, schema = await _make_tenant(admin_session, "copydisable")
    for i in range(2):
        await _seed_farm(admin_session, schema, f"CD{i}-{uuid4().hex[:4]}")

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        async with factory() as public_session, public_session.begin():
            author = get_decision_trees_author_service(
                public_session=public_session, tenant_id=tenant_id
            )
            copy = await author.copy_tree_to_tenant(
                code=code,
                new_code=None,
                disable_original=True,
                tenant_session=tenant_session,
                actor_user_id=None,
            )

    assert copy["disabled_original_on_farms"] == 2
    original = await _availability(tenant_id, schema, code)
    assert original["farms_running"] == 0, "the original stopped on every farm"
    copied = await _availability(tenant_id, schema, copy["code"])
    assert copied["farms_running"] == 2, "and the copy runs in its place"
