"""Unit tests for crop-attribute resolution and gating (pure, no DB).

These rules are shared by the assignment form, the report column resolver and
the decision-tree context loader. If they disagree, a block shows one set of
fields, the report exports another, and a tree branches on a third — with no
error anywhere. Hence the coverage here rather than only through the API.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.modules.farms.crop_attributes import (
    GATEABLE_VALUE_TYPES,
    RESERVED_ATTRIBUTE_CODES,
    gate_matches,
    is_required,
    is_visible,
    path_prefixes,
    resolve_definitions,
    validate_type_consistency,
    visible_definitions,
)


@dataclass
class Def:
    """Stand-in for the ORM row — resolve_definitions is duck-typed."""

    path: str
    code: str
    sort_order: int = 0
    is_active: bool = True
    value_type: str = "text"
    is_required: bool = False
    show_when: dict | None = None
    required_when: dict | None = None
    value_max: int | None = None


# ---- path walking ---------------------------------------------------------


def test_path_prefixes_walks_shallow_to_deep() -> None:
    assert path_prefixes("mango.alphonso.short") == [
        "mango",
        "mango.alphonso",
        "mango.alphonso.short",
    ]
    assert path_prefixes("mango") == ["mango"]
    assert path_prefixes("") == []


# ---- deepest-wins ---------------------------------------------------------


def test_deeper_definition_replaces_inherited_one() -> None:
    crop_level = Def(path="mango", code="transplant_height_cm", value_max=2000)
    strain_level = Def(path="mango.alphonso.short", code="transplant_height_cm", value_max=250)

    out = resolve_definitions([crop_level, strain_level], crop_path="mango.alphonso.short")

    assert [d.value_max for d in out.definitions] == [250]
    assert out.shadowed == [crop_level]


def test_deeper_definition_does_not_apply_to_a_sibling_path() -> None:
    crop_level = Def(path="mango", code="transplant_height_cm", value_max=2000)
    strain_level = Def(path="mango.alphonso.short", code="transplant_height_cm", value_max=250)

    out = resolve_definitions([crop_level, strain_level], crop_path="mango.sukkary")

    assert [d.value_max for d in out.definitions] == [2000]
    assert out.shadowed == []


def test_definitions_from_another_crop_are_ignored() -> None:
    out = resolve_definitions(
        [Def(path="potato", code="seed_material"), Def(path="mango", code="rootstock_type")],
        crop_path="mango.sukkary",
    )
    assert [d.code for d in out.definitions] == ["rootstock_type"]


def test_deeper_inactive_row_suppresses_an_inherited_attribute() -> None:
    """The suppression mechanism: a variety opts out of a crop-level field.

    The inactive row has to win the walk *before* being dropped, otherwise the
    crop-level definition survives and the opt-out silently does nothing.
    """
    out = resolve_definitions(
        [
            Def(path="mango", code="rootstock_type"),
            Def(path="mango.sukkary", code="rootstock_type", is_active=False),
        ],
        crop_path="mango.sukkary",
    )
    assert out.definitions == []


def test_include_inactive_keeps_suppressed_rows_for_the_authoring_view() -> None:
    out = resolve_definitions(
        [
            Def(path="mango", code="rootstock_type"),
            Def(path="mango.sukkary", code="rootstock_type", is_active=False),
        ],
        crop_path="mango.sukkary",
        include_inactive=True,
    )
    assert [d.is_active for d in out.definitions] == [False]


def test_ordering_is_sort_order_then_code() -> None:
    out = resolve_definitions(
        [
            Def(path="mango", code="zzz", sort_order=1),
            Def(path="mango", code="aaa", sort_order=2),
            Def(path="mango", code="bbb", sort_order=2),
        ],
        crop_path="mango",
    )
    assert [d.code for d in out.definitions] == ["zzz", "aaa", "bbb"]


def test_rows_supplied_deep_first_still_resolve_to_the_deepest() -> None:
    """Callers order by (sort_order, code), not by path depth."""
    deep = Def(path="mango.sukkary", code="rootstock_type", value_max=1)
    shallow = Def(path="mango", code="rootstock_type", value_max=2)

    out = resolve_definitions([deep, shallow], crop_path="mango.sukkary")

    assert [d.value_max for d in out.definitions] == [1]
    assert out.shadowed == [shallow]


# ---- gating ---------------------------------------------------------------


def test_gate_in_and_eq() -> None:
    assert gate_matches({"code": "m", "in": ["grafted_tree"]}, {"m": "grafted_tree"}) is True
    assert gate_matches({"code": "m", "in": ["grafted_tree"]}, {"m": "seed"}) is False
    assert gate_matches({"code": "m", "eq": True}, {"m": True}) is True
    assert gate_matches({"code": "m", "eq": True}, {"m": False}) is False


def test_gate_on_an_unset_target_is_closed() -> None:
    """Fail closed: an unanswered establishment method must not reveal the
    transplant fields, or a half-filled form looks complete."""
    assert gate_matches({"code": "m", "in": ["a"]}, {}) is False
    assert gate_matches(None, {"m": "a"}) is False


def test_gate_against_a_multi_select_target_matches_any_member() -> None:
    assert gate_matches({"code": "t", "in": ["insecticide"]}, {"t": ["fungicide_dust"]}) is False
    assert (
        gate_matches({"code": "t", "in": ["insecticide"]}, {"t": ["fungicide_dust", "insecticide"]})
        is True
    )


def test_absent_show_when_means_always_visible_absent_required_when_means_optional() -> None:
    """The two defaults are deliberately opposite; conflating them makes every
    ungated field mandatory."""
    plain = Def(path="mango", code="nursery_source")
    assert is_visible(plain, {}) is True
    assert is_required(plain, {}) is False


def test_required_when_opens_with_its_gate() -> None:
    d = Def(
        path="mango",
        code="transplant_date",
        show_when={"code": "establishment_method", "in": ["grafted_tree"]},
        required_when={"code": "establishment_method", "in": ["grafted_tree"]},
    )
    assert is_visible(d, {"establishment_method": "seed"}) is False
    assert is_required(d, {"establishment_method": "seed"}) is False
    assert is_visible(d, {"establishment_method": "grafted_tree"}) is True
    assert is_required(d, {"establishment_method": "grafted_tree"}) is True


def test_unconditionally_required_ignores_the_gate() -> None:
    assert is_required(Def(path="mango", code="m", is_required=True), {}) is True


def test_visible_definitions_filters_the_set() -> None:
    method = Def(path="mango", code="establishment_method", sort_order=1)
    date_field = Def(
        path="mango",
        code="transplant_date",
        sort_order=2,
        show_when={"code": "establishment_method", "in": ["grafted_tree"]},
    )
    assert [d.code for d in visible_definitions([method, date_field], {})] == [
        "establishment_method"
    ]
    assert [
        d.code
        for d in visible_definitions([method, date_field], {"establishment_method": "grafted_tree"})
    ] == ["establishment_method", "transplant_date"]


# ---- reserved codes -------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["growth_stage", "canopy_size_class", "planting_date", "crop_path", "soil_texture"],
)
def test_first_class_block_fields_are_reserved(code: str) -> None:
    """Shadowing one of these puts two same-named entries in the decision-tree
    condition builder, one of which never resolves."""
    assert code in RESERVED_ATTRIBUTE_CODES


def test_establishment_codes_are_not_reserved() -> None:
    for code in ("establishment_method", "transplant_date", "age_at_transplant_months"):
        assert code not in RESERVED_ATTRIBUTE_CODES


def test_only_select_and_boolean_can_gate() -> None:
    assert {"single_select", "boolean"} == GATEABLE_VALUE_TYPES


# ---- type consistency -----------------------------------------------------


def test_select_requires_options_and_non_select_forbids_them() -> None:
    with pytest.raises(ValueError, match="non-empty 'options'"):
        validate_type_consistency(value_type="single_select", options=None)
    with pytest.raises(ValueError, match="only valid for select types"):
        validate_type_consistency(value_type="text", options=[{"code": "a"}])
    validate_type_consistency(value_type="single_select", options=[{"code": "a"}])


def test_duplicate_option_codes_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        validate_type_consistency(
            value_type="single_select", options=[{"code": "a"}, {"code": "a"}]
        )


def test_numeric_facets_are_numeric_only() -> None:
    with pytest.raises(ValueError, match="only valid for"):
        validate_type_consistency(value_type="text", value_min=1)
    with pytest.raises(ValueError, match="only valid for"):
        validate_type_consistency(value_type="date", unit_en="days", unit_ar="يوم")
    validate_type_consistency(value_type="integer", value_min=0, value_max=600)


def test_inverted_range_rejected() -> None:
    with pytest.raises(ValueError, match="value_min must be <= value_max"):
        validate_type_consistency(value_type="integer", value_min=10, value_max=1)


def test_integer_cannot_declare_decimal_places() -> None:
    with pytest.raises(ValueError, match="decimal_places"):
        validate_type_consistency(value_type="integer", decimal_places=2)


def test_text_max_length_is_text_only() -> None:
    with pytest.raises(ValueError, match="text_max_length"):
        validate_type_consistency(value_type="integer", text_max_length=10)
    validate_type_consistency(value_type="text", text_max_length=120)


def test_units_must_be_bilingual() -> None:
    """A unit in one language only is worse than none: the Arabic form drops
    it silently and the number renders bare."""
    with pytest.raises(ValueError, match="unit_en and unit_ar"):
        validate_type_consistency(value_type="integer", unit_en="months")
    validate_type_consistency(value_type="integer", unit_en="months", unit_ar="شهر")


def test_unknown_value_type_rejected() -> None:
    with pytest.raises(ValueError, match="unknown value_type"):
        validate_type_consistency(value_type="colour")
