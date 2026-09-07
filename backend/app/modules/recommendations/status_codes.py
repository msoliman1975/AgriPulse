"""The platform's fixed status list for decision-tree leaves.

A leaf used to end in one of two kinds, ``recommendation`` or ``alert``, and
every branch that found nothing wrong ended in ``action_type: no_action``,
which wrote no row at all. On screen that looked the same as a tree excluded
by targeting and the same as a tree that never ran, so nobody could be told
"this block was checked and it is fine".

A leaf now declares one of four kinds — ``alert``, ``recommendation``,
``status``, ``no_action`` — and every evaluation resolves to one of the five
status codes here. The list is closed and ships with the platform: a tenant
cannot add a code or change a colour, because the codes are what the map
legend and the block health rule are built on.

`rank` orders two verdicts on one block. The highest rank wins, so a block
with one `issue` and six `good` reads as an issue. `na` is rank 0, so a tree
that had nothing to say never outranks a real answer.

See ``docs/proposals/decision-tree-status-verdicts.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

StatusCode = Literal["very_good", "good", "issue", "alert", "na"]

# The four leaf kinds. `no_action` used to be an `action_type`; it is a kind
# now, so the four cases a leaf can express are one closed list.
LeafKind = Literal["alert", "recommendation", "status", "no_action"]

LEAF_KINDS: tuple[str, ...] = get_args(LeafKind)


@dataclass(frozen=True, slots=True)
class StatusDefinition:
    """One entry of the platform status list."""

    code: str
    rank: int
    color: str
    label_en: str
    label_ar: str


STATUS_DEFINITIONS: tuple[StatusDefinition, ...] = (
    StatusDefinition("na", 0, "#9AA0A6", "Not applicable", "لا ينطبق"),
    StatusDefinition("very_good", 1, "#1B873F", "Very good", "ممتاز"),
    StatusDefinition("good", 2, "#6FBF4B", "Good", "جيد"),
    StatusDefinition("issue", 3, "#E8A33D", "Issue", "مشكلة"),
    StatusDefinition("alert", 4, "#D64545", "Alert", "إنذار"),
)

STATUS_BY_CODE: dict[str, StatusDefinition] = {d.code: d for d in STATUS_DEFINITIONS}

STATUS_CODES: tuple[str, ...] = tuple(d.code for d in STATUS_DEFINITIONS)

# What each leaf kind resolves to when the leaf does not name a status
# itself. Only a `status` leaf names one; the other three are fixed, so an
# alert always paints red and a recommendation always paints amber whatever
# the author does.
KIND_STATUS: dict[str, str] = {
    "alert": "alert",
    "recommendation": "issue",
    "status": "good",
    "no_action": "na",
}


def kind_of(outcome: object) -> str:
    """The leaf kind of one compiled ``outcome`` mapping.

    Both the loader and the engine read a leaf's kind through this function,
    so a leaf cannot validate as one kind and evaluate as another.

    Precedence, and why:

    1. An explicit ``kind: status`` or ``kind: alert`` wins. Those two are
       deliberate choices the author made.
    2. Otherwise ``action_type: no_action`` means the kind is ``no_action``.
       A recommendation that recommends no action is not a recommendation.
       Of the 63 no-action leaves shipped on 2026-09-07, 15 declare
       ``kind: recommendation`` next to ``action_type: no_action``; reading
       the declared kind would paint all 15 amber, which is the opposite of
       what they say. Eleven of the 15 read "within the sufficiency band" or
       "no meaningful rain", and four read "no reading has been ingested".
    3. Otherwise the declared kind, if it is one of the four.
    4. Otherwise ``recommendation``, which is what a leaf with no kind at
       all has always meant.
    """
    if not isinstance(outcome, dict):
        return "recommendation"
    declared = outcome.get("kind")
    if declared in ("status", "alert"):
        return str(declared)
    if outcome.get("action_type") == "no_action":
        return "no_action"
    if isinstance(declared, str) and declared in LEAF_KINDS:
        return declared
    return "recommendation"


def status_for(kind: str, declared: str | None = None) -> str:
    """Return the status code an evaluation of ``kind`` resolves to.

    ``declared`` is honoured for a ``status`` leaf only. An alert leaf that
    tried to declare `good` would break the colour of every alert, so the
    loader rejects it at publish time and this function ignores it.
    """
    if kind == "status" and declared in STATUS_BY_CODE:
        return declared
    return KIND_STATUS.get(kind, "na")


def rank_of(code: str) -> int:
    """Rank of ``code``. An unknown code ranks below every known one.

    A compiled tree can only carry a known code — the loader rejects the rest —
    so an unknown code here means a hand-edited row. It ranks last rather than
    raising, because a rollup over a whole farm must not fail on one row.
    """
    definition = STATUS_BY_CODE.get(code)
    return definition.rank if definition is not None else -1


def worst(codes: list[str]) -> str | None:
    """The winning status over one block's verdicts, or None for an empty list."""
    if not codes:
        return None
    return max(codes, key=rank_of)
