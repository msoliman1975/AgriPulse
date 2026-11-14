"""D26 on signals: platform definitions and templates carry Arabic.

Platform writes are the ones without a tenant schema. Tenant custom signals
may stay English. Untouched legacy platform rows without Arabic still save.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.signals.schemas import SignalTemplateDefinitionMember
from app.shared.arabic_required import ArabicRequiredError
from tests.unit.modules.signals.test_crop_scoped_signals import _impl as _impl_with_mocked_repo


def _create_kwargs(**over: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "code": "rpw_frass",
        "name": "RPW frass",
        "name_ar": "نشارة سوسة النخيل",
        "description": None,
        "value_kind": "categorical",
        "unit": None,
        "categorical_values": ["none", "some"],
        "categorical_values_ar": ["لا يوجد", "بعض"],
        "value_min": None,
        "value_max": None,
        "attachment_allowed": False,
        "aggregation": "latest",
        "aggregation_window_days": None,
        "actor_user_id": None,
        "tenant_schema": None,
    }
    kwargs.update(over)
    return kwargs


def _repo() -> AsyncMock:
    repo = AsyncMock()
    repo.insert_definition.return_value = {"id": uuid4()}
    repo.update_definition.return_value = {"id": uuid4()}
    return repo


class TestPlatformDefinitionCreate:
    async def test_complete_definition_saves(self) -> None:
        repo = _repo()
        await _impl_with_mocked_repo(repo).create_definition(**_create_kwargs())
        repo.insert_definition.assert_awaited_once()

    async def test_missing_name_ar_is_a_422(self) -> None:
        repo = _repo()
        with pytest.raises(ArabicRequiredError) as caught:
            await _impl_with_mocked_repo(repo).create_definition(
                **_create_kwargs(name_ar=None, description="Frass at the crown")
            )
        assert caught.value.status_code == 422
        assert caught.value.extras["missing_arabic"] == ["name_ar", "description_ar"]
        repo.insert_definition.assert_not_awaited()

    async def test_categorical_values_need_arabic_labels(self) -> None:
        repo = _repo()
        with pytest.raises(ArabicRequiredError) as caught:
            await _impl_with_mocked_repo(repo).create_definition(
                **_create_kwargs(categorical_values_ar=None)
            )
        assert caught.value.extras["missing_arabic"] == ["categorical_values_ar"]

    async def test_blank_arabic_value_label_is_refused(self) -> None:
        with pytest.raises(ArabicRequiredError):
            await _impl_with_mocked_repo(_repo()).create_definition(
                **_create_kwargs(categorical_values_ar=["لا يوجد", " "])
            )

    async def test_tenant_custom_signal_may_stay_english(self) -> None:
        repo = _repo()
        await _impl_with_mocked_repo(repo).create_definition(
            **_create_kwargs(name_ar=None, categorical_values_ar=None, tenant_schema="tenant_x")
        )
        repo.insert_definition.assert_awaited_once()


_LEGACY = {
    "code": "rpw_frass",
    "value_kind": "categorical",
    "name": "RPW frass",
    "name_ar": None,
    "description": "Seeded, English only",
    "description_ar": None,
    "unit": None,
    "unit_ar": None,
    "categorical_values": ["none", "some"],
    "categorical_values_ar": None,
}


class TestPlatformDefinitionUpdate:
    async def test_untouched_legacy_row_resaves(self) -> None:
        repo = _repo()
        repo.get_definition.return_value = dict(_LEGACY)
        await _impl_with_mocked_repo(repo).update_definition(
            definition_id=uuid4(),
            updates={"is_active": False, "aggregation_window_days": 14},
            actor_user_id=None,
            tenant_schema=None,
        )
        repo.update_definition.assert_awaited_once()

    async def test_renaming_legacy_row_without_arabic_is_refused(self) -> None:
        repo = _repo()
        repo.get_definition.return_value = dict(_LEGACY)
        with pytest.raises(ArabicRequiredError) as caught:
            await _impl_with_mocked_repo(repo).update_definition(
                definition_id=uuid4(),
                updates={"name": "Red palm weevil frass"},
                actor_user_id=None,
                tenant_schema=None,
            )
        assert caught.value.extras["missing_arabic"] == ["name_ar"]
        repo.update_definition.assert_not_awaited()

    async def test_clearing_arabic_is_refused(self) -> None:
        repo = _repo()
        repo.get_definition.return_value = {**_LEGACY, "name_ar": "نشارة"}
        with pytest.raises(ArabicRequiredError):
            await _impl_with_mocked_repo(repo).update_definition(
                definition_id=uuid4(),
                updates={"name_ar": ""},
                actor_user_id=None,
                tenant_schema=None,
            )

    async def test_tenant_update_is_not_checked(self) -> None:
        repo = _repo()
        repo.get_definition.return_value = dict(_LEGACY)
        await _impl_with_mocked_repo(repo).update_definition(
            definition_id=uuid4(),
            updates={"name": "Renamed"},
            actor_user_id=None,
            tenant_schema="tenant_x",
        )
        repo.update_definition.assert_awaited_once()


class TestPlatformTemplates:
    def _members(self) -> tuple[SignalTemplateDefinitionMember, ...]:
        return (SignalTemplateDefinitionMember(signal_definition_id=uuid4(), position=0),)

    async def test_new_template_without_arabic_is_refused(self) -> None:
        repo = AsyncMock()
        with pytest.raises(ArabicRequiredError):
            await _impl_with_mocked_repo(repo).create_template(
                code="rpw_round",
                name="RPW round",
                description=None,
                members=self._members(),
                actor_user_id=None,
                tenant_schema=None,
            )
        repo.insert_template.assert_not_awaited()

    async def test_untouched_legacy_template_resaves(self) -> None:
        repo = AsyncMock()
        repo.get_template.return_value = {
            "code": "rpw_round",
            "name": "RPW round",
            "name_ar": None,
            "description": None,
            "description_ar": None,
        }
        repo.update_template.return_value = {"id": uuid4()}
        await _impl_with_mocked_repo(repo).update_template(
            template_id=uuid4(),
            updates={"is_active": True},
            members=None,
            actor_user_id=None,
            tenant_schema=None,
        )
        repo.update_template.assert_awaited_once()
