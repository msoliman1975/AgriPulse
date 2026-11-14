"""D26 on decision content: platform beta trees and platform findings.

Both sides of the rule: new or changed English without Arabic is refused
(a 422 the designer and the catalogue form render), and an untouched legacy
row or tree without Arabic still saves.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.recommendations.folding_arabic import ARABIC_RULE, check_tree_arabic
from app.modules.recommendations.folding_authoring import FoldingTreeAuthorService
from app.modules.recommendations.folding_compiler import FoldingCompileError
from app.modules.recommendations.router import _map_beta_error
from app.modules.recommendations.service import FindingsCatalogueService
from app.shared.arabic_required import ArabicRequiredError


def _tree(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": "mango_dry",
        "name_en": "Dry canopy",
        "name_ar": "مظلة جافة",
        "description_en": "Checks leaf water.",
        "description_ar": "يفحص ماء الورق.",
        "readiness_note_en": "Needs NDMI.",
        "readiness_note_ar": "يحتاج NDMI.",
        "parameters": {
            "ndmi_floor": {
                "type": "number",
                "default": -0.1,
                "description": "NDMI floor",
                "description_ar": "حد NDMI الأدنى",
            }
        },
        "registers": ["dry"],
        "combinations": [
            {
                "codes": ["dry"],
                "action_type": "irrigate",
                "status": "warning",
                "text_en": "Irrigate now",
                "text_ar": "اسقِ الآن",
            }
        ],
        "root": "cond_1",
        "nodes": {
            "cond_1": {"label_en": "Leaf water low?", "label_ar": "ماء الورق منخفض؟"},
            "stop_1": {"label_en": "End", "label_ar": "نهاية", "stop": True},
        },
    }
    body.update(over)
    return body


def _legacy_tree() -> dict[str, Any]:
    """A seeded tree with no Arabic anywhere."""
    body = _tree()
    for key in ("name_ar", "description_ar", "readiness_note_ar"):
        body[key] = None
    body["parameters"]["ndmi_floor"].pop("description_ar")
    body["combinations"][0]["text_ar"] = ""
    for node in body["nodes"].values():
        node.pop("label_ar")
    return body


class TestCheckTreeArabic:
    def test_complete_new_tree_passes(self) -> None:
        assert check_tree_arabic(_tree(), None) == []

    def test_new_tree_without_arabic_names_every_piece(self) -> None:
        errors = check_tree_arabic(_legacy_tree(), None)
        assert {e.rule for e in errors} == {ARABIC_RULE}
        text = " ".join(e.message_en for e in errors)
        for piece in (
            "name_ar",
            "description_ar",
            "readiness_note_ar",
            "'cond_1'",
            "'stop_1'",
            "Combination rule number 1",
            "'ndmi_floor'",
        ):
            assert piece in text
        assert {e.node_id for e in errors if e.node_id} == {"cond_1", "stop_1"}
        assert all(e.message_ar for e in errors)

    def test_resaving_an_untouched_legacy_tree_passes(self) -> None:
        legacy = _legacy_tree()
        assert check_tree_arabic(copy.deepcopy(legacy), legacy) == []

    def test_moving_a_legacy_node_passes(self) -> None:
        legacy = _legacy_tree()
        moved = copy.deepcopy(legacy)
        moved["nodes"]["cond_1"]["ui"] = {"x": 10, "y": 20}
        assert check_tree_arabic(moved, legacy) == []

    def test_new_node_in_legacy_tree_needs_arabic(self) -> None:
        legacy = _legacy_tree()
        after = copy.deepcopy(legacy)
        after["nodes"]["reg_1"] = {"label_en": "Record dry", "register": {"code": "dry"}}
        errors = check_tree_arabic(after, legacy)
        assert [e.node_ids for e in errors] == [("reg_1",)]

    def test_relabelled_legacy_node_needs_arabic(self) -> None:
        legacy = _legacy_tree()
        after = copy.deepcopy(legacy)
        after["nodes"]["stop_1"]["label_en"] = "Finish"
        assert [e.node_ids for e in check_tree_arabic(after, legacy)] == [("stop_1",)]

    def test_changed_combination_text_needs_arabic(self) -> None:
        legacy = _legacy_tree()
        after = copy.deepcopy(legacy)
        after["combinations"][0]["text_en"] = "Irrigate today"
        errors = check_tree_arabic(after, legacy)
        assert len(errors) == 1
        assert "Combination rule number 1" in errors[0].message_en

    def test_legacy_rule_rewritten_without_its_code_is_still_matched(self) -> None:
        # The designer's rule form drops `code`; the finding set still matches.
        legacy = _legacy_tree()
        legacy["combinations"][0]["code"] = "dry_only"
        after = copy.deepcopy(legacy)
        del after["combinations"][0]["code"]
        assert check_tree_arabic(after, legacy) == []

    def test_changed_parameter_description_needs_arabic(self) -> None:
        legacy = _legacy_tree()
        after = copy.deepcopy(legacy)
        after["parameters"]["ndmi_floor"]["description"] = "Lowest NDMI"
        errors = check_tree_arabic(after, legacy)
        assert len(errors) == 1
        assert "'ndmi_floor'" in errors[0].message_en

    def test_clearing_an_arabic_label_is_refused(self) -> None:
        before = _tree()
        after = copy.deepcopy(before)
        after["nodes"]["cond_1"]["label_ar"] = "  "
        assert [e.node_ids for e in check_tree_arabic(after, before)] == [("cond_1",)]


def _author(tenant_id: Any = None) -> FoldingTreeAuthorService:
    svc = FoldingTreeAuthorService.__new__(FoldingTreeAuthorService)
    svc._tenant_id = tenant_id  # type: ignore[attr-defined]
    svc._repo = AsyncMock()  # type: ignore[attr-defined]
    svc._audit = AsyncMock()  # type: ignore[attr-defined]
    svc._compile = AsyncMock(side_effect=lambda d, **_: {**d, "nodes": d["nodes"]})  # type: ignore[method-assign]
    svc.get_tree = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]
    svc._repo.get_tree_by_id.return_value = {"id": uuid4(), "code": "mango_dry"}
    svc._repo.get_tree_by_code.return_value = None
    svc._repo.insert_tree.return_value = uuid4()
    svc._repo.insert_version.return_value = uuid4()
    return svc


class TestBetaAuthoring:
    async def test_platform_create_without_arabic_is_a_422(self) -> None:
        svc = _author()
        with pytest.raises(FoldingCompileError) as caught:
            await svc.create_tree(
                code="mango_dry", definition=_legacy_tree(), notes=None, actor_user_id=None
            )
        svc._repo.insert_tree.assert_not_awaited()  # type: ignore[attr-defined]
        mapped = _map_beta_error(caught.value)
        assert mapped is not None
        assert mapped.status_code == 422

    async def test_tenant_create_without_arabic_is_allowed(self) -> None:
        svc = _author(tenant_id=uuid4())
        await svc.create_tree(
            code="mango_dry", definition=_legacy_tree(), notes=None, actor_user_id=None
        )
        svc._repo.insert_tree.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_platform_resave_of_untouched_legacy_tree_is_allowed(self) -> None:
        svc = _author()
        legacy = _legacy_tree()
        moved = copy.deepcopy(legacy)
        moved["nodes"]["cond_1"]["ui"] = {"x": 1, "y": 2}
        svc._repo.get_latest_version.return_value = {  # type: ignore[attr-defined]
            "version": 3,
            "compiled_hash": "different",
            "definition": legacy,
        }
        await svc.append_version(tree_id=uuid4(), definition=moved, notes=None, actor_user_id=None)
        svc._repo.insert_version.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_platform_new_node_without_arabic_is_refused(self) -> None:
        svc = _author()
        legacy = _legacy_tree()
        after = copy.deepcopy(legacy)
        after["nodes"]["reg_1"] = {"label_en": "Record dry"}
        svc._repo.get_latest_version.return_value = {  # type: ignore[attr-defined]
            "version": 3,
            "compiled_hash": "different",
            "definition": legacy,
        }
        with pytest.raises(FoldingCompileError) as caught:
            await svc.append_version(
                tree_id=uuid4(), definition=after, notes=None, actor_user_id=None
            )
        assert [e.node_ids for e in caught.value.errors] == [("reg_1",)]
        svc._repo.insert_version.assert_not_awaited()  # type: ignore[attr-defined]


def _findings(tenant_schema: str | None = None) -> FindingsCatalogueService:
    svc = FindingsCatalogueService.__new__(FindingsCatalogueService)
    svc._repo = AsyncMock()  # type: ignore[attr-defined]
    svc._tenant_schema = tenant_schema  # type: ignore[attr-defined]
    svc._audit = AsyncMock()  # type: ignore[attr-defined]
    return svc


_FINDING = {
    "clause_en": "leaf water is low",
    "clause_ar": "ماء الورق منخفض",
    "name_en": "Dry canopy",
    "name_ar": "مظلة جافة",
    "default_status": "warning",
    "description_en": None,
    "description_ar": None,
}


class TestPlatformFindings:
    async def test_new_description_without_arabic_is_a_422(self) -> None:
        svc = _findings()
        svc._repo.get_platform.return_value = None  # type: ignore[attr-defined]
        with pytest.raises(ArabicRequiredError) as caught:
            await svc.create(
                payload={**_FINDING, "code": "dry", "description_en": "Leaf water low."},
                actor_user_id=None,
            )
        assert caught.value.extras["missing_arabic"] == ["description_ar"]
        svc._repo.insert_platform.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_whitespace_arabic_clause_is_refused(self) -> None:
        svc = _findings()
        svc._repo.get_platform.return_value = None  # type: ignore[attr-defined]
        with pytest.raises(ArabicRequiredError):
            await svc.create(
                payload={**_FINDING, "code": "dry", "clause_ar": "   "}, actor_user_id=None
            )

    async def test_resaving_legacy_row_without_arabic_description_is_allowed(self) -> None:
        svc = _findings()
        legacy = {**_FINDING, "code": "dry", "description_en": "Seeded, English only."}
        svc._repo.get_platform.return_value = legacy  # type: ignore[attr-defined]
        svc._repo.update_platform.return_value = legacy  # type: ignore[attr-defined]
        payload = {k: v for k, v in legacy.items() if k != "code"}
        payload["default_status"] = "critical"
        await svc.update(code="dry", payload=payload, actor_user_id=None)
        svc._repo.update_platform.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_changed_legacy_description_without_arabic_is_refused(self) -> None:
        svc = _findings()
        legacy = {**_FINDING, "code": "dry", "description_en": "Seeded, English only."}
        svc._repo.get_platform.return_value = legacy  # type: ignore[attr-defined]
        payload = {k: v for k, v in legacy.items() if k != "code"}
        payload["description_en"] = "Rewritten."
        with pytest.raises(ArabicRequiredError):
            await svc.update(code="dry", payload=payload, actor_user_id=None)

    async def test_tenant_finding_may_stay_english(self) -> None:
        svc = _findings(tenant_schema="tenant_x")
        svc._repo.get_tenant.return_value = None  # type: ignore[attr-defined]
        svc._repo.get_platform.return_value = None  # type: ignore[attr-defined]
        svc._repo.insert_tenant.return_value = {"code": "dry"}  # type: ignore[attr-defined]
        await svc.create(
            payload={**_FINDING, "code": "dry", "description_en": "Only English."},
            actor_user_id=None,
        )
        svc._repo.insert_tenant.assert_awaited_once()  # type: ignore[attr-defined]
