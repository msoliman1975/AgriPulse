"""The pixel inspector must read the quality band with its own product's rules.

Sentinel-2's SCL is a class enum; Landsat Collection-2's QA_PIXEL is a
bitmask. They occupy the same trailing band of the raw COG, so nothing
about the raster distinguishes them — only the product code does. The
inspector read every scene as Sentinel-2, which produced two wrong
answers on thermal at once:

  * the wrong verdict. `scl_cloud_mask` tests membership in
    `(0, 1, 3, 8, 9, 10, 11)`. A clear Landsat pixel is 21824 — not in
    that set, so "not masked", which happens to be right by accident. A
    *cloudy* one is 22280, also not in the set, so also "not masked",
    which is wrong. The whole point of the bitmask is that the failure
    flags live in bits 0-5, and a membership test cannot see them.

  * the wrong words. 21824 rendered as "SCL = 21824 (unknown class)",
    and a fill pixel (bit 0 set) as "saturated or defective" — one
    product's vocabulary printed over another's numbers.

`quality_band_mask` in `indices.computation` is the pipeline's own
dispatcher and stays the authority on the verdict; these tests pin the
dispatch and the labels the inspector adds around it.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from app.modules.indices.computation import (
    LANDSAT_QA_MASKED_BITS,
    PRODUCT_INDEX_CODES,
    PRODUCT_MASK_RULESETS,
)
from app.modules.observer.pixels import (
    QA_PIXEL_BIT_LABELS,
    SCL_LABELS,
    _qa_pixel_label,
    _read_quality_band,
)

_THERMAL = "landsat_c2_l2_st"
_OPTICAL = "s2_l2a"

# Real Collection-2 QA_PIXEL values. 21824 = bits 6 (clear) + 8,9,14 set;
# 22280 = bits 3 (cloud) + 6 clear-of-others confidence pairs; 1 = fill.
_QA_CLEAR = 21824
_QA_CLOUD = 22280
_QA_FILL = 1


def test_a_clear_landsat_pixel_is_not_masked() -> None:
    """Bit 6 means CLEAR — the polarity trap.

    Testing "is any bit set" would mask every good pixel on the scene.
    """
    value, label, masked, reason = _read_quality_band(np.float32(_QA_CLEAR), _THERMAL)
    assert value == _QA_CLEAR
    assert masked is False
    assert reason is None
    assert "clear" in label


def test_a_cloudy_landsat_pixel_is_masked_and_says_why() -> None:
    value, label, masked, reason = _read_quality_band(np.float32(_QA_CLOUD), _THERMAL)
    assert masked is True
    assert "cloud" in label
    # The band is named, so the number in the message is readable against
    # the right documentation.
    assert reason is not None
    assert reason.startswith("QA_PIXEL = ")
    assert str(_QA_CLOUD) in reason


def test_a_fill_pixel_is_masked_as_fill_not_as_saturated() -> None:
    """The exact mislabel the SCL table produced on this value."""
    _, label, masked, _ = _read_quality_band(np.float32(_QA_FILL), _THERMAL)
    assert masked is True
    assert label == "fill"
    assert label != SCL_LABELS[1]


def test_the_membership_test_would_have_got_the_cloudy_pixel_wrong() -> None:
    """Pins the regression itself, not just the fixed behaviour.

    If this ever passes with SCL rules again, the dispatch has been lost.
    """
    from app.modules.indices.computation import scl_cloud_mask

    wrong = bool(scl_cloud_mask(np.array([[np.float32(_QA_CLOUD)]]))[0, 0])
    _, _, right, _ = _read_quality_band(np.float32(_QA_CLOUD), _THERMAL)
    assert wrong is False
    assert right is True


@pytest.mark.parametrize(
    ("scl", "expected_masked"),
    [
        (4, False),  # vegetation
        (6, False),  # water — kept, matching the ruleset
        (9, True),  # cloud, high probability
        (3, True),  # cloud shadow
    ],
)
def test_sentinel_scenes_are_unaffected(scl: int, expected_masked: bool) -> None:
    """The regression guard for every optical scene, which is most of them."""
    value, label, masked, reason = _read_quality_band(np.float32(scl), _OPTICAL)
    assert value == scl
    assert label == SCL_LABELS[scl]
    assert masked is expected_masked
    if expected_masked:
        assert reason is not None
        assert reason.startswith("SCL = ")


def test_qa_label_names_every_set_flag_bit() -> None:
    # Bits 3 (cloud) and 4 (cloud shadow), nothing else.
    assert _qa_pixel_label(0b11000) == "cloud, cloud shadow"


def test_qa_label_ignores_the_confidence_bits() -> None:
    """Bits 8-15 qualify the flags rather than standing alone.

    Naming them would bury the ones that decide the mask under noise.
    """
    assert _qa_pixel_label(0xFF00) == "no flags set"


def test_every_masking_bit_has_a_label() -> None:
    """A bit that drops a pixel with no name would read as an empty reason."""
    assert set(LANDSAT_QA_MASKED_BITS) <= set(QA_PIXEL_BIT_LABELS)


def test_every_product_with_an_index_set_has_a_mask_ruleset() -> None:
    """The two dispatch tables have to cover the same products.

    A product in one and not the other computes indices it never masked,
    or masks a scene it cannot compute — either way the panel would
    describe something the pipeline is not doing.
    """
    assert set(PRODUCT_INDEX_CODES) == set(PRODUCT_MASK_RULESETS)


def test_no_observer_module_reaches_for_the_sentinel_only_helpers() -> None:
    """Structural guard: Observer must dispatch on the product, never assume S2.

    `compute_all_indices` and `scl_cloud_mask` are the Sentinel-2-only
    entry points. Any Observer module that calls one has re-introduced the
    assumption that broke thermal — and each time it did, the symptom was
    different and none of them failed a test:

      * `pixels.explain_pixel` masked a cloudy Landsat pixel as CLEAR and
        offered no thermal indices at all;
      * `pixels.compute_pixel_budget` returned an empty budget, because the
        KeyError was swallowed;
      * `pixel_grid.build_pixel_grid` died on `KeyError: 'nir'` — invisible
        until a farm scene became openable and the map tried to draw.

    Three modules, three failure modes, one cause. The product-dispatching
    pair (`compute_indices_for_product`, `quality_band_mask`) is the only
    correct entry point, so pin the import surface rather than trusting
    each new call site to remember.
    """
    observer_dir = Path(__file__).resolve().parents[4] / "app" / "modules" / "observer"
    offenders: list[str] = []
    for module in sorted(observer_dir.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        for banned in ("compute_all_indices", "scl_cloud_mask"):
            # Mentioning one in prose is fine; importing or calling it is not.
            if re.search(rf"\b{banned}\s*\(", source) or re.search(
                rf"^from .+ import .*\b{banned}\b", source, re.M
            ):
                offenders.append(f"{module.name}: {banned}")
    assert offenders == [], (
        "Observer modules must call compute_indices_for_product / "
        f"quality_band_mask instead: {offenders}"
    )
