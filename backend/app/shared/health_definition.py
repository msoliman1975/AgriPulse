"""The bounded health definition, and the resolver that reads it.

Phase 2 of moving block health off NDVI thresholds. Pure functions with
no I/O and no callers yet: :mod:`app.shared.health` still holds the rule
that ships. This module is what replaces it.

Why a definition object at all
------------------------------
``classify_health`` hard-codes one rule for every crop on every farm.
NDVI break points of 0.40 and 0.55 are a land-cover description, not an
agronomic verdict: a healthy wide-spaced mango orchard on desert soil
averages under 0.40 for its whole life and reads Critical for ever. The
rule has to be per crop and per farm, so it becomes data.

It is deliberately NOT a second decision-tree engine. A farm admin picks
values inside a fixed schema. They cannot author conditions.

What the resolver treats as evidence
------------------------------------
Alerts written by decision-tree leaves. Nothing else decides the class.
The old rules engine was removed in tenant migrations 0025 and 0033, so
every alert already comes from a tree leaf with a synthesised
``rule_code`` of ``tree:<tree_code>:<leaf_node_id>``.

Silence is not health
---------------------
"No open alert" hides three different states:

  1. Trees ran and everything passed.
  2. Trees ran, but their conditions had no data. The engine branches to
     ``on_miss`` when a condition resolves to None, so a broken tree is
     quiet, not loud. An unknown operator does the same: it compiles,
     publishes and misses for ever.
  3. No tree applies to the block at all.

Only the first is health. So coverage and freshness gate the *healthy*
answer and nothing else. An open critical alert still reads Critical on
a stale or uncovered block: a real finding is never hidden behind
"unknown".

Order the resolver applies
--------------------------
  0. Any decision-tree verdict at all: worst
     status wins and nothing below is read.   -> critical / watch / healthy
  1. Counted alerts, worst class wins.        -> critical / watch
  2. Open recommendations at or above the
     confidence floor.                        -> watch
  3. No trace for this block, or a trace that
     errored.                                 -> unknown  (no_coverage)
  4. Every trace skipped: no tree applies.    -> definition's choice (no_tree)
  5. Last evaluation older than the limit.    -> unknown  (stale)
  6. Nothing found, and we know we looked.    -> healthy  (all_clear)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, get_args

from app.shared.health import Health

# Why the block ended up in the class it did. Rendered next to the class so
# "why is my block red" has an answer that is not a guess.
HealthReason = Literal[
    # From a decision-tree verdict, which is the primary source: every tree
    # leaves one, including the leaves that find nothing wrong.
    "verdict_alert",
    "verdict_issue",
    "verdict_good",
    "critical_alert",
    "warning_alert",
    "cell_share",
    "strong_recommendation",
    "no_coverage",
    "no_tree",
    "stale",
    "all_clear",
]

# Alert vocabulary. Declared here rather than imported: app.shared must not
# depend on app.modules. tests/unit/shared/test_health_definition.py asserts
# these stay equal to alerts.schemas.AlertSeverity and AlertStatus, so drift
# fails a test instead of dropping alerts on the floor with no error.
_SEVERITIES: frozenset[str] = frozenset({"info", "warning", "critical"})
_STATUSES: frozenset[str] = frozenset({"open", "acknowledged", "resolved", "snoozed"})

# A severity may map to a class that carries a verdict. "unknown" is not a
# verdict, it is the absence of one, so it cannot be the answer to an alert
# having fired.
_MAPPABLE: frozenset[str] = frozenset({"healthy", "watch", "critical"})

# Ranked worst-first. "unknown" sits outside the order on purpose: it never
# competes with a real verdict.
_RANK: dict[Health, int] = {"critical": 3, "watch": 2, "healthy": 1, "unknown": 0}


class HealthDefinitionError(ValueError):
    """A definition that cannot be honoured as written.

    Raised at parse time, never at resolve time. A definition that reaches
    `resolve_health` has already been checked. This is the loud failure the
    tree loader does not have: an unknown key here stops the load instead of
    becoming a branch that misses for ever with no log line.
    """


@dataclass(frozen=True, slots=True)
class HealthDefinition:
    """What turns evidence about a block into a health class.

    Every field is a value, not a rule. A farm admin choosing values here
    cannot express anything the resolver does not already know how to do.

    ``severity_map``
        Alert severity to the class one such alert argues for. Values are
        limited to healthy / watch / critical.
    ``counted_statuses``
        Alert statuses that count at all. A resolved alert is finished and
        colours nothing; an acknowledged one has been seen, not fixed.
    ``snoozed_as``
        Class a snoozed alert contributes, overriding ``severity_map``.
        None means a snoozed alert uses its severity like any other.
        Ignored when "snoozed" is not in ``counted_statuses``.
    ``cell_critical_share``
        Share of a block's grid cells that must carry a critical alert
        before the block itself reads critical. None means one critical
        cell is enough. Block-scoped alerts ignore this: they are already
        about the whole block.
    ``recommendation_floor``
        Confidence at or above which an open recommendation moves a block
        to watch. None means recommendations never move health, which is
        the default: a 0.5-confidence "consider scouting" should not turn
        a farm orange.
    ``stale_after_hours``
        Hours after the last evaluation past which a "nothing found"
        answer stops being believable.
    ``no_tree_coverage``
        Class for a block no tree applies to. "unknown" is honest.
        "healthy" is there for a tenant that would rather see green.

    ``severity_map`` is a plain dict, so this dataclass is frozen but not
    deeply immutable. Callers build a definition and read it; nothing in
    this module writes to the map.
    """

    version: int = 1
    severity_map: Mapping[str, Health] = field(
        default_factory=lambda: {"critical": "critical", "warning": "watch", "info": "healthy"}
    )
    counted_statuses: frozenset[str] = frozenset({"open", "acknowledged", "snoozed"})
    snoozed_as: Health | None = "watch"
    cell_critical_share: Decimal | None = None
    recommendation_floor: Decimal | None = None
    stale_after_hours: int = 48
    no_tree_coverage: Health = "unknown"

    def __post_init__(self) -> None:
        _validate(self)


@dataclass(frozen=True, slots=True)
class AlertEvidence:
    """One alert, reduced to what the resolver reads."""

    severity: str
    status: str
    # Grid cell the alert is scoped to. None means the alert is about the
    # whole block, which is what exempts it from the cell share test.
    cell_id: Any | None = None


@dataclass(frozen=True, slots=True)
class VerdictEvidence:
    """One decision-tree verdict, reduced to what the resolver reads.

    `cell_id` is None for a verdict about the whole block. A cell verdict is
    what `cell_critical_share` compares against the block's grid — and it is
    a far better source than the alert children that fed it before, because
    a tree writes one per cell it evaluated whether or not anything fired.
    """

    status_code: str
    cell_id: Any | None = None


@dataclass(frozen=True, slots=True)
class HealthInputs:
    """Everything known about one block at one instant.

    The trace counters come from the newest evaluation run's rows for this
    block: ``fired`` reached a leaf, ``clear`` evaluated to no action,
    ``skipped`` was excluded by targeting, ``error`` hit a malformed node.
    All four zero means the sweep did not reach this block at all.
    """

    alerts: tuple[AlertEvidence, ...] = ()
    # Decision-tree verdicts. When there is at least one, they decide the
    # block's class on their own and the alert path below is not consulted:
    # an alert leaf already writes a verdict, so reading both would count
    # one finding twice.
    verdicts: tuple[VerdictEvidence, ...] = ()
    # The newest verdict's evaluation time. Separate from the trace stamp
    # because the two can be hours apart on a block whose sweep half ran.
    verdict_last_evaluated_at: datetime | None = None
    total_cells: int = 0
    max_recommendation_confidence: Decimal | None = None
    traces_fired: int = 0
    traces_clear: int = 0
    traces_skipped: int = 0
    traces_error: int = 0
    last_evaluated_at: datetime | None = None


def resolve_health(
    definition: HealthDefinition,
    inputs: HealthInputs,
    *,
    now: datetime,
) -> tuple[Health, HealthReason]:
    """Return the block's class and the reason it landed there.

    `now` is passed in rather than read from the clock, so a caller
    resolving a whole farm gives every block the same instant.

    Verdicts decide on their own when the block has any. An alert leaf
    already writes a verdict, so consulting the alert path as well would
    count one finding twice — and the verdict is the better source, because
    a tree writes one whether or not anything fired. The alert path below
    stays for blocks whose sweep predates the verdict table.
    """
    if inputs.verdicts:
        return _from_verdicts(definition, inputs, now=now)

    alert_class, alert_reason = _from_alerts(definition, inputs)
    if alert_class is not None and alert_reason is not None:
        return alert_class, alert_reason

    if _recommendation_argues_for_watch(definition, inputs):
        return "watch", "strong_recommendation"

    # Past this point the evidence says "nothing found". Whether that is
    # health depends on whether anything actually looked.
    return _gate_the_healthy_answer(definition, inputs, now=now)


# ---------- Step 0: verdicts, when there are any -----------------------------


def _from_verdicts(  # noqa: PLR0911 - one return per status the block can land on
    definition: HealthDefinition, inputs: HealthInputs, *, now: datetime
) -> tuple[Health, HealthReason]:
    """The block's class from what its trees actually said.

    Worst wins, and the ranking is the status list's own: alert beats issue
    beats good beats very_good beats na. `na` argues for nothing — a tree
    that ran and had nothing to say is not evidence of health — so a block
    whose every verdict is `na` lands on the same answer as a block no tree
    covers.

    Freshness gates the healthy answer only, never a critical. A block whose
    sweep is three days old and whose trees found an alert is still red; it
    is the "everything is fine" claim that goes stale, because that claim is
    only as good as the last look.
    """
    codes = {v.status_code for v in inputs.verdicts}
    alert_cells = {
        v.cell_id for v in inputs.verdicts if v.status_code == "alert" and v.cell_id is not None
    }
    block_alert = any(v.status_code == "alert" and v.cell_id is None for v in inputs.verdicts)

    if block_alert:
        return "critical", "verdict_alert"
    if alert_cells:
        # The same test the alert path applies, on a source that can
        # actually reach it: a tree writes a verdict per cell it evaluated.
        if _share_is_met(definition, len(alert_cells), inputs.total_cells):
            return "critical", "verdict_alert"
        return "watch", "cell_share"
    if "issue" in codes:
        return "watch", "verdict_issue"
    if codes & {"good", "very_good"}:
        seen = inputs.verdict_last_evaluated_at
        if seen is None:
            return "unknown", "no_coverage"
        if now - seen > timedelta(hours=definition.stale_after_hours):
            return "unknown", "stale"
        return "healthy", "verdict_good"
    # Every verdict is `na`: the trees ran and none of them had anything to
    # say about this block. Same answer as no tree covering it at all.
    return definition.no_tree_coverage, "no_tree"


# ---------- Step 1: alerts ---------------------------------------------------


def _from_alerts(
    definition: HealthDefinition, inputs: HealthInputs
) -> tuple[Health | None, HealthReason | None]:
    """Worst class any counted alert argues for, or (None, None).

    (None, None) means no counted alert argues for watch or critical. An
    alert whose severity maps to "healthy" — info under the default map —
    is counted and then argues for nothing, which is why info is mapped
    rather than dropped.
    """
    worst: Health | None = None
    worst_reason: HealthReason | None = None
    # A cell-scoped critical held back by the share test still argues for
    # watch. Tracked separately so the reason can name the test that decided.
    share_held_back = False

    critical_cells: set[Any] = set()
    for a in inputs.alerts:
        if a.status not in definition.counted_statuses:
            continue
        klass = _class_for(definition, a)
        if klass == "critical" and a.cell_id is not None:
            critical_cells.add(a.cell_id)
            continue
        worst, worst_reason = _keep_worse(worst, worst_reason, klass, _reason_for(klass))

    if critical_cells:
        if _share_is_met(definition, len(critical_cells), inputs.total_cells):
            worst, worst_reason = _keep_worse(worst, worst_reason, "critical", "critical_alert")
        else:
            share_held_back = True
            worst, worst_reason = _keep_worse(worst, worst_reason, "watch", "cell_share")

    if worst is None or _RANK[worst] <= _RANK["healthy"]:
        return None, None
    # _keep_worse may have replaced the cell-share reason with a louder one;
    # only report cell_share when it is what actually set the class.
    if share_held_back and worst == "watch":
        return worst, "cell_share"
    return worst, worst_reason


def _class_for(definition: HealthDefinition, alert: AlertEvidence) -> Health:
    if alert.status == "snoozed" and definition.snoozed_as is not None:
        return definition.snoozed_as
    return definition.severity_map.get(alert.severity, "healthy")


def _reason_for(klass: Health) -> HealthReason:
    return "critical_alert" if klass == "critical" else "warning_alert"


def _keep_worse(
    current: Health | None,
    current_reason: HealthReason | None,
    candidate: Health,
    candidate_reason: HealthReason,
) -> tuple[Health | None, HealthReason | None]:
    if current is None or _RANK[candidate] > _RANK[current]:
        return candidate, candidate_reason
    return current, current_reason


def _share_is_met(definition: HealthDefinition, critical_cells: int, total_cells: int) -> bool:
    """True when enough of the block's cells are critical.

    No threshold means one cell is enough. A threshold with no known cell
    count also means one cell is enough: refusing to escalate because the
    denominator is missing would hide a real critical.
    """
    if definition.cell_critical_share is None:
        return True
    if total_cells <= 0:
        return True
    return Decimal(critical_cells) / Decimal(total_cells) >= definition.cell_critical_share


# ---------- Step 2: recommendations ------------------------------------------


def _recommendation_argues_for_watch(definition: HealthDefinition, inputs: HealthInputs) -> bool:
    if definition.recommendation_floor is None:
        return False
    if inputs.max_recommendation_confidence is None:
        return False
    return inputs.max_recommendation_confidence >= definition.recommendation_floor


# ---------- Step 3: is "nothing found" believable? ---------------------------


def _gate_the_healthy_answer(
    definition: HealthDefinition, inputs: HealthInputs, *, now: datetime
) -> tuple[Health, HealthReason]:
    traces = inputs.traces_fired + inputs.traces_clear + inputs.traces_skipped
    if inputs.traces_error > 0 or traces == 0:
        return "unknown", "no_coverage"

    if inputs.traces_fired == 0 and inputs.traces_clear == 0:
        # Every trace was skipped by targeting: no tree covers this block.
        return definition.no_tree_coverage, "no_tree"

    if inputs.last_evaluated_at is None:
        return "unknown", "no_coverage"
    if now - inputs.last_evaluated_at > timedelta(hours=definition.stale_after_hours):
        return "unknown", "stale"

    return "healthy", "all_clear"


# ---------- Parsing ----------------------------------------------------------

_FIELDS: frozenset[str] = frozenset(
    {
        "version",
        "severity_map",
        "counted_statuses",
        "snoozed_as",
        "cell_critical_share",
        "recommendation_floor",
        "stale_after_hours",
        "no_tree_coverage",
    }
)


def parse_definition(raw: Mapping[str, Any]) -> HealthDefinition:
    """Build a definition from authored data, refusing anything unclear.

    Unknown keys are an error, not a shrug. A misspelled key that falls back
    to a default is the same failure as a decision-tree condition with an
    unknown operator: it loads, it publishes, and it quietly means something
    else for the rest of its life.
    """
    unknown = sorted(set(raw) - _FIELDS)
    if unknown:
        raise HealthDefinitionError(
            f"unknown health-definition key(s) {unknown}; allowed keys are {sorted(_FIELDS)}"
        )

    kwargs: dict[str, Any] = {}
    if "version" in raw:
        kwargs["version"] = _as_int(raw["version"], "version")
    if "severity_map" in raw:
        kwargs["severity_map"] = dict(_as_mapping(raw["severity_map"], "severity_map"))
    if "counted_statuses" in raw:
        kwargs["counted_statuses"] = frozenset(
            _as_str_iterable(raw["counted_statuses"], "counted_statuses")
        )
    if "snoozed_as" in raw:
        kwargs["snoozed_as"] = raw["snoozed_as"]
    if "cell_critical_share" in raw:
        kwargs["cell_critical_share"] = _as_decimal(
            raw["cell_critical_share"], "cell_critical_share"
        )
    if "recommendation_floor" in raw:
        kwargs["recommendation_floor"] = _as_decimal(
            raw["recommendation_floor"], "recommendation_floor"
        )
    if "stale_after_hours" in raw:
        kwargs["stale_after_hours"] = _as_int(raw["stale_after_hours"], "stale_after_hours")
    if "no_tree_coverage" in raw:
        kwargs["no_tree_coverage"] = raw["no_tree_coverage"]

    return HealthDefinition(**kwargs)


def _validate(d: HealthDefinition) -> None:
    """Every check the definition must pass, in one place.

    Split into four helpers only to keep each one short. The order is the
    order a reader would ask the questions in.
    """
    if d.version < 1:
        raise HealthDefinitionError(f"version must be 1 or greater, got {d.version}")
    _validate_severity_map(d)
    _validate_statuses(d)
    _validate_thresholds(d)

    if d.no_tree_coverage not in ("unknown", "healthy"):
        raise HealthDefinitionError(
            f"no_tree_coverage is {d.no_tree_coverage!r}; expected 'unknown' or 'healthy'"
        )


def _validate_severity_map(d: HealthDefinition) -> None:
    if not d.severity_map:
        raise HealthDefinitionError("severity_map cannot be empty")
    for severity, klass in d.severity_map.items():
        if severity not in _SEVERITIES:
            raise HealthDefinitionError(
                f"severity_map key {severity!r} is not an alert severity; "
                f"expected one of {sorted(_SEVERITIES)}"
            )
        if klass not in _MAPPABLE:
            raise HealthDefinitionError(
                f"severity_map[{severity!r}] is {klass!r}; expected one of {sorted(_MAPPABLE)}"
            )
    # Every severity must be named. A map that omits one would fall back to
    # "healthy" on a severity the author never thought about.
    missing = sorted(_SEVERITIES - set(d.severity_map))
    if missing:
        raise HealthDefinitionError(
            f"severity_map must name every alert severity; missing {missing}"
        )


def _validate_statuses(d: HealthDefinition) -> None:
    unknown_statuses = sorted(set(d.counted_statuses) - _STATUSES)
    if unknown_statuses:
        raise HealthDefinitionError(
            f"counted_statuses has unknown status {unknown_statuses}; "
            f"expected a subset of {sorted(_STATUSES)}"
        )
    if "resolved" in d.counted_statuses:
        raise HealthDefinitionError(
            "counted_statuses cannot include 'resolved'; a resolved alert is finished"
        )
    if d.snoozed_as is not None and d.snoozed_as not in _MAPPABLE:
        raise HealthDefinitionError(
            f"snoozed_as is {d.snoozed_as!r}; expected null or one of {sorted(_MAPPABLE)}"
        )


def _validate_thresholds(d: HealthDefinition) -> None:
    if d.cell_critical_share is not None and not (Decimal(0) < d.cell_critical_share <= Decimal(1)):
        raise HealthDefinitionError(
            f"cell_critical_share must be greater than 0 and at most 1, "
            f"got {d.cell_critical_share}"
        )
    if d.recommendation_floor is not None and not (
        Decimal(0) <= d.recommendation_floor <= Decimal(1)
    ):
        raise HealthDefinitionError(
            f"recommendation_floor must be between 0 and 1, got {d.recommendation_floor}"
        )
    if d.stale_after_hours < 1:
        raise HealthDefinitionError(
            f"stale_after_hours must be 1 or greater, got {d.stale_after_hours}"
        )


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HealthDefinitionError(f"{name} must be a whole number, got {value!r}")
    return value


def _as_decimal(value: Any, name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ArithmeticError) as exc:
        raise HealthDefinitionError(f"{name} must be a number, got {value!r}") from exc


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HealthDefinitionError(f"{name} must be a mapping, got {value!r}")
    return value


def _as_str_iterable(value: Any, name: str) -> Iterable[str]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise HealthDefinitionError(f"{name} must be a list of strings, got {value!r}")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise HealthDefinitionError(f"{name} must be a list of strings, got {item!r}")
        out.append(item)
    return out


# What a tenant gets before anyone overrides anything. Phase 5 lets a
# knowledge-base package ship a per-crop default; Phase 6 lets a farm admin
# override that. Until then this is the whole resolution chain.
#
# Note on counted_statuses: the two live callers of the old classifier
# disagree today. The map counts open only; the insights scorecard counts
# open, acknowledged and snoozed. This default follows the scorecard, so
# switching the map over in Phase 4 makes some acknowledged alerts visible
# on the map that were not visible before. That is the intended direction:
# an acknowledged alert means somebody saw it, not that the block recovered.
#
# Defined here, at the end of the module, and not next to the class: this
# builds an instance at import time, and __post_init__ calls _validate.
PLATFORM_DEFAULT_DEFINITION = HealthDefinition()


# Enumerable vocabulary, so a caller does not import the private names.
HEALTH_CLASSES: tuple[str, ...] = get_args(Health)
HEALTH_REASONS: tuple[str, ...] = get_args(HealthReason)
