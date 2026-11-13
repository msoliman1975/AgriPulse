"""D20: the Medjool inputs seed and the request shapes."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.modules.inputs.schemas import Category, InputCreateRequest, InputDose, Method, Unit

_DATA = Path(__file__).parents[3] / "migrations/public/versions/data/0106_medjool_inputs.json"
SEED = json.loads(_DATA.read_text(encoding="utf-8"))
DOCS = {"medjool_manual_1_7", "medjool_manual_1_7_annex_a", "medjool_manual_1_7_annex_b"}


def test_every_seeded_input_is_well_formed() -> None:
    codes = [i["code"] for i in SEED["inputs"]]
    assert len(codes) == len(set(codes))
    for item in SEED["inputs"]:
        assert item["category"] in get_args(Category)
        assert set(item["methods"]) <= set(get_args(Method))
        for dose in item["doses"]:
            InputDose(**{k: v for k, v in dose.items() if k != "section"})
            assert dose["section"], item["code"]
            assert dose["crop_path"] == "date_palm.medjool"
        for link in item["links"]:
            assert link["doc"] in DOCS
            assert link["confidence"] in {"high", "medium", "low", "expert_inference"}


def test_every_dose_cites_a_manual_row_and_every_input_a_source() -> None:
    for item in SEED["inputs"]:
        assert item["links"], item["code"]
    assert "13 #5" in SEED["organic_list"]


def test_dose_needs_a_number_and_other_needs_a_note() -> None:
    with pytest.raises(ValidationError):
        InputDose(unit="kg/plant")
    with pytest.raises(ValidationError):
        InputDose(value=Decimal(1), unit="other")
    with pytest.raises(ValidationError):
        InputDose(value_min=Decimal(5), value_max=Decimal(1), unit="kg/plant")
    assert InputDose(value=Decimal(1), unit="other", unit_note="trap per 100 m").unit == "other"
    assert "kg/plant" in get_args(Unit)


def test_code_is_snake_case() -> None:
    with pytest.raises(ValidationError):
        InputCreateRequest(code="Bad Code", name_en="x", category="bag_or_cover")


def test_every_input_has_its_arabic_name_from_the_manual() -> None:
    """D26: names come from the manual's Arabic edition, never a fresh translation."""
    missing = [i["code"] for i in SEED["inputs"] if not i.get("name_ar")]
    assert missing == []
