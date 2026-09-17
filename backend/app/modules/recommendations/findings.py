"""The finding catalogue, resolved. Platform first, then the tenant.

A folding decision tree registers *findings* as it walks and folds the set
it collected into one card at `stop`. A finding's code is all the tree
stores; the clause that reaches the card, the label that heads the group
and the health class it argues for all come from a catalogue row.

There are two catalogues. `public.decision_tree_findings` is the shared
vocabulary the platform ships. `tenant_*.decision_tree_findings` lets a
tenant authoring its own tree add a code without waiting for a platform
release. This module is the one place the two are merged.

**Why this module holds no session.** Resolution is the rule that decides
what a farmer reads, and it is three lines of precedence that are easy to
get subtly wrong — a shadowed tenant row silently winning is not a crash,
it is a card in the wrong words with no error anywhere. Keeping it as a
function over two row sequences means it is tested directly, against
literal dictionaries, with no database at all. The caller fetches; this
decides.

**Platform wins on a duplicate code.** Not the tenant. The catalogue
exists so `dry` means one thing across every tree and every tenant, and a
tenant that could redefine a platform code would break exactly that. A
tenant row whose code is also a platform code is kept and marked
`shadowed`, so the admin screen can explain why the tenant's clause is not
the one on the card, rather than leaving the author to guess.

**Inactive rows are dropped by the caller, not here.** `is_active` is a
column on both tables and both repository reads filter on it. This module
takes whatever rows it is given, so a caller that deliberately wants the
inactive ones — the admin list does — gets them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# The platform's closed status list, imported rather than re-spelled so a
# code added to `status_codes` cannot silently fail validation here.
from app.modules.recommendations.status_codes import STATUS_DEFINITIONS

# Which catalogue a resolved row came from. `platform` rows are shared;
# `tenant` rows belong to one schema and never leave it.
PLATFORM_SOURCE = "platform"
TENANT_SOURCE = "tenant"


class UnknownFindingCodeError(KeyError):
    """A tree registers a code that neither catalogue defines.

    Raised by `require_findings`, which the compiler uses: a tree that can
    register a code with no clause would publish and then produce a card
    with a gap in the sentence. Failing the publish is the only point at
    which anybody is still looking.
    """

    def __init__(self, codes: Iterable[str]) -> None:
        self.codes = tuple(sorted(set(codes)))
        joined = ", ".join(self.codes)
        super().__init__(
            f"No finding catalogue entry for: {joined}. "
            "Add it to the platform catalogue or to this tenant's own."
        )


@dataclass(frozen=True, slots=True)
class FindingDef:
    """One resolved catalogue row.

    The attribute names are the contract. Three other parts of this work
    declare a local `Protocol` with these names rather than importing this
    class, so renaming a field here breaks them silently at type-check
    time and loudly at run time. Add fields; do not rename them.
    """

    code: str
    clause_en: str
    clause_ar: str
    name_en: str
    name_ar: str
    default_status: str
    source: str

    def clause(self, language: str) -> str:
        """The clause in `language`, falling back to English.

        Arabic is the only other language the catalogue carries. A tenant
        on a third language reads English rather than an empty fragment,
        because a missing clause leaves a hole in a composed sentence that
        reads as a bug rather than as a missing translation.
        """
        if language == "ar":
            return self.clause_ar
        return self.clause_en

    def name(self, language: str) -> str:
        """The short group-header label in `language`, falling back to English."""
        if language == "ar":
            return self.name_ar
        return self.name_en


def _to_def(row: Mapping[str, Any], *, source: str) -> FindingDef:
    return FindingDef(
        code=str(row["code"]),
        clause_en=str(row["clause_en"]),
        clause_ar=str(row["clause_ar"]),
        name_en=str(row["name_en"]),
        name_ar=str(row["name_ar"]),
        default_status=str(row["default_status"]),
        source=source,
    )


def resolve_findings(
    platform_rows: Iterable[Mapping[str, Any]],
    tenant_rows: Iterable[Mapping[str, Any]],
) -> dict[str, FindingDef]:
    """Merge the two catalogues into one code-to-definition mapping.

    Platform wins on a duplicate code. A tenant row whose code is already
    a platform code contributes nothing to the result; `shadowed_codes`
    answers which ones those were.

    Both arguments are sequences of mappings — whatever the repository
    returns, as long as it carries the six catalogue columns. Rows are
    taken in order, so a duplicate *within* one catalogue keeps the first,
    which matters only for a caller assembling rows by hand: both tables
    have `code` as their primary key.
    """
    resolved: dict[str, FindingDef] = {}

    for row in platform_rows:
        definition = _to_def(row, source=PLATFORM_SOURCE)
        resolved.setdefault(definition.code, definition)

    for row in tenant_rows:
        definition = _to_def(row, source=TENANT_SOURCE)
        # `setdefault`, so a platform row already in place is not replaced.
        # This single line is the whole precedence rule.
        resolved.setdefault(definition.code, definition)

    return resolved


def shadowed_codes(
    platform_rows: Iterable[Mapping[str, Any]],
    tenant_rows: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Tenant codes the platform catalogue already defines, sorted.

    The admin screen flags these. Without it a tenant author edits a
    clause, sees no change on the card, and has nothing to read that
    explains it.
    """
    platform_codes = {str(row["code"]) for row in platform_rows}
    return tuple(sorted({str(row["code"]) for row in tenant_rows} & platform_codes))


def require_findings(
    codes: Iterable[str],
    catalogue: Mapping[str, FindingDef],
) -> tuple[FindingDef, ...]:
    """Every code in `codes`, resolved, or raise naming all the missing ones.

    Raises once with the full list rather than on the first miss: an author
    fixing a tree's `registers` block wants to see every unknown code in
    one go, not to re-publish and be told about the next one.
    """
    wanted = tuple(codes)
    missing = [code for code in wanted if code not in catalogue]
    if missing:
        raise UnknownFindingCodeError(missing)
    return tuple(catalogue[code] for code in wanted)


def worst_status(
    codes: Iterable[str],
    catalogue: Mapping[str, FindingDef],
    *,
    override: str | None = None,
) -> str:
    """The health class a set of findings argues for.

    "The worst status wins. An empty set is healthy" (design section 5.5).
    `very_good` is the value for an empty set, because the tree ran, walked
    every check, and none of them fired — that is the strongest thing this
    module can say, and it is not the same as `na`, which means no tree had
    an opinion at all.

    `override` is a matching combination rule's declared status. It wins
    outright when given: the rule is the author saying they know what this
    exact set means, which is the whole reason combination rules exist.

    An unknown code contributes nothing rather than raising. This runs at
    fold time, per evaluation, long after the compiler has already refused
    to publish a tree that registers an unknown code; raising here would
    turn a catalogue row deactivated mid-sweep into a failed evaluation for
    every block.
    """
    if override is not None:
        return override
    ranked = [_STATUS_RANK[catalogue[code].default_status] for code in codes if code in catalogue]
    if not ranked:
        return "very_good"
    return _STATUS_BY_RANK[max(ranked)]


# Rank is `StatusDefinition.rank`, read from the platform list rather than
# repeated here, so "the worst status wins" in a fold and "the highest rank
# wins" on a block's verdicts are the same ordering and cannot drift.
_STATUS_RANK: dict[str, int] = {d.code: d.rank for d in STATUS_DEFINITIONS}
_STATUS_BY_RANK: dict[int, str] = {d.rank: d.code for d in STATUS_DEFINITIONS}
