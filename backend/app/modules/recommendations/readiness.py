"""Tree readiness (decision D15): what a tree needs, and which blocks have it.

A folding tree reads data through value refs: block fields, crop fields,
scout signals, satellite indices, weather, water balance and the grid. A tree
whose data is missing does not fail; its conditions fail closed and it stays
silent. Nothing told the grower why. Readiness reads the requirements straight
from the compiled definition, so they can never drift from what the tree
actually tests, and checks each block against the same context the sweep
builds for it.

Pure: ``extract_requirements`` reads a compiled tree, ``assess`` reads a
``ConditionContext``. The service in ``folding_authoring`` loads the blocks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.shared.conditions import ConditionContext

Kind = Literal[
    "block_field",
    "crop_attribute",
    "reference",
    "heat_units",
    "signal",
    "index",
    "weather",
    "water_balance",
    "grid",
]
Status = Literal["ready", "partial", "not_ready"]

# Order shown to a person: what they set on the block first, then what they
# record, then what arrives on its own.
_KIND_ORDER: dict[str, int] = {
    "block_field": 0,
    "crop_attribute": 1,
    "reference": 1,
    "heat_units": 1,
    "signal": 2,
    "water_balance": 3,
    "index": 4,
    "grid": 5,
    "weather": 6,
}

# Weather of every flavour comes from one farm subscription, so the tree
# needs it once however many weather fields it reads.
_WEATHER_SOURCES = {"weather", "weather_index", "weather_risk"}


@dataclass(frozen=True, slots=True, order=True)
class Requirement:
    kind: Kind
    key: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "key": self.key}


def _refs(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("source"), str):
            yield node
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _requirement(ref: dict[str, Any]) -> Requirement | None:  # noqa: PLR0911
    source = ref["source"]
    if source == "block" and ref.get("field"):
        return Requirement("block_field", str(ref["field"]))
    if source == "crop_attribute" and ref.get("code"):
        return Requirement("crop_attribute", str(ref["code"]))
    if source == "reference" and ref.get("key"):
        return Requirement("reference", str(ref["key"]))
    if source == "heat_units":
        # One requirement whatever key is read: total, today and days since
        # start all come from the same crop setting and the same weather.
        return Requirement("heat_units", "total")
    if source == "signals" and ref.get("code"):
        return Requirement("signal", str(ref["code"]))
    if source == "indices" and ref.get("index_code"):
        return Requirement("index", str(ref["index_code"]))
    if source == "grid" and ref.get("index_code"):
        return Requirement("grid", str(ref["index_code"]))
    if source == "water_balance":
        return Requirement("water_balance", "balance")
    if source in _WEATHER_SOURCES:
        return Requirement("weather", "farm")
    # params, vars and findings are the tree's own state, not block data.
    return None


def extract_requirements(compiled: dict[str, Any]) -> list[Requirement]:
    """Every distinct piece of block data the tree's nodes read, ordered."""
    found = {
        req for ref in _refs(compiled.get("nodes") or {}) if (req := _requirement(ref)) is not None
    }
    return sorted(found, key=lambda r: (_KIND_ORDER[r.kind], r.key))


def _present(  # noqa: PLR0911 - one return per kind reads clearest
    req: Requirement, ctx: ConditionContext, has_grid: bool
) -> bool:
    if req.kind == "block_field":
        return ctx.block_attributes.get(req.key) is not None
    if req.kind == "crop_attribute":
        return ctx.crop_attributes.get(req.key) is not None
    if req.kind == "reference":
        # Set in the crop catalogue for this crop path, as a value or a range.
        entry = ctx.reference_values.get(req.key) or {}
        return any(v is not None for v in entry.values())
    if req.kind == "heat_units":
        # The crop sets a method, base and start, the start is known, and
        # the farm has at least one day with both temperatures since it.
        return ctx.heat_units.get("total") is not None
    if req.kind == "signal":
        # The snapshot holds a signal only when it applies to the block and
        # has a record. An answer older than its window keeps its time but
        # loses its value (D6), so a stale answer counts as missing, except
        # for "done" events, which are read through days_since_latest.
        signal = ctx.signals.get(req.key)
        if signal is None:
            return False
        return any(
            v is not None
            for v in (
                signal.value_numeric,
                signal.value_categorical,
                signal.value_event,
                signal.value_boolean,
                signal.days_since_latest,
            )
        )
    if req.kind == "index":
        index = ctx.indices.get(req.key)
        return index is not None and index.mean is not None
    if req.kind == "grid":
        # ctx.grid holds an entry only while an anomaly is open, so an empty
        # map does not mean "no grid". The block has what the tree needs when
        # it has an active grid configuration.
        return has_grid
    if req.kind == "water_balance":
        return ctx.water_balance is not None
    if req.kind == "weather":
        return ctx.weather is not None
    return False


def assess(
    requirements: list[Requirement], ctx: ConditionContext, *, has_grid: bool = False
) -> dict[str, Any]:
    """One block's status and what it lacks.

    Ready: every requirement is met. Not ready: none is. Partial: some are,
    so the tree runs but the checks that read the missing data stay silent.
    A tree that reads nothing from the block is ready everywhere.
    """
    missing = [req for req in requirements if not _present(req, ctx, has_grid)]
    if not missing:
        status: Status = "ready"
    elif len(missing) == len(requirements):
        status = "not_ready"
    else:
        status = "partial"
    return {
        "status": status,
        "met": len(requirements) - len(missing),
        "total": len(requirements),
        "missing": [req.as_dict() for req in missing],
    }


def summarise(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"ready": 0, "partial": 0, "not_ready": 0}
    for row in rows:
        counts[row["status"]] += 1
    return counts
