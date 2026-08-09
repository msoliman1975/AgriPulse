"""Save-time validation of `{source: crop_attribute}` refs.

`crop_attribute` is the one condition source whose valid codes are data
rather than a constant: they live in ``public.crop_attribute_definitions``
and which ones are legal depends on the tree's crop targeting. So
``compile_tree`` cannot check them — it is sync, DB-free and runs at startup
for the platform seeds — and until now nothing did, despite the docstring in
``shared/conditions/models.py`` claiming the check lived "in the tree
validator".

The cost of not checking is silent: a ref to a code the target crops never
define resolves to None for every block the tree runs on, and
permissive-on-missing-data turns that into a comparison that fails closed
forever. The tree looks authored, publishes cleanly, and never fires.

These run against the real seeded catalog (migration 0051) rather than
fixtures, so a seed rename breaks them loudly instead of leaving the
validator asserting against codes nobody ships.
"""

from __future__ import annotations

import textwrap
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _DecisionTreeUnknownCropAttributeError,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

# Seeded by migration 0051 at the `mango` / `potato` crop nodes.
_MANGO_CODE = "age_at_transplant_months"
_POTATO_CODE = "seed_generation"


def _tree_yaml(code: str, attribute_code: str) -> str:
    return textwrap.dedent(
        f"""\
        code: {code}
        name_en: "Attribute tree {code}"
        root: root
        nodes:
          root:
            condition:
              tree:
                op: gt
                left:
                  source: crop_attribute
                  code: {attribute_code}
                  key: value
                right: 12
            on_match: leaf
            on_miss: leaf
          leaf:
            outcome:
              action_type: no_action
              text_en: "noop"
        """
    )


async def _service(admin_session: AsyncSession, slug: str) -> DecisionTreesAuthorService:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    return DecisionTreesAuthorService(public_session=admin_session, tenant_id=tenant.tenant_id)


@pytest.mark.asyncio
async def test_accepts_an_attribute_defined_for_the_target_crop(
    admin_session: AsyncSession,
) -> None:
    svc = await _service(admin_session, f"dt-attr-ok-{uuid4().hex[:8]}")
    code = f"dt_attr_ok_{uuid4().hex[:8]}"

    detail = await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_tree_yaml(code, _MANGO_CODE),
        crop_paths=["mango"],
        actor_user_id=None,
    )

    assert detail["code"] == code


@pytest.mark.asyncio
async def test_accepts_a_crop_level_attribute_for_a_cultivar_target(
    admin_session: AsyncSession,
) -> None:
    # Definitions are inherited down the taxonomy: a `mango` attribute
    # resolves for a `mango.keitt` block, so targeting the cultivar must not
    # reject the crop-level code.
    svc = await _service(admin_session, f"dt-attr-inherit-{uuid4().hex[:8]}")
    code = f"dt_attr_inherit_{uuid4().hex[:8]}"

    detail = await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_tree_yaml(code, _MANGO_CODE),
        crop_paths=["mango.keitt"],
        actor_user_id=None,
    )

    assert detail["code"] == code


@pytest.mark.asyncio
async def test_rejects_an_attribute_another_crop_owns(admin_session: AsyncSession) -> None:
    svc = await _service(admin_session, f"dt-attr-bad-{uuid4().hex[:8]}")
    code = f"dt_attr_bad_{uuid4().hex[:8]}"

    with pytest.raises(_DecisionTreeUnknownCropAttributeError) as excinfo:
        await svc.create_tree(
            code=code,
            crop_code=None,
            tree_yaml=_tree_yaml(code, _POTATO_CODE),
            crop_paths=["mango"],
            actor_user_id=None,
        )

    assert excinfo.value.codes == [_POTATO_CODE]
    assert excinfo.value.crop_paths == ["mango"]
    # Rejected before any write — a half-created tree row would be worse than
    # the dead branch this prevents.
    assert await svc.get_tree_detail(code=code) is None


@pytest.mark.asyncio
async def test_rejects_a_code_that_exists_nowhere(admin_session: AsyncSession) -> None:
    svc = await _service(admin_session, f"dt-attr-typo-{uuid4().hex[:8]}")
    code = f"dt_attr_typo_{uuid4().hex[:8]}"

    with pytest.raises(_DecisionTreeUnknownCropAttributeError) as excinfo:
        await svc.create_tree(
            code=code,
            crop_code=None,
            tree_yaml=_tree_yaml(code, "no_such_attribute_anywhere"),
            crop_paths=["mango"],
            actor_user_id=None,
        )

    assert excinfo.value.codes == ["no_such_attribute_anywhere"]


@pytest.mark.asyncio
async def test_append_version_checks_against_the_stored_targeting(
    admin_session: AsyncSession,
) -> None:
    # The version payload carries no targeting — the pickers edit it on the
    # tree row — so the check has to read the stored crop paths, not the YAML.
    svc = await _service(admin_session, f"dt-attr-append-{uuid4().hex[:8]}")
    code = f"dt_attr_append_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_tree_yaml(code, _MANGO_CODE),
        crop_paths=["mango"],
        actor_user_id=None,
    )

    with pytest.raises(_DecisionTreeUnknownCropAttributeError):
        await svc.append_version(
            code=code,
            tree_yaml=_tree_yaml(code, _POTATO_CODE),
            notes="swap in an attribute mango doesn't have",
            actor_user_id=None,
        )

    detail = await svc.get_tree_detail(code=code)
    assert detail is not None
    assert len(detail["versions"]) == 1, "the rejected version must not have been written"


@pytest.mark.asyncio
async def test_retargeting_away_from_the_attributes_crop_is_rejected(
    admin_session: AsyncSession,
) -> None:
    # The other way a ref goes dead: the YAML never changes, but the crop set
    # moves out from under it. Nothing would edit the tree body, so without
    # this check the tree stays published and simply stops being able to fire.
    svc = await _service(admin_session, f"dt-attr-retarget-{uuid4().hex[:8]}")
    code = f"dt_attr_retarget_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_tree_yaml(code, _MANGO_CODE),
        crop_paths=["mango"],
        actor_user_id=None,
    )

    with pytest.raises(_DecisionTreeUnknownCropAttributeError) as excinfo:
        await svc.update_tree(
            code=code,
            name_en="Retargeted",
            name_ar=None,
            description_en=None,
            description_ar=None,
            crop_paths=["potato"],
            country_codes=[],
            soil_textures=[],
            scope="block",
            actor_user_id=None,
        )

    assert excinfo.value.codes == [_MANGO_CODE]
    detail = await svc.get_tree_detail(code=code)
    assert detail is not None
    assert detail["crop_paths"] == ["mango"], "targeting must not have been written"


@pytest.mark.asyncio
async def test_retargeting_within_the_same_crop_is_allowed(admin_session: AsyncSession) -> None:
    svc = await _service(admin_session, f"dt-attr-narrow-{uuid4().hex[:8]}")
    code = f"dt_attr_narrow_{uuid4().hex[:8]}"
    await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=_tree_yaml(code, _MANGO_CODE),
        crop_paths=["mango"],
        actor_user_id=None,
    )

    detail = await svc.update_tree(
        code=code,
        name_en="Narrowed to a cultivar",
        name_ar=None,
        description_en=None,
        description_ar=None,
        crop_paths=["mango.keitt"],
        country_codes=[],
        soil_textures=[],
        scope="block",
        actor_user_id=None,
    )

    assert detail["crop_paths"] == ["mango.keitt"]


@pytest.mark.asyncio
async def test_a_tree_with_no_attribute_refs_is_unaffected(admin_session: AsyncSession) -> None:
    svc = await _service(admin_session, f"dt-attr-none-{uuid4().hex[:8]}")
    code = f"dt_attr_none_{uuid4().hex[:8]}"
    yaml = textwrap.dedent(
        f"""\
        code: {code}
        name_en: "No attribute refs"
        root: root
        nodes:
          root:
            condition:
              tree:
                op: lt
                left:
                  source: indices
                  index_code: ndvi
                  key: baseline_deviation
                right: -1.0
            on_match: leaf
            on_miss: leaf
          leaf:
            outcome:
              action_type: no_action
              text_en: "noop"
        """
    )

    detail = await svc.create_tree(
        code=code,
        crop_code=None,
        tree_yaml=yaml,
        crop_paths=["mango"],
        actor_user_id=None,
    )

    assert detail["code"] == code
