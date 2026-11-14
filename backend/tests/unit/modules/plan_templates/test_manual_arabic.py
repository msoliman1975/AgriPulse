"""D26 on operation manuals, and Arabic notes copied onto applied plans."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any
from uuid import uuid4

from app.modules.plan_templates.allocation import resolve_allocation
from app.modules.plan_templates.apply import resolve_schedule
from app.modules.plan_templates.arabic import missing_manual_arabic


def _activity(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": "a_spray",
        "activity_type": "spraying",
        "title": "Copper spray",
        "title_ar": "رش النحاس",
        "notes": "Before rain",
        "notes_ar": "قبل المطر",
        "product_name": "Copper oxychloride",
        "product_name_ar": "أوكسي كلوريد النحاس",
        "dosage": "2.5 g/L",
        "dosage_ar": "2.5 غ/لتر",
    }
    body.update(over)
    return body


def _manual(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": "mango_keitt",
        "name": "Keitt manual",
        "name_ar": "دليل كيت",
        "description": None,
        "description_ar": None,
        "milestones": [{"code": "m1", "name": "Flowering", "name_ar": "الإزهار"}],
        "activities": [_activity()],
    }
    body.update(over)
    return body


def _legacy() -> dict[str, Any]:
    """A seeded manual with English-only product and notes."""
    return _manual(
        activities=[
            _activity(notes_ar=None, product_name_ar=None, dosage_ar=None),
        ]
    )


class TestMissingManualArabic:
    def test_complete_new_manual_passes(self) -> None:
        assert missing_manual_arabic(_manual(), None) == []

    def test_new_activity_without_arabic_names_each_field(self) -> None:
        payload = _manual(
            activities=[_activity(code=None, title_ar=None, notes_ar="", dosage_ar=None)]
        )
        assert [ar for _en, ar in missing_manual_arabic(payload, None)] == [
            "activities[1].title_ar",
            "activities[1].notes_ar",
            "activities[1].dosage_ar",
        ]

    def test_manual_name_and_milestones_are_not_checked_yet(self) -> None:
        payload = _manual(
            name_ar=None,
            description="Keitt season",
            milestones=[{"code": "m1", "name": "Flowering", "name_ar": None}],
        )
        assert missing_manual_arabic(payload, None) == []

    def test_resaving_untouched_legacy_manual_passes(self) -> None:
        legacy = _legacy()
        assert missing_manual_arabic(copy.deepcopy(legacy), legacy) == []

    def test_reordering_legacy_activity_passes(self) -> None:
        legacy = _legacy()
        payload = copy.deepcopy(legacy)
        payload["activities"][0]["offset_days"] = 14
        payload["activities"].insert(0, _activity(code="a_new"))
        assert missing_manual_arabic(payload, legacy) == []

    def test_changed_legacy_product_needs_arabic(self) -> None:
        legacy = _legacy()
        payload = copy.deepcopy(legacy)
        payload["activities"][0]["product_name"] = "Copper hydroxide"
        assert [ar for _en, ar in missing_manual_arabic(payload, legacy)] == [
            "activities[1].product_name_ar"
        ]

    def test_new_activity_in_legacy_manual_needs_arabic(self) -> None:
        legacy = _legacy()
        payload = copy.deepcopy(legacy)
        payload["activities"].append(_activity(code=None, notes_ar=None))
        assert [ar for _en, ar in missing_manual_arabic(payload, legacy)] == [
            "activities[2].notes_ar"
        ]


def _resolvable(**over: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "code": "a_spray",
        "activity_type": "spraying",
        "anchor": "start",
        "offset_days": 0,
        "notes": "Before rain",
        "notes_ar": "قبل المطر",
        **over,
    }


class TestNotesArCopiedOnApply:
    def test_resolve_schedule_carries_notes_ar(self) -> None:
        resolved, _ = resolve_schedule(
            activities=[_resolvable()],
            milestones=[],
            stages=None,
            block_start_date=date(2026, 3, 1),
            planting_date=None,
            is_perennial=True,
            season_year=2026,
        )
        assert resolved[0].notes_ar == "قبل المطر"

    def _allocate(self, edits: dict[str, Any]) -> Any:
        out, _ = resolve_allocation(
            activities=[_resolvable()],
            milestones=[],
            stages=None,
            block_start_date=date(2026, 3, 1),
            planting_date=None,
            is_perennial=True,
            season_year=2026,
            excluded_codes=set(),
            activity_edits={"a_spray": edits} if edits else {},
            custom_activities=[],
            overrides={},
        )
        return out[0]

    def test_allocation_keeps_manual_notes_ar(self) -> None:
        assert self._allocate({}).notes_ar == "قبل المطر"

    def test_allocation_uses_the_farms_arabic_notes(self) -> None:
        assert self._allocate({"notes_ar": "ملاحظة المزرعة"}).notes_ar == "ملاحظة المزرعة"

    def test_rewriting_only_english_notes_drops_stale_arabic(self) -> None:
        row = self._allocate({"notes": "Our own note"})
        assert row.notes == "Our own note"
        assert row.notes_ar is None
