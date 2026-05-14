"""Pure-function tests for the signals value-ref source."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.shared.conditions import ConditionContext, SignalEntry, evaluate
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import SignalsValueRef, parse_value_ref


def _ctx(signals: dict[str, SignalEntry] | None = None) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        signals=signals or {},
    )


def test_parse_signals_value_ref_default_key() -> None:
    ref = parse_value_ref({"source": "signals", "code": "soil_moisture"})
    assert isinstance(ref, SignalsValueRef)
    assert ref.code == "soil_moisture"
    assert ref.key == "value_numeric"


def test_parse_signals_value_ref_explicit_key() -> None:
    ref = parse_value_ref({"source": "signals", "code": "irrigation_event", "key": "value_event"})
    assert isinstance(ref, SignalsValueRef)
    assert ref.key == "value_event"


def test_parse_signals_rejects_missing_code() -> None:
    with pytest.raises(ConditionParseError, match="code"):
        parse_value_ref({"source": "signals"})


def test_parse_signals_rejects_unknown_key() -> None:
    with pytest.raises(ConditionParseError, match="key"):
        parse_value_ref({"source": "signals", "code": "soil_moisture", "key": "value_bogus"})


def test_predicate_matches_numeric_signal_value() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "signals", "code": "soil_moisture", "key": "value_numeric"},
        "right": 30,
    }
    matched, snapshot = evaluate(
        tree,
        _ctx({"soil_moisture": SignalEntry(time=datetime.now(UTC), value_numeric=Decimal("22.5"))}),
    )
    assert matched is True
    assert snapshot["values"]["signals.soil_moisture.value_numeric"] == "22.5"


def test_predicate_misses_when_no_observation_for_signal() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "signals", "code": "soil_moisture", "key": "value_numeric"},
        "right": 30,
    }
    matched, _ = evaluate(tree, _ctx())
    assert matched is False


def test_predicate_misses_when_wrong_value_kind_read() -> None:
    """If the predicate reads ``value_numeric`` but the signal is
    categorical, the resolver returns ``None`` and the comparison is
    permissive-False — same contract as a missing index."""
    tree = {
        "op": "eq",
        "left": {"source": "signals", "code": "pest_status", "key": "value_numeric"},
        "right": 1,
    }
    matched, _ = evaluate(
        tree,
        _ctx({"pest_status": SignalEntry(time=datetime.now(UTC), value_categorical="absent")}),
    )
    assert matched is False
