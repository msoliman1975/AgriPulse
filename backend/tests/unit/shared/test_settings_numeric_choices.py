"""The decision-tree cadence takes four values and nothing else.

The choices are enforced here, in the shared write-side validation, and
not by a CHECK constraint, because the value is JSONB and the same list
has to reach the browser. That makes this test the only thing standing
between a platform admin and a cadence of 1 hour, which the hourly Beat
tick cannot honour, or 0, which would enqueue a tenant on every tick.
"""

from __future__ import annotations

import pytest

from app.shared.settings.constraints import constraint_for
from app.shared.settings.errors import SettingValueError
from app.shared.settings.validation import validate_value

_KEY = "recommendations.sweep_cadence_hours"


@pytest.mark.parametrize("hours", [4, 8, 24, 168])
def test_the_four_offered_cadences_are_accepted(hours: int) -> None:
    validate_value(key=_KEY, value=hours, value_schema="number")


@pytest.mark.parametrize("hours", [0, 1, 3, 5, 12, 48, 169, -4])
def test_every_other_number_is_rejected(hours: int) -> None:
    with pytest.raises(SettingValueError):
        validate_value(key=_KEY, value=hours, value_schema="number")


@pytest.mark.parametrize("value", ["24", None, True, [24]])
def test_a_non_number_is_rejected(value: object) -> None:
    with pytest.raises(SettingValueError):
        validate_value(key=_KEY, value=value, value_schema="number")


def test_the_browser_is_told_the_same_four_values() -> None:
    """The select in the platform admin page is built from this, so the
    page cannot drift from what the write path accepts."""
    constraint = constraint_for(_KEY)
    assert constraint is not None
    assert constraint.as_dict()["numeric_choices"] == [4, 8, 24, 168]


def test_a_key_with_a_range_is_unaffected() -> None:
    """The new field must not change how the existing range keys behave."""
    validate_value(key="grid.anomaly_z_threshold", value=1.5, value_schema="number")
    with pytest.raises(SettingValueError):
        validate_value(key="grid.anomaly_z_threshold", value=99.0, value_schema="number")
