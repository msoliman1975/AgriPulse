"""D26 on the inputs catalogue: platform inputs carry an Arabic name."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.inputs import router as inputs_router
from app.modules.inputs.schemas import InputCreateRequest, InputUpdateRequest
from app.shared.arabic_required import ArabicRequiredError


def _ctx(tenant_id: Any = None) -> Any:
    return SimpleNamespace(tenant_id=tenant_id, user_id=uuid4())


@pytest.fixture(autouse=True)
def _allowed() -> Any:
    with (
        patch.object(inputs_router, "_ensure_can_write", lambda _ctx: None),
        patch.object(inputs_router, "get_audit_service", lambda: AsyncMock()),
    ):
        yield


def _repo(existing: dict[str, Any] | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.code_taken.return_value = False
    repo.create.return_value = uuid4()
    repo.get_input.return_value = existing or {"id": uuid4(), "tenant_id": None}
    return repo


async def test_platform_input_without_arabic_is_a_422() -> None:
    repo = _repo()
    with pytest.raises(ArabicRequiredError):
        await inputs_router.create_input(
            InputCreateRequest(
                code="copper", name_en="Copper", category="mineral_or_botanical_treatment"
            ),
            context=_ctx(),
            repo=repo,
        )
    repo.create.assert_not_awaited()


async def test_tenant_input_may_stay_english() -> None:
    repo = _repo()
    await inputs_router.create_input(
        InputCreateRequest(
            code="copper", name_en="Copper", category="mineral_or_botanical_treatment"
        ),
        context=_ctx(tenant_id=uuid4()),
        repo=repo,
    )
    repo.create.assert_awaited_once()


async def test_untouched_legacy_platform_input_resaves() -> None:
    legacy = {"id": uuid4(), "tenant_id": None, "name_en": "Copper", "name_ar": None}
    repo = _repo(legacy)
    await inputs_router.update_input(
        legacy["id"], InputUpdateRequest(phi_days=7), context=_ctx(), repo=repo
    )
    repo.update.assert_awaited_once()


async def test_renaming_legacy_platform_input_needs_arabic() -> None:
    legacy = {"id": uuid4(), "tenant_id": None, "name_en": "Copper", "name_ar": None}
    repo = _repo(legacy)
    with pytest.raises(ArabicRequiredError):
        await inputs_router.update_input(
            legacy["id"],
            InputUpdateRequest(name_en="Copper oxychloride"),
            context=_ctx(),
            repo=repo,
        )
    repo.update.assert_not_awaited()
