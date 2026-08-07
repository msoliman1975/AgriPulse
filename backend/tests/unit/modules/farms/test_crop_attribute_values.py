"""Unit tests for crop-attribute value coercion (pure, no DB).

Coercion returns typed Python objects — ``Decimal``, ``date``, ``list[str]``
— never a string standing in for one. Binding an ISO string through a
``CAST(:x AS date)`` is the bug that took the backfill console down (#331),
so the tests below pin the *types*, not just the values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.farms.crop_attributes import VALUE_COLUMN_BY_TYPE, coerce_value


@dataclass
class Def:
    code: str
    value_type: str
    value_min: object | None = None
    value_max: object | None = None
    text_max_length: int | None = None
    options: list[dict] = field(default_factory=list)


def _select(value_type: str = "single_select") -> Def:
    return Def(
        code="establishment_method",
        value_type=value_type,
        options=[{"code": "seed"}, {"code": "grafted_tree"}],
    )


# ---- absence --------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, ""])
def test_absent_values_coerce_to_none(raw) -> None:
    """An empty string from a form field is absence, not a zero-length value."""
    assert coerce_value(Def(code="x", value_type="text"), raw) is None


# ---- numerics -------------------------------------------------------------


def test_integer_returns_decimal_not_str() -> None:
    out = coerce_value(Def(code="age", value_type="integer"), "30")
    assert out == Decimal("30")
    assert isinstance(out, Decimal)


def test_integer_rejects_fractional() -> None:
    with pytest.raises(ValueError, match="whole number"):
        coerce_value(Def(code="age", value_type="integer"), 3.5)


def test_decimal_keeps_precision() -> None:
    assert coerce_value(Def(code="h", value_type="decimal"), "180.5") == Decimal("180.5")


def test_range_is_enforced_at_both_ends() -> None:
    d = Def(code="age", value_type="integer", value_min=0, value_max=600)
    with pytest.raises(ValueError, match="below the minimum"):
        coerce_value(d, -1)
    with pytest.raises(ValueError, match="above the maximum"):
        coerce_value(d, 601)
    assert coerce_value(d, 600) == Decimal("600")


def test_non_numeric_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="is not a number"):
        coerce_value(Def(code="age", value_type="integer"), "soon")


# ---- dates ----------------------------------------------------------------


def test_iso_string_becomes_a_date_object() -> None:
    out = coerce_value(Def(code="d", value_type="date"), "2023-02-18")
    assert out == date(2023, 2, 18)
    assert isinstance(out, date)
    assert not isinstance(out, datetime)


def test_datetime_is_narrowed_to_its_date() -> None:
    out = coerce_value(Def(code="d", value_type="date"), datetime(2023, 2, 18, 9, 14))
    assert out == date(2023, 2, 18)
    assert not isinstance(out, datetime)


def test_malformed_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="ISO date"):
        coerce_value(Def(code="d", value_type="date"), "18/02/2023")


# ---- text and boolean -----------------------------------------------------


def test_text_length_limit_defaults_and_overrides() -> None:
    assert coerce_value(Def(code="n", value_type="text"), "x" * 500) == "x" * 500
    with pytest.raises(ValueError, match="longer than 500"):
        coerce_value(Def(code="n", value_type="text"), "x" * 501)
    with pytest.raises(ValueError, match="longer than 10"):
        coerce_value(Def(code="n", value_type="text", text_max_length=10), "x" * 11)


def test_boolean_does_not_accept_truthy_strings() -> None:
    """`"false"` is truthy in Python; silently storing it as True would make a
    decision tree branch the wrong way."""
    with pytest.raises(ValueError, match="true or false"):
        coerce_value(Def(code="b", value_type="boolean"), "false")
    assert coerce_value(Def(code="b", value_type="boolean"), False) is False


# ---- selects --------------------------------------------------------------


def test_single_select_must_be_a_catalog_option() -> None:
    assert coerce_value(_select(), "grafted_tree") == "grafted_tree"
    with pytest.raises(ValueError, match="is not one of"):
        coerce_value(_select(), "airlayered")


def test_multi_select_dedupes_and_validates_every_member() -> None:
    d = _select("multi_select")
    assert coerce_value(d, ["seed", "seed", "grafted_tree"]) == ["seed", "grafted_tree"]
    with pytest.raises(ValueError, match="not options"):
        coerce_value(d, ["seed", "airlayered"])


def test_multi_select_empty_list_is_absence_not_an_empty_array() -> None:
    """The tenant migration's options_non_empty CHECK rejects an empty array;
    an empty selection has to become "no value" instead."""
    assert coerce_value(_select("multi_select"), []) is None


def test_multi_select_rejects_a_bare_string() -> None:
    with pytest.raises(ValueError, match="expected a list"):
        coerce_value(_select("multi_select"), "seed")


# ---- column mapping -------------------------------------------------------


def test_every_value_type_maps_to_a_column() -> None:
    """The write path, read path, report resolver and DT context all key off
    this one mapping; a missing entry would KeyError at save time."""
    from app.modules.farms.crop_attributes import VALUE_TYPES

    assert set(VALUE_COLUMN_BY_TYPE) == set(VALUE_TYPES)


def test_unknown_value_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown value_type"):
        coerce_value(Def(code="x", value_type="colour"), "red")
