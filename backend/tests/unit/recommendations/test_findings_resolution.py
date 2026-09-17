"""The finding catalogue's precedence rule, tested without a database.

`resolve_findings` decides which clause reaches a farmer's card when the
platform and a tenant both define a code. Getting it backwards is not a
crash: it is a card in the wrong words, with no error anywhere, and the
only way anyone would notice is by reading a live card and recognising a
sentence they did not expect. So it is tested directly, against literal
dictionaries, rather than only through whatever happens to call it.
"""

from __future__ import annotations

import pytest

from app.modules.recommendations.findings import (
    PLATFORM_SOURCE,
    TENANT_SOURCE,
    FindingDef,
    UnknownFindingCodeError,
    require_findings,
    resolve_findings,
    shadowed_codes,
    worst_status,
)
from app.modules.recommendations.status_codes import STATUS_BY_CODE


def _row(
    code: str,
    *,
    status: str = "issue",
    clause_en: str | None = None,
    name_en: str | None = None,
) -> dict[str, str]:
    """One catalogue row, as either repository read returns it."""
    return {
        "code": code,
        "clause_en": clause_en or f"{code} is out of band",
        "clause_ar": f"ar:{code}",
        "name_en": name_en or code.title(),
        "name_ar": f"ar-name:{code}",
        "default_status": status,
    }


def test_platform_only_code_resolves_to_the_platform_row() -> None:
    resolved = resolve_findings([_row("ndvi_low")], [])

    assert set(resolved) == {"ndvi_low"}
    assert resolved["ndvi_low"].source == PLATFORM_SOURCE
    assert resolved["ndvi_low"].clause_en == "ndvi_low is out of band"


def test_tenant_only_code_resolves_to_the_tenant_row() -> None:
    resolved = resolve_findings([], [_row("salinity_high")])

    assert set(resolved) == {"salinity_high"}
    assert resolved["salinity_high"].source == TENANT_SOURCE


def test_platform_wins_when_both_define_the_same_code() -> None:
    """The one rule this module exists for.

    The catalogue's whole purpose is that `dry` means one thing across
    every tree and every tenant. A tenant row that could redefine it would
    break exactly that, so the platform row wins and the tenant row is not
    read at all — not merged field by field, not used as a fallback.
    """
    platform = [_row("dry", status="issue", clause_en="leaf water is low")]
    tenant = [_row("dry", status="alert", clause_en="the tenant's own wording")]

    resolved = resolve_findings(platform, tenant)

    assert resolved["dry"].source == PLATFORM_SOURCE
    assert resolved["dry"].clause_en == "leaf water is low"
    assert resolved["dry"].default_status == "issue"


def test_a_shadowed_tenant_row_does_not_add_a_second_entry() -> None:
    resolved = resolve_findings([_row("dry")], [_row("dry"), _row("own_code")])

    assert set(resolved) == {"dry", "own_code"}


def test_order_of_the_two_arguments_does_not_change_the_answer() -> None:
    """Precedence is by argument position, not by row order.

    Both catalogues are read in one pass each, so a tenant row that happens
    to be iterated first must still lose. Written out because the
    implementation is two `setdefault` loops and swapping them would pass
    every other test here.
    """
    platform = [_row("dry", clause_en="platform wording")]
    tenant = [_row("aaa_first"), _row("dry", clause_en="tenant wording")]

    resolved = resolve_findings(platform, tenant)

    assert resolved["dry"].clause_en == "platform wording"


def test_shadowed_codes_names_only_the_overlap() -> None:
    platform = [_row("dry"), _row("ndvi_low")]
    tenant = [_row("dry"), _row("own_code")]

    assert shadowed_codes(platform, tenant) == ("dry",)


def test_shadowed_codes_is_empty_when_nothing_overlaps() -> None:
    assert shadowed_codes([_row("dry")], [_row("own_code")]) == ()


def test_clause_and_name_fall_back_to_english() -> None:
    """A third language reads English rather than an empty fragment.

    A missing clause leaves a hole in a composed sentence, which reads as a
    bug rather than as a missing translation.
    """
    definition = FindingDef(
        code="dry",
        clause_en="leaf water is low",
        clause_ar="ماء الأوراق منخفض",
        name_en="Low leaf water",
        name_ar="نقص ماء الأوراق",
        default_status="issue",
        source=PLATFORM_SOURCE,
    )

    assert definition.clause("en") == "leaf water is low"
    assert definition.clause("ar") == "ماء الأوراق منخفض"
    assert definition.clause("pt") == "leaf water is low"
    assert definition.name("ar") == "نقص ماء الأوراق"
    assert definition.name("pt") == "Low leaf water"


def test_require_findings_returns_definitions_in_the_order_asked() -> None:
    resolved = resolve_findings([_row("dry"), _row("ndvi_low")], [])

    got = require_findings(["ndvi_low", "dry"], resolved)

    assert [d.code for d in got] == ["ndvi_low", "dry"]


def test_require_findings_names_every_missing_code_at_once() -> None:
    """One raise, listing all of them.

    An author fixing a tree's `registers` block wants every unknown code in
    one go, not to re-publish and be told about the next one.
    """
    resolved = resolve_findings([_row("dry")], [])

    with pytest.raises(UnknownFindingCodeError) as caught:
        require_findings(["nope", "dry", "zilch"], resolved)

    assert caught.value.codes == ("nope", "zilch")
    assert "nope" in str(caught.value)
    assert "zilch" in str(caught.value)


def test_worst_status_takes_the_highest_ranked_finding() -> None:
    resolved = resolve_findings(
        [_row("dry", status="issue"), _row("pest_high", status="alert")], []
    )

    assert worst_status(["dry", "pest_high"], resolved) == "alert"
    assert worst_status(["dry"], resolved) == "issue"


def test_worst_status_of_an_empty_set_is_very_good() -> None:
    """ "An empty set is healthy" (design section 5.5).

    `very_good`, not `na`: the tree ran, walked every check, and none of
    them fired. `na` means no tree had an opinion at all, which is a
    different thing and paints a different colour.
    """
    assert worst_status([], {}) == "very_good"


def test_a_combination_rule_status_overrides_the_findings() -> None:
    resolved = resolve_findings([_row("pest_high", status="alert")], [])

    assert worst_status(["pest_high"], resolved, override="good") == "good"


def test_an_unknown_code_is_ignored_rather_than_raising() -> None:
    """This runs per evaluation, long after the compiler refused a bad tree.

    Raising here would turn a catalogue row deactivated mid-sweep into a
    failed evaluation for every block in the tenant.
    """
    resolved = resolve_findings([_row("dry", status="issue")], [])

    assert worst_status(["dry", "gone_yesterday"], resolved) == "issue"
    assert worst_status(["gone_yesterday"], resolved) == "very_good"


def test_rank_order_comes_from_the_platform_status_list() -> None:
    """`worst_status` and a block's verdict roll-up must order the same way.

    Both mean "the worst wins" and both read `StatusDefinition.rank`. A
    second copy of the order here would let a fold and a map disagree about
    which of two findings is worse, with nothing failing.
    """
    rows = [_row(f"c_{code}", status=code) for code in STATUS_BY_CODE]
    resolved = resolve_findings(rows, [])
    codes = list(resolved)

    assert worst_status(codes, resolved) == "alert"
    assert worst_status([c for c in codes if c != "c_alert"], resolved) == "issue"
