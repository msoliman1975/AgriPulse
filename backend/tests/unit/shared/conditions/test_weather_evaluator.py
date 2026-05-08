"""Pure-function tests for the weather value-ref source.

The loader (``app.modules.weather.snapshot.load_snapshot``) is integration-
tested via the alerts/recommendations end-to-end paths; these tests
focus on the parser + resolver behaviour against a hand-built
``WeatherSnapshot``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.shared.conditions import ConditionContext, WeatherSnapshot, evaluate
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import WeatherValueRef, parse_value_ref


def _ctx(
    *,
    forecast_24h: dict[str, Decimal | None] | None = None,
    forecast_72h: dict[str, Decimal | None] | None = None,
    derived_today: dict[str, Decimal | None] | None = None,
    latest_observation: dict[str, Decimal | None] | None = None,
) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        weather=WeatherSnapshot(
            latest_observation=latest_observation,
            forecast_24h=forecast_24h,
            forecast_72h=forecast_72h,
            derived_today=derived_today,
        ),
    )


# ---- value-ref parsing ----------------------------------------------------


def test_parse_weather_value_ref() -> None:
    ref = parse_value_ref(
        {"source": "weather", "scope": "forecast_24h", "field": "precipitation_mm_total"}
    )
    assert isinstance(ref, WeatherValueRef)
    assert ref.scope == "forecast_24h"
    assert ref.field == "precipitation_mm_total"


def test_parse_weather_rejects_unknown_scope() -> None:
    with pytest.raises(ConditionParseError, match="scope"):
        parse_value_ref(
            {"source": "weather", "scope": "next_year", "field": "precipitation_mm_total"}
        )


def test_parse_weather_rejects_missing_field() -> None:
    with pytest.raises(ConditionParseError, match="field"):
        parse_value_ref({"source": "weather", "scope": "forecast_24h"})


# ---- resolver / evaluator integration -------------------------------------


def test_predicate_matches_when_forecast_rain_above_threshold() -> None:
    tree = {
        "op": "ge",
        "left": {
            "source": "weather",
            "scope": "forecast_24h",
            "field": "precipitation_mm_total",
        },
        "right": 5,
    }
    matched, snapshot = evaluate(
        tree, _ctx(forecast_24h={"precipitation_mm_total": Decimal("12.5")})
    )
    assert matched is True
    assert snapshot["values"]["weather.forecast_24h.precipitation_mm_total"] == "12.5"


def test_predicate_misses_when_no_weather_loaded() -> None:
    """A predicate referencing weather must return False (not raise) when
    the service didn't populate ``ConditionContext.weather`` — same
    permissive-on-missing-data contract as indices."""
    tree = {
        "op": "lt",
        "left": {"source": "weather", "scope": "forecast_24h", "field": "air_temp_c_max"},
        "right": 10,
    }
    matched, _ = evaluate(tree, ConditionContext(block_id="b1"))
    assert matched is False


def test_predicate_misses_when_scope_present_but_field_unknown() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "weather", "scope": "forecast_24h", "field": "totally_made_up"},
        "right": 1,
    }
    matched, snapshot = evaluate(
        tree, _ctx(forecast_24h={"precipitation_mm_total": Decimal("0")})
    )
    assert matched is False
    assert snapshot["values"]["weather.forecast_24h.totally_made_up"] is None


def test_combined_indices_plus_weather_tree() -> None:
    """The whole point of weather wiring: a single tree spans both
    sources. Realistic shape: NDVI dropping AND no rain in forecast →
    fire."""
    from datetime import UTC, datetime

    from app.shared.conditions.context import IndicesEntry

    ctx = ConditionContext(
        block_id="b1",
        crop_category="vegetables",
        indices={
            "ndvi": IndicesEntry(
                time=datetime.now(UTC),
                mean=Decimal("0.4"),
                baseline_deviation=Decimal("-1.2"),
            )
        },
        weather=WeatherSnapshot(forecast_72h={"precipitation_mm_total": Decimal("0.5")}),
    )
    tree = {
        "all_of": [
            {
                "op": "lt",
                "left": {
                    "source": "indices",
                    "index_code": "ndvi",
                    "key": "baseline_deviation",
                },
                "right": -0.5,
            },
            {
                "op": "lt",
                "left": {
                    "source": "weather",
                    "scope": "forecast_72h",
                    "field": "precipitation_mm_total",
                },
                "right": 2,
            },
        ]
    }
    matched, _ = evaluate(tree, ctx)
    assert matched is True


def test_derived_today_lookup() -> None:
    tree = {
        "op": "ge",
        "left": {
            "source": "weather",
            "scope": "derived_today",
            "field": "gdd_cumulative_base10_season",
        },
        "right": 500,
    }
    matched, _ = evaluate(
        tree,
        _ctx(derived_today={"gdd_cumulative_base10_season": Decimal("823.4")}),
    )
    assert matched is True
