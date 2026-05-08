"""Shared condition language for alerts (and, later, recommendations).

A condition tree is a JSON document stored on a rule (e.g.
``default_rules.conditions["tree"]``). The evaluator is a sync pure
function: it takes a parsed tree and a pre-loaded ``ConditionContext``
and returns ``(matched, snapshot)``. The snapshot records every value
ref that was resolved during evaluation, so downstream readers can audit
what triggered the rule.

Design choices worth knowing:

  * **Pure-function, sync.** Drops into the existing alerts predicate
    dispatcher unchanged. Loading data is the service's job, not the
    evaluator's.
  * **Context-bag model.** New data sources (weather, signals — Slice 5)
    arrive as new fields on ``ConditionContext``. The evaluator only
    knows how to read from them; the loader is per-consumer (alerts
    service today, recommendations later).
  * **Permissive on missing data.** A value ref that resolves to ``None``
    short-circuits the comparison to ``False`` rather than raising, so
    a stale rule body or a not-yet-populated source doesn't crash a
    sweep. This mirrors the existing predicates' behavior.
"""

from app.shared.conditions.context import (
    ConditionContext,
    SignalEntry,
    WeatherSnapshot,
)
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.evaluator import evaluate

__all__ = [
    "ConditionContext",
    "ConditionParseError",
    "SignalEntry",
    "WeatherSnapshot",
    "evaluate",
]
