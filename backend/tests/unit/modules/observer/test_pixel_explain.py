"""The pixel inspector's rendering and exclusion logic.

The inspector's whole claim is that it cannot describe a calculation the
pipeline is not performing. Two things could break that claim without any
test failing elsewhere:

  * the formula-token map drifting from what the catalog actually writes, so
    a band name renders unsubstituted or, worse, substitutes the wrong band;
  * the exclusion reason naming a cause the pipeline never reached — telling
    an operator a pixel was cloud-masked when in fact it was outside the
    block.

Both are covered here. The maths itself is not re-tested: it is
`indices.computation`'s, and duplicating its assertions would just create a
second thing to keep in step.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.indices.computation import STANDARD_INDEX_CODES
from app.modules.observer.pixels import (
    FORMULA_TOKEN_TO_BAND,
    SCL_LABELS,
    _exclusion_reason,
    substitute_formula,
)

_MIGRATIONS = Path(__file__).resolve().parents[4] / "migrations" / "public" / "versions"


def _catalog_formulas() -> list[str]:
    """Every `formula_text` seeded into `public.indices_catalog`.

    Read from the migrations because that is where the strings actually live;
    a formula added in a future migration with a band token this module has
    never seen would otherwise render half-substituted in production and look
    like a data problem.
    """
    found: list[str] = []
    for path in sorted(_MIGRATIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        found += re.findall(r'"formula_text":\s*"([^"]+)"', source)
        # 0027 seeds ndmi inline in SQL rather than through a dict literal.
        found += re.findall(r"\$tag\$(\([^$]*?\))\$tag\$", source)
    return found


# ---- formula substitution --------------------------------------------------


def test_substitutes_every_band_token_with_its_value() -> None:
    rendered = substitute_formula(
        "(NIR - Red) / (NIR + Red)",
        {"nir": 0.3140, "red": 0.0871},
    )
    assert rendered == "(0.3140 - 0.0871) / (0.3140 + 0.0871)"


def test_rededge_is_not_split_into_red_plus_edge() -> None:
    """Token matching is longest-first for exactly this reason.

    A naive alternation would rewrite "RedEdge" as "<red-value>Edge" — a
    plausible-looking expression built from the wrong band.
    """
    rendered = substitute_formula(
        "(NIR - RedEdge) / (NIR + RedEdge)",
        {"nir": 0.3, "red_edge_1": 0.15, "red": 0.09},
    )
    assert rendered == "(0.3000 - 0.1500) / (0.3000 + 0.1500)"
    assert "Edge" not in rendered


def test_swir1_is_not_shortened_to_swir() -> None:
    rendered = substitute_formula("(NIR - SWIR1) / (NIR + SWIR1)", {"nir": 0.3, "swir1": 0.18})
    assert rendered == "(0.3000 - 0.1800) / (0.3000 + 0.1800)"


def test_returns_none_when_the_product_lacks_a_band_the_formula_needs() -> None:
    """PlanetScope has no SWIR, so NDMI cannot be rendered at all.

    Printing an expression with a band name still in it would read as a
    rendering bug rather than as "this product cannot compute this index".
    """
    assert substitute_formula("(NIR - SWIR1) / (NIR + SWIR1)", {"nir": 0.3}) is None


def test_a_present_but_unreadable_band_is_also_not_rendered() -> None:
    """A no-data band value is None, not 0.0 — and 0.0 would be a lie."""
    assert substitute_formula("(NIR - Red) / (NIR + Red)", {"nir": 0.3, "red": None}) is None


def test_every_catalog_formula_is_fully_substitutable() -> None:
    """No seeded formula may contain a token this module cannot resolve."""
    values = {band: 0.5 for band in FORMULA_TOKEN_TO_BAND.values()}
    unresolved: list[str] = []
    for formula in _catalog_formulas():
        rendered = substitute_formula(formula, values)
        assert rendered is not None, formula
        # Any surviving capital-letter run is a band name we failed to map.
        leftovers = re.findall(r"[A-Za-z]+", rendered)
        if leftovers:
            unresolved.append(f"{formula} -> {leftovers}")
    assert not unresolved, f"unmapped band tokens in catalog formulas: {unresolved}"


def test_catalog_formulas_were_actually_found() -> None:
    """Guards the guard: a regex that matches nothing passes vacuously."""
    formulas = _catalog_formulas()
    assert len(formulas) >= len(STANDARD_INDEX_CODES) - 1


# ---- exclusion reasons -----------------------------------------------------


def test_outside_the_aoi_outranks_a_mask_verdict() -> None:
    """Ordering matches how the pipeline actually drops pixels.

    Outside the AOI the pixel is never aggregated at all, so reporting "cloud
    shadow" for it would name a cause that was never reached — and send an
    operator looking at the weather rather than at the block boundary.
    """
    reason = _exclusion_reason(
        masked=True,
        mask_reason="SCL = 3 (cloud shadow)",
        inside_aoi=False,
        value=0.42,
    )
    assert reason == "outside the block boundary"


def test_a_masked_pixel_reports_the_scl_class_that_dropped_it() -> None:
    reason = _exclusion_reason(
        masked=True,
        mask_reason="SCL = 9 (cloud, high probability)",
        inside_aoi=True,
        value=0.42,
    )
    assert reason == "SCL = 9 (cloud, high probability)"


def test_a_non_finite_result_is_named_rather_than_shown_as_zero() -> None:
    reason = _exclusion_reason(masked=False, mask_reason=None, inside_aoi=True, value=None)
    assert reason is not None
    assert "divide-by-zero" in reason


def test_a_contributing_pixel_has_no_exclusion_reason() -> None:
    assert _exclusion_reason(masked=False, mask_reason=None, inside_aoi=True, value=0.5657) is None


# ---- SCL labels ------------------------------------------------------------


@pytest.mark.parametrize("code", [0, 1, 3, 8, 9, 10, 11])
def test_every_masked_scl_class_has_a_human_label(code: int) -> None:
    """A masked pixel must be able to say *why*, not just "masked"."""
    from app.modules.indices.computation import S2_SCL_MASKED_CLASSES

    assert code in S2_SCL_MASKED_CLASSES
    assert SCL_LABELS[code]


def test_scl_labels_cover_the_full_sentinel2_class_range() -> None:
    assert set(SCL_LABELS) == set(range(12))
