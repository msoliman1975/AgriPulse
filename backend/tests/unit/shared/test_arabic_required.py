"""D26: the shared "Arabic beside English" rule and its backward-compat side."""

from __future__ import annotations

import pytest

from app.shared.arabic_required import (
    ARABIC_REQUIRED_PROBLEM,
    ArabicRequiredError,
    is_blank,
    merged,
    missing_arabic,
    pair_needs_arabic,
    require_arabic,
)

PAIRS = (("name_en", "name_ar"), ("description_en", "description_ar"))


class TestIsBlank:
    @pytest.mark.parametrize("value", [None, "", "   ", "\n\t"])
    def test_blank(self, value: object) -> None:
        assert is_blank(value)

    @pytest.mark.parametrize("value", ["x", " نخيل ", 0, []])
    def test_not_blank(self, value: object) -> None:
        assert not is_blank(value)


class TestNewRecord:
    def test_english_without_arabic_is_missing(self) -> None:
        assert missing_arabic({"name_en": "Medjool"}, PAIRS) == [("name_en", "name_ar")]

    def test_whitespace_arabic_is_missing(self) -> None:
        assert missing_arabic({"name_en": "Medjool", "name_ar": "  "}, PAIRS) == [
            ("name_en", "name_ar")
        ]

    def test_both_filled_is_fine(self) -> None:
        assert missing_arabic({"name_en": "Medjool", "name_ar": "مجهول"}, PAIRS) == []

    def test_no_english_needs_no_arabic(self) -> None:
        assert missing_arabic({"name_en": "  ", "name_ar": None}, PAIRS) == []
        assert missing_arabic({"description_en": None}, PAIRS) == []

    def test_prefix_names_the_item(self) -> None:
        assert missing_arabic({"name_en": "x"}, PAIRS, prefix="activities[2].") == [
            ("activities[2].name_en", "activities[2].name_ar")
        ]


class TestExistingRecord:
    LEGACY = {"name_en": "Keitt", "name_ar": None, "description_en": "Late", "description_ar": ""}

    def test_untouched_legacy_record_is_fine(self) -> None:
        assert missing_arabic(dict(self.LEGACY), PAIRS, before=self.LEGACY) == []

    def test_unrelated_patch_on_legacy_record_is_fine(self) -> None:
        after = merged(self.LEGACY, {"is_active": False})
        assert missing_arabic(after, PAIRS, before=self.LEGACY) == []

    def test_changed_english_without_arabic_is_missing(self) -> None:
        after = merged(self.LEGACY, {"name_en": "Keitt mango"})
        assert missing_arabic(after, PAIRS, before=self.LEGACY) == [("name_en", "name_ar")]

    def test_whitespace_only_english_change_is_not_a_change(self) -> None:
        after = merged(self.LEGACY, {"name_en": " Keitt "})
        assert missing_arabic(after, PAIRS, before=self.LEGACY) == []

    def test_clearing_existing_arabic_is_missing(self) -> None:
        before = {"name_en": "Keitt", "name_ar": "كيت"}
        after = merged(before, {"name_ar": ""})
        assert missing_arabic(after, PAIRS, before=before) == [("name_en", "name_ar")]

    def test_newly_added_english_is_missing(self) -> None:
        before = {"name_en": "Keitt", "name_ar": "كيت", "description_en": None}
        after = merged(before, {"description_en": "Late season"})
        assert missing_arabic(after, PAIRS, before=before) == [("description_en", "description_ar")]


def test_pair_needs_arabic_matrix() -> None:
    assert pair_needs_arabic(en_after="a", ar_after=None, is_new=True)
    assert not pair_needs_arabic(en_after="a", ar_after=None, en_before="a", is_new=False)
    assert pair_needs_arabic(en_after="b", ar_after=None, en_before="a", is_new=False)


def test_require_arabic_raises_a_422_naming_each_field() -> None:
    with pytest.raises(ArabicRequiredError) as caught:
        require_arabic({"name_en": "a", "description_en": "b"}, PAIRS)
    err = caught.value
    assert err.status_code == 422
    assert err.type == ARABIC_REQUIRED_PROBLEM
    assert err.extras == {"missing_arabic": ["name_ar", "description_ar"]}
    assert "name_ar (Arabic for name_en)" in (err.detail or "")
    assert "description_ar (Arabic for description_en)" in (err.detail or "")


def test_require_arabic_passes_quietly() -> None:
    require_arabic({"name_en": "a", "name_ar": "أ"}, PAIRS)
