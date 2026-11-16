"""Harvest record rules that need no database (build plan 3.5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.harvest.repository import WRITABLE
from app.modules.harvest.schemas import HarvestLotCreateRequest, HarvestLotUpdateRequest
from app.modules.harvest.service import revenue_of


def test_revenue_is_weight_times_price_rounded() -> None:
    assert revenue_of(Decimal("1250.50"), Decimal("12.3456")) == Decimal("15438.17")
    assert revenue_of(Decimal("10"), Decimal("0")) == Decimal("0.00")
    assert revenue_of(Decimal("10"), None) is None


@pytest.mark.parametrize(
    "body",
    [
        {"harvested_on": "2026-09-10", "weight_kg": "0"},
        {"harvested_on": "2026-09-10", "weight_kg": "-1"},
        {"harvested_on": "2026-09-10", "weight_kg": "10", "price_per_kg": "-0.5"},
        {"harvested_on": "2026-09-10", "weight_kg": "10", "currency": "USD"},
        {"harvested_on": "2026-09-10", "weight_kg": "10", "pick_no": 0},
    ],
)
def test_create_refuses_bad_values_and_unknown_fields(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HarvestLotCreateRequest.model_validate(body)


def test_blank_text_becomes_null() -> None:
    req = HarvestLotCreateRequest.model_validate(
        {"harvested_on": "2026-09-10", "weight_kg": "10", "label": "  ", "season_label": ""}
    )
    assert req.label is None
    assert req.season_label is None
    assert req.harvested_on == date(2026, 9, 10)


def test_update_cannot_null_required_fields_or_move_the_pick() -> None:
    with pytest.raises(ValidationError):
        HarvestLotUpdateRequest.model_validate({"weight_kg": None})
    with pytest.raises(ValidationError):
        HarvestLotUpdateRequest.model_validate({"block_id": "x"})
    # Price may be cleared: a pick sold later has no price yet.
    assert HarvestLotUpdateRequest.model_validate({"price_per_kg": None}).price_per_kg is None


def test_only_correctable_fields_are_writable() -> None:
    assert set(WRITABLE) == {
        "harvested_on",
        "weight_kg",
        "price_per_kg",
        "pick_no",
        "label",
        "label_ar",
        "notes_internal",
    }
