"""D20: template activities carry an input and a structured dose into plans."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.plan_templates.apply import format_dose, resolve_schedule
from app.modules.plan_templates.schemas import PlanTemplateActivityInput


def test_format_dose_reads_like_the_catalogue() -> None:
    assert format_dose(Decimal("100"), Decimal("150"), "g/plant") == "100-150 g/plant"
    assert format_dose(Decimal("50.0"), None, "kg/plant") == "50 kg/plant"
    assert format_dose(Decimal("0.75"), None, "%") == "0.75 %"
    assert format_dose(None, None, "kg/plant") is None
    assert format_dose(Decimal("5"), None, None) is None


def test_resolved_activity_keeps_the_input_and_dose() -> None:
    input_id = uuid4()
    act = {
        "id": uuid4(),
        "activity_type": "fertilizing",
        "anchor": "start",
        "milestone_id": None,
        "stage_code": None,
        "offset_days": 0,
        "duration_days": 1,
        "product_name": None,
        "dosage": None,
        "notes": None,
        "start_time": None,
        "input_id": input_id,
        "dose_value": Decimal("100"),
        "dose_value_max": Decimal("150"),
        "dose_unit": "g/plant",
    }
    resolved, _ = resolve_schedule(
        activities=[act],
        milestones=[],
        stages=None,
        block_start_date=date(2026, 3, 1),
        planting_date=None,
        is_perennial=False,
        season_year=2026,
    )
    assert resolved[0].input_id == input_id
    assert resolved[0].dose_unit == "g/plant"


def test_a_dose_needs_an_amount_and_a_unit() -> None:
    with pytest.raises(ValidationError):
        PlanTemplateActivityInput(activity_type="fertilizing", dose_value=Decimal(5))
    with pytest.raises(ValidationError):
        PlanTemplateActivityInput(activity_type="fertilizing", dose_unit="kg/plant")
    with pytest.raises(ValidationError):
        PlanTemplateActivityInput(
            activity_type="fertilizing",
            dose_value=Decimal(9),
            dose_value_max=Decimal(5),
            dose_unit="kg/plant",
        )
    ok = PlanTemplateActivityInput(
        activity_type="fertilizing", dose_value=Decimal(50), dose_unit="kg/plant"
    )
    assert ok.dose_unit == "kg/plant"
