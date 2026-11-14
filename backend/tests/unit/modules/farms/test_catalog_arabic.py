"""D26 on the crop catalogue: varieties, strains, crops and attribute labels.

New rows need Arabic names; an update may not blank an existing Arabic name;
an untouched legacy row without Arabic still resaves.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.farms.service import FarmServiceImpl
from app.shared.arabic_required import ArabicRequiredError


def _crop(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "code": "mango",
        "name_en": "Mango",
        "name_ar": "مانجو",
        "is_perennial": True,
        "gdd_base_temp_c": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _service() -> tuple[FarmServiceImpl, AsyncMock]:
    impl = FarmServiceImpl.__new__(FarmServiceImpl)
    repo = AsyncMock()
    repo.get_crop.return_value = _crop()
    repo.variety_code_exists.return_value = False
    repo.strain_code_exists.return_value = False
    repo.create_variety.return_value = {"id": uuid4(), "path": "mango.keitt"}
    repo.create_strain.return_value = {"id": uuid4(), "path": "mango.keitt.a"}
    repo.update_variety.return_value = {"id": uuid4()}
    repo.update_strain.return_value = {"id": uuid4()}
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()  # type: ignore[attr-defined]
    return impl, repo


class TestVarietyAndStrainCreate:
    @pytest.mark.parametrize("name_ar", [None, "", "   "])
    async def test_variety_without_arabic_is_a_422(self, name_ar: str | None) -> None:
        impl, repo = _service()
        with pytest.raises(ArabicRequiredError) as caught:
            await impl.create_variety(
                crop_id=uuid4(), code="keitt", name_en="Keitt", name_ar=name_ar, actor_user_id=None
            )
        assert caught.value.status_code == 422
        assert caught.value.extras["missing_arabic"] == ["name_ar"]
        repo.create_variety.assert_not_awaited()

    async def test_variety_with_arabic_saves(self) -> None:
        impl, repo = _service()
        await impl.create_variety(
            crop_id=uuid4(), code="keitt", name_en="Keitt", name_ar="كيت", actor_user_id=None
        )
        repo.create_variety.assert_awaited_once()

    async def test_strain_without_arabic_is_a_422(self) -> None:
        impl, repo = _service()
        repo.get_variety.return_value = SimpleNamespace(
            id=uuid4(), crop_id=uuid4(), path="mango.keitt"
        )
        with pytest.raises(ArabicRequiredError):
            await impl.create_strain(
                crop_variety_id=uuid4(),
                code="a",
                name_en="Line A",
                name_ar=None,
                actor_user_id=None,
            )
        repo.create_strain.assert_not_awaited()


class TestVarietyAndStrainUpdate:
    async def test_untouched_legacy_variety_resaves(self) -> None:
        impl, repo = _service()
        repo.get_variety.return_value = SimpleNamespace(
            id=uuid4(), crop_id=uuid4(), name_en="Keitt", name_ar=None
        )
        await impl.update_variety(
            variety_id=uuid4(), fields={"is_active": False}, actor_user_id=None
        )
        repo.update_variety.assert_awaited_once()

    async def test_renaming_legacy_variety_needs_arabic(self) -> None:
        impl, repo = _service()
        repo.get_variety.return_value = SimpleNamespace(
            id=uuid4(), crop_id=uuid4(), name_en="Keitt", name_ar=None
        )
        with pytest.raises(ArabicRequiredError):
            await impl.update_variety(
                variety_id=uuid4(), fields={"name_en": "Keitt mango"}, actor_user_id=None
            )
        repo.update_variety.assert_not_awaited()

    async def test_blanking_existing_arabic_is_refused(self) -> None:
        impl, repo = _service()
        repo.get_strain.return_value = SimpleNamespace(
            id=uuid4(), crop_variety_id=uuid4(), name_en="Line A", name_ar="السلالة أ"
        )
        repo.get_variety.return_value = SimpleNamespace(id=uuid4(), crop_id=uuid4())
        with pytest.raises(ArabicRequiredError):
            await impl.update_strain(strain_id=uuid4(), fields={"name_ar": ""}, actor_user_id=None)
        repo.update_strain.assert_not_awaited()

    async def test_untouched_legacy_strain_resaves(self) -> None:
        impl, repo = _service()
        repo.get_strain.return_value = SimpleNamespace(
            id=uuid4(), crop_variety_id=uuid4(), name_en="Line A", name_ar=None
        )
        repo.get_variety.return_value = SimpleNamespace(id=uuid4(), crop_id=uuid4())
        await impl.update_strain(
            strain_id=uuid4(), fields={"default_thresholds": None}, actor_user_id=None
        )
        repo.update_strain.assert_awaited_once()


class TestCropAndAttributeLabels:
    async def test_whitespace_crop_arabic_is_refused(self) -> None:
        impl, repo = _service()
        with pytest.raises(ArabicRequiredError):
            await impl.create_crop(
                fields={"code": "fig", "name_en": "Fig", "name_ar": "  "}, actor_user_id=None
            )
        repo.create_crop.assert_not_awaited()

    async def test_new_attribute_description_needs_arabic(self) -> None:
        impl, repo = _service()
        with pytest.raises(ArabicRequiredError) as caught:
            await impl.create_crop_attribute_definition(
                crop_id=uuid4(),
                fields={
                    "code": "rootstock",
                    "name_en": "Rootstock",
                    "name_ar": "الأصل",
                    "description_en": "What it is grafted on",
                    "description_ar": None,
                    "unit_en": None,
                    "unit_ar": None,
                    "group_name_en": "Planting",
                    "group_name_ar": None,
                },
                actor_user_id=None,
            )
        assert caught.value.extras["missing_arabic"] == ["description_ar", "group_name_ar"]
        repo.create_crop_attribute_definition.assert_not_awaited()

    async def test_legacy_attribute_patch_without_arabic_passes_the_check(self) -> None:
        impl, repo = _service()
        repo.get_crop_attribute_definition.return_value = SimpleNamespace(
            id=uuid4(),
            name_en="Rootstock",
            name_ar="الأصل",
            description_en="Seeded, English only",
            description_ar=None,
        )
        impl._normalized_gates = lambda f: (_ for _ in ()).throw(  # type: ignore[method-assign]
            RuntimeError("past the Arabic check")
        )
        # The Arabic check lets it through; the next step (stubbed) is reached.
        with pytest.raises(RuntimeError, match="past the Arabic check"):
            await impl.update_crop_attribute_definition(
                definition_id=uuid4(), fields={"sort_order": 3}, actor_user_id=None
            )
