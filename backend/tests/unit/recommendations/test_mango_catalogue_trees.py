"""Walk every tree in the T_ mango catalogue to the leaf it should reach.

The catalogue turns `tatoo Docs/Mango indices- 28_8/
AgriPulse_Mango_Indices_Plan_EN.xlsx` into twenty-two decision trees. Eleven
compare one index against the band the guide gives for the block's tree size,
five read several indices together, six carry the agriculture plan.

Assert the LEAF, not the outcome text. Nine of the eleven index trees are
generated from one shape, so a bug in that shape reaches nine trees at once
and a test that only checked "a card was opened" would pass through all of
them. The leaf id says which branch actually ran.

Four behaviours are pinned throughout, because each one has already been
shipped broken at least once on this platform:

* the size branch changes the verdict, not just the label -- the same reading
  is normal for one size and a problem for another;
* an unrecorded size reaches `leaf_size_unknown` and never guesses a band;
* a missing or unmeasured index fails closed rather than reading as zero;
* a leaf that exists to explain a data problem (a clipped CWSI, a deliberate
  nitrogen stop) is reached instead of the card it would otherwise open.

Pure evaluation: compile the YAML, hand-build a context, walk the tree. No
database, so this lives in the unit suite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.recommendations.engine import EvaluationResult, TreeOutcome, evaluate_tree
from app.modules.recommendations.loader import DecisionTreeParseError, compile_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import IndicesEntry, WeatherRiskEntry

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"

# Every code in the catalogue, in the order the catalogue lists them: the
# eleven index-band trees, the five that combine, the six from the plan.
CATALOGUE: tuple[str, ...] = (
    "t_ndvi_canopy_vigour",
    "t_evi_canopy_vigour",
    "t_savi_canopy_vigour",
    "t_msavi_canopy_vigour",
    "t_gndvi_chlorophyll",
    "t_ndre_nitrogen",
    "t_ndmi_leaf_water",
    "t_msi_moisture_stress",
    "t_cwsi_irrigation_stress",
    "t_smi_soil_moisture",
    "t_bsi_ground_cover",
    "t_water_stress_confirm",
    "t_vigour_cause_split",
    "t_young_orchard_establishment",
    "t_size_record_check",
    "t_deficit_irrigation_verify",
    "t_post_harvest_care",
    "t_flower_induction_readiness",
    "t_bloom_protection",
    "t_fruit_development_program",
    "t_anthracnose_mealybug_watch",
    "t_fruit_fly_harvest_readiness",
)


def _tree(code: str) -> dict[str, Any]:
    return compile_tree(
        yaml.safe_load((_SEEDS / f"{code}.yaml").read_text(encoding="utf-8")),
        source_path=code,
    )


def _ctx(
    *,
    size: str | None = None,
    bearing: str | None = None,
    harvest_group: str | None = None,
    stage: str | None = None,
    risks: dict[str, int] | None = None,
    dev: dict[str, float] | None = None,
    **means: float | None,
) -> ConditionContext:
    """Build a context for one block.

    An index passed through `means` as `None` is present-but-unmeasured, which
    is what a fully masked scene looks like; an index not passed at all is
    absent entirely. Both must fail closed, and they take different code paths
    to get there, so both appear in the tests below.
    """
    attrs: dict[str, Any] = {}
    if size is not None:
        attrs["tree_size_class"] = size
    if bearing is not None:
        attrs["bearing_status"] = bearing
    if harvest_group is not None:
        attrs["harvest_season_group"] = harvest_group

    indices: dict[str, IndicesEntry] = {
        code: IndicesEntry(
            time=datetime.now(UTC),
            mean=None if value is None else Decimal(str(value)),
            baseline_deviation=None,
        )
        for code, value in means.items()
    }
    for code, z in (dev or {}).items():
        existing = indices.get(code)
        indices[code] = IndicesEntry(
            time=datetime.now(UTC),
            mean=existing.mean if existing else None,
            baseline_deviation=Decimal(str(z)),
        )

    return ConditionContext(
        block_id="b1",
        block_attributes={} if stage is None else {"growth_stage": stage},
        crop_attributes=attrs,
        indices=indices,
        weather_risks={
            code: WeatherRiskEntry(date=date.today(), score=v) for code, v in (risks or {}).items()
        },
    )


def _leaf(result: EvaluationResult) -> str:
    return result.path[-1].node_id


def _outcome(result: EvaluationResult) -> TreeOutcome:
    assert result.outcome is not None
    return result.outcome


# ---------------------------------------------------------------------------
# Catalogue-wide invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", CATALOGUE)
def test_every_catalogue_tree_compiles(code: str) -> None:
    tree = _tree(code)
    assert tree["code"] == code
    assert tree["crop_path"] == "mango"


@pytest.mark.parametrize("code", CATALOGUE)
def test_every_leaf_carries_both_languages(code: str) -> None:
    """A card with an English body and an empty Arabic one renders as a blank
    card to half the users on this platform, and nothing in the pipeline
    notices. Every leaf must carry both."""
    tree = _tree(code)
    for node_id, node in tree["nodes"].items():
        outcome = node.get("outcome")
        if outcome is None:
            continue
        assert outcome.get("text_en"), f"{code}:{node_id} has no English text"
        assert outcome.get("text_ar"), f"{code}:{node_id} has no Arabic text"


@pytest.mark.parametrize("code", CATALOGUE)
def test_every_node_label_carries_both_languages(code: str) -> None:
    tree = _tree(code)
    for node_id, node in tree["nodes"].items():
        assert node.get("label_en"), f"{code}:{node_id} has no English label"
        assert node.get("label_ar"), f"{code}:{node_id} has no Arabic label"


@pytest.mark.parametrize("code", CATALOGUE)
def test_every_tree_names_itself_and_says_what_it_does(code: str) -> None:
    tree = _tree(code)
    for field in ("name_en", "name_ar", "description_en", "description_ar"):
        assert tree.get(field), f"{code} has no {field}"
    assert tree["name_en"].startswith("T_"), f"{code} name does not carry its T_ prefix"


@pytest.mark.parametrize("code", CATALOGUE)
def test_no_tree_reads_the_platform_ndwi(code: str) -> None:
    """The guide's NDWI row carries the formula (NIR-SWIR)/(NIR+SWIR), which
    is NDMI. The platform's `ndwi` is McFeeters (GREEN-NIR)/(GREEN+NIR) --
    open surface water, a different measurement entirely. A mango moisture
    rule written on `ndwi` reads the wrong band with no error, and on Mango
    Republic the two average -0.079 and -0.328, so nothing about the number
    would look wrong either."""
    raw = (_SEEDS / f"{code}.yaml").read_text(encoding="utf-8")
    assert "index_code: ndwi" not in raw


# ---------------------------------------------------------------------------
# The op validator added with this catalogue
# ---------------------------------------------------------------------------


def test_unknown_operator_is_rejected_at_compile_time() -> None:
    """`gte` is the spelling most rule engines use and this one does not. The
    evaluator catches the parse error and answers "did not match", so before
    this validator a typo'd operator produced a branch that silently took
    `on_miss` for ever, with no card, log line or trace saying why."""
    spec = yaml.safe_load((_SEEDS / "t_ndvi_canopy_vigour.yaml").read_text(encoding="utf-8"))
    spec["nodes"]["small_check"]["condition"]["tree"]["op"] = "gte"
    with pytest.raises(DecisionTreeParseError, match="operator"):
        compile_tree(spec, source_path="probe")


# ---------------------------------------------------------------------------
# Index-band trees: the size branch has to change the verdict
# ---------------------------------------------------------------------------


def test_ndvi_same_reading_opposite_verdicts_by_size() -> None:
    """NDVI 0.18 is normal for a small mango tree over bright sand and a
    collapse on a closed canopy. The guide's bands are 0.10-0.22 and
    0.65-0.81; nothing but the recorded size separates them."""
    ndvi = _tree("t_ndvi_canopy_vigour")
    assert _leaf(evaluate_tree(ndvi, _ctx(size="small", ndvi=0.18))) == "leaf_in_band"
    assert _leaf(evaluate_tree(ndvi, _ctx(size="large", ndvi=0.18))) == "leaf_out_of_band_large"


def test_ndvi_medium_band_sits_between_the_other_two() -> None:
    ndvi = _tree("t_ndvi_canopy_vigour")
    assert _leaf(evaluate_tree(ndvi, _ctx(size="medium", ndvi=0.30))) == "leaf_in_band"
    assert _leaf(evaluate_tree(ndvi, _ctx(size="medium", ndvi=0.18))) == "leaf_out_of_band_medium"


@pytest.mark.parametrize(
    "code",
    [
        "t_ndvi_canopy_vigour",
        "t_evi_canopy_vigour",
        "t_savi_canopy_vigour",
        "t_msavi_canopy_vigour",
        "t_gndvi_chlorophyll",
        "t_ndmi_leaf_water",
        "t_msi_moisture_stress",
        "t_bsi_ground_cover",
    ],
)
def test_unrecorded_size_reaches_the_unknown_leaf(code: str) -> None:
    """Every size-aware tree has to say "I have no band to compare against"
    rather than fall through to a default band. Guessing medium would put a
    young orchard below its range on the first sweep."""
    r = evaluate_tree(
        _tree(code),
        _ctx(ndvi=0.01, evi=0.01, savi=0.01, msavi=0.01, gndvi=0.01, ndmi=-0.9, msi=2.5, bsi=0.9),
    )
    assert _leaf(r) == "leaf_size_unknown"
    assert _outcome(r).action_type == "no_action"


@pytest.mark.parametrize(
    ("code", "index"),
    [
        ("t_ndvi_canopy_vigour", "ndvi"),
        ("t_evi_canopy_vigour", "evi"),
        ("t_savi_canopy_vigour", "savi"),
        ("t_msavi_canopy_vigour", "msavi"),
        ("t_gndvi_chlorophyll", "gndvi"),
        ("t_ndmi_leaf_water", "ndmi"),
    ],
)
def test_unmeasured_index_does_not_read_as_zero(code: str, index: str) -> None:
    """A fully masked scene leaves the row present with a null mean. Reading
    that as zero would open a card on every cloudy week."""
    r = evaluate_tree(_tree(code), _ctx(size="medium", **{index: None}))
    assert _leaf(r) == "leaf_in_band"


@pytest.mark.parametrize(
    ("code", "index"),
    [
        ("t_ndvi_canopy_vigour", "ndvi"),
        ("t_savi_canopy_vigour", "savi"),
        ("t_ndmi_leaf_water", "ndmi"),
    ],
)
def test_absent_index_row_does_not_read_as_zero(code: str, index: str) -> None:
    """Absent entirely, rather than present-and-null: a block with no scene at
    all. Different code path, same requirement."""
    assert _leaf(evaluate_tree(_tree(code), _ctx(size="medium"))) == "leaf_in_band"


def test_msi_is_inverted_high_is_the_problem() -> None:
    """MSI is the one index in the guide where more is worse. The guide's
    medium band is 0.60-0.90; 1.20 is stress and 0.40 is a well-watered
    tree, which is the opposite of how every other tree here reads."""
    msi = _tree("t_msi_moisture_stress")
    assert _leaf(evaluate_tree(msi, _ctx(size="medium", msi=1.20))) == "leaf_out_of_band_medium"
    assert _leaf(evaluate_tree(msi, _ctx(size="medium", msi=0.40))) == "leaf_in_band"


def test_bsi_is_inverted_high_is_the_problem() -> None:
    bsi = _tree("t_bsi_ground_cover")
    assert _leaf(evaluate_tree(bsi, _ctx(size="large", bsi=0.30))) == "leaf_out_of_band_large"
    assert _leaf(evaluate_tree(bsi, _ctx(size="large", bsi=0.08))) == "leaf_in_band"


def test_ndmi_small_band_uses_the_widest_stage_value() -> None:
    """Small + productive is one of the eight cells that moves between the
    workbook's stage sheets: -0.07 at flowering and maturity, -0.15 during
    fruit development. The tree takes no stage input, so it must use the
    widest of the three or it alerts inside a documented range."""
    ndmi = _tree("t_ndmi_leaf_water")
    assert _leaf(evaluate_tree(ndmi, _ctx(size="small", ndmi=-0.10))) == "leaf_in_band"
    assert _leaf(evaluate_tree(ndmi, _ctx(size="small", ndmi=-0.20))) == "leaf_out_of_band_small"


def test_small_tree_cards_are_advisory() -> None:
    """The guide grades every small-tree cell Low and asks for ground-truthing
    before the ranges drive a decision. A small-tree finding is therefore info
    and carries the lowest confidence of the three sizes."""
    ndvi = _tree("t_ndvi_canopy_vigour")
    small = _outcome(evaluate_tree(ndvi, _ctx(size="small", ndvi=0.05)))
    large = _outcome(evaluate_tree(ndvi, _ctx(size="large", ndvi=0.05)))
    assert small.severity == "info"
    assert large.severity == "warning"
    assert small.confidence < large.confidence


# ---------------------------------------------------------------------------
# CWSI: the saturation guard
# ---------------------------------------------------------------------------


def test_cwsi_clipped_reading_does_not_open_an_irrigation_card() -> None:
    """CWSI is computed against a fixed dry-canopy constant that Egyptian
    summer surface temperature runs straight past, so the value clips to 1.0
    for stressed and healthy blocks alike -- 2,959 thermal rows on Mango
    Republic average 0.995. Without this guard the tree opens a critical
    irrigation card on every mango block in the country."""
    cwsi = _tree("t_cwsi_irrigation_stress")
    r = evaluate_tree(cwsi, _ctx(size="medium", bearing="not_bearing", cwsi=1.0))
    assert _leaf(r) == "leaf_saturated"
    assert _outcome(r).action_type == "no_action"


def test_cwsi_below_the_guard_still_reads_normally() -> None:
    cwsi = _tree("t_cwsi_irrigation_stress")
    hot = evaluate_tree(cwsi, _ctx(size="medium", bearing="not_bearing", cwsi=0.50))
    assert _leaf(hot) == "leaf_out_of_band_medium"
    assert _outcome(hot).action_type == "irrigate"
    cool = evaluate_tree(cwsi, _ctx(size="medium", bearing="not_bearing", cwsi=0.20))
    assert _leaf(cool) == "leaf_in_band"


def test_cwsi_deficit_window_raises_the_bar_for_a_bearing_block() -> None:
    """0.40 is above the normal medium ceiling of 0.30 and inside the deficit
    window's 0.25-0.54. A bearing block in maturation is being deliberately
    stressed, so the same reading must not open a card there."""
    cwsi = _tree("t_cwsi_irrigation_stress")
    resting = _ctx(size="medium", bearing="not_bearing", stage="maturation", cwsi=0.40)
    bearing = _ctx(size="medium", bearing="bearing", stage="maturation", cwsi=0.40)
    assert _leaf(evaluate_tree(cwsi, resting)) == "leaf_out_of_band_medium"
    assert _leaf(evaluate_tree(cwsi, bearing)) == "leaf_in_band"


def test_cwsi_deficit_window_still_has_a_ceiling() -> None:
    cwsi = _tree("t_cwsi_irrigation_stress")
    ctx = _ctx(size="medium", bearing="bearing", stage="maturation", cwsi=0.60)
    assert _leaf(evaluate_tree(cwsi, ctx)) == "leaf_deficit_out_of_band_medium"


def test_cwsi_deficit_window_needs_both_bearing_and_the_stage() -> None:
    """Bearing alone is not the window. A bearing block in fruit development
    is on full irrigation and gets the normal band."""
    cwsi = _tree("t_cwsi_irrigation_stress")
    ctx = _ctx(size="medium", bearing="bearing", stage="fruit_development", cwsi=0.40)
    assert _leaf(evaluate_tree(cwsi, ctx)) == "leaf_out_of_band_medium"


def test_smi_deficit_window_lowers_the_floor_for_a_bearing_block() -> None:
    """SMI moves the other way from CWSI in the same window: the guide lowers
    the band because the soil is meant to be drier."""
    smi = _tree("t_smi_soil_moisture")
    resting = _ctx(size="medium", bearing="not_bearing", stage="maturation", smi=0.35)
    bearing = _ctx(size="medium", bearing="bearing", stage="maturation", smi=0.35)
    assert _leaf(evaluate_tree(smi, resting)) == "leaf_out_of_band_medium"
    assert _leaf(evaluate_tree(smi, bearing)) == "leaf_in_band"


# ---------------------------------------------------------------------------
# NDRE: the deliberate nitrogen stop
# ---------------------------------------------------------------------------


def test_ndre_is_silent_while_nitrogen_is_withheld_on_purpose() -> None:
    """The plan stops nitrogen about two months before flowering to push the
    tree from vegetative growth into flowering. A low NDRE in that window is
    the plan working. Without this gate the rule fires on every block, every
    season, at the one moment the number is meant to be low."""
    ndre = _tree("t_ndre_nitrogen")
    ctx = _ctx(size="large", stage="pre_flowering", ndre=0.10)
    r = evaluate_tree(ndre, ctx)
    assert _leaf(r) == "leaf_stage_suppressed"
    assert _outcome(r).action_type == "no_action"


def test_ndre_fires_once_the_window_has_passed() -> None:
    ndre = _tree("t_ndre_nitrogen")
    ctx = _ctx(size="large", stage="fruit_development", ndre=0.10)
    r = evaluate_tree(ndre, ctx)
    assert _leaf(r) == "leaf_out_of_band_large"
    assert _outcome(r).action_type == "fertilize"


# ---------------------------------------------------------------------------
# T_WATER_CONFIRM
# ---------------------------------------------------------------------------


def test_water_confirm_needs_more_than_one_reading() -> None:
    confirm = _tree("t_water_stress_confirm")
    one = _ctx(cwsi=0.5, dev={"ndmi": -2.0, "smi": 0.0, "cwsi": 0.0})
    assert _leaf(evaluate_tree(confirm, one)) == "leaf_single_signal"
    assert _outcome(evaluate_tree(confirm, one)).action_type == "scout"


def test_water_confirm_two_readings_open_an_irrigation_card() -> None:
    confirm = _tree("t_water_stress_confirm")
    two = _ctx(cwsi=0.5, dev={"ndmi": -2.0, "smi": -2.0, "cwsi": 0.0})
    r = evaluate_tree(confirm, two)
    assert _leaf(r) == "leaf_confirmed"
    assert _outcome(r).action_type == "irrigate"


def test_water_confirm_three_readings_escalate() -> None:
    confirm = _tree("t_water_stress_confirm")
    three = _ctx(cwsi=0.5, dev={"ndmi": -2.0, "smi": -2.0, "cwsi": 2.0})
    r = evaluate_tree(confirm, three)
    assert _leaf(r) == "leaf_confirmed_strong"
    assert _outcome(r).severity == "critical"


def test_water_confirm_drops_the_thermal_vote_when_cwsi_is_clipped() -> None:
    """With CWSI clipped there are two usable votes, not three, and NDMI alone
    must still not reach `confirmed`. Counting a clipped reading as a vote
    would let every block in an Egyptian summer confirm on one signal."""
    confirm = _tree("t_water_stress_confirm")
    ctx = _ctx(cwsi=1.0, dev={"ndmi": -2.0, "smi": 0.0, "cwsi": 3.0})
    assert _leaf(evaluate_tree(confirm, ctx)) == "leaf_single_signal"


def test_water_confirm_never_reads_msi() -> None:
    """MSI is SWIR/NIR and NDMI is (NIR-SWIR)/(NIR+SWIR): ndmi == (1-msi)/(1+msi),
    a monotone transform, so they cannot disagree. Reading both would let one
    measurement cast two votes and reach `confirmed` on its own."""
    raw = (_SEEDS / "t_water_stress_confirm.yaml").read_text(encoding="utf-8")
    assert "index_code: msi" not in raw


def test_water_confirm_quiet_when_nothing_is_dry() -> None:
    confirm = _tree("t_water_stress_confirm")
    ctx = _ctx(cwsi=0.3, dev={"ndmi": 0.2, "smi": 0.1, "cwsi": -0.3})
    assert _leaf(evaluate_tree(confirm, ctx)) == "leaf_no_stress"


# ---------------------------------------------------------------------------
# T_VIGOUR_CAUSE
# ---------------------------------------------------------------------------


def test_vigour_cause_is_silent_while_the_canopy_holds() -> None:
    cause = _tree("t_vigour_cause_split")
    assert _leaf(evaluate_tree(cause, _ctx(dev={"savi": 0.1}))) == "leaf_no_action"


def test_vigour_cause_open_ground_beats_the_other_two() -> None:
    """Bare soil rising with the canopy falling means trees are gone, and no
    amount of water or fertilizer brings those back -- so this branch is
    checked before either input cause."""
    cause = _tree("t_vigour_cause_split")
    ctx = _ctx(dev={"savi": -2.0, "bsi": 2.0, "ndmi": -2.0, "ndre": -2.0})
    assert _leaf(evaluate_tree(cause, ctx)) == "leaf_missing_trees"


def test_vigour_cause_separates_water_from_nutrition() -> None:
    cause = _tree("t_vigour_cause_split")
    water = _ctx(dev={"savi": -2.0, "bsi": 0.0, "ndmi": -2.0, "ndre": 0.0})
    nutrition = _ctx(dev={"savi": -2.0, "bsi": 0.0, "ndmi": 0.0, "ndre": -2.0})
    assert _leaf(evaluate_tree(cause, water)) == "leaf_water_cause"
    assert _leaf(evaluate_tree(cause, nutrition)) == "leaf_nitrogen_cause"


def test_vigour_cause_both_inputs_down_asks_for_water_first() -> None:
    """A tree short of water cannot take up nutrients either, so the combined
    leaf treats water as the likely single root cause rather than sending a
    fertilizer order and a water order at once."""
    cause = _tree("t_vigour_cause_split")
    ctx = _ctx(dev={"savi": -2.0, "bsi": 0.0, "ndmi": -2.0, "ndre": -2.0})
    r = evaluate_tree(cause, ctx)
    assert _leaf(r) == "leaf_combined"
    assert _outcome(r).action_type == "scout"


def test_vigour_cause_admits_when_it_cannot_separate() -> None:
    cause = _tree("t_vigour_cause_split")
    ctx = _ctx(dev={"savi": -2.0, "bsi": 0.0, "ndmi": 0.0, "ndre": 0.0})
    assert _leaf(evaluate_tree(cause, ctx)) == "leaf_unseparated"


# ---------------------------------------------------------------------------
# T_ESTABLISH
# ---------------------------------------------------------------------------


def test_establishment_runs_on_small_blocks_only() -> None:
    est = _tree("t_young_orchard_establishment")
    ctx = _ctx(size="large", msavi=0.01, bsi=0.99)
    assert _leaf(evaluate_tree(est, ctx)) == "leaf_not_applicable"


def test_establishment_separates_slow_fill_from_lost_saplings() -> None:
    """A healthy MSAVI with a high BSI is the case no greenness index can see
    on its own: the survivors are fine, there are simply fewer of them."""
    est = _tree("t_young_orchard_establishment")
    gaps = _ctx(size="small", msavi=0.30, bsi=0.70)
    slow = _ctx(size="small", msavi=0.10, bsi=0.45)
    both = _ctx(size="small", msavi=0.10, bsi=0.70)
    assert _leaf(evaluate_tree(est, gaps)) == "leaf_gaps_only"
    assert _leaf(evaluate_tree(est, slow)) == "leaf_slow_fill"
    assert _leaf(evaluate_tree(est, both)) == "leaf_establishment_gaps"


def test_establishment_quiet_when_the_block_is_filling_in() -> None:
    est = _tree("t_young_orchard_establishment")
    ctx = _ctx(size="small", msavi=0.22, bsi=0.45)
    assert _leaf(evaluate_tree(est, ctx)) == "leaf_establishing_ok"


# ---------------------------------------------------------------------------
# T_SIZE_CHECK
# ---------------------------------------------------------------------------


def test_size_check_catches_a_block_recorded_a_class_too_large() -> None:
    """This is the failure this rule exists for, and it has shipped before:
    100 prod blocks carried a size label a whole class above what their
    imagery and their recorded age both said."""
    check = _tree("t_size_record_check")
    ctx = _ctx(size="medium", ndvi=0.18, bsi=0.45)
    r = evaluate_tree(check, ctx)
    assert _leaf(r) == "leaf_looks_smaller"
    assert _outcome(r).action_type == "other"


def test_size_check_catches_a_block_recorded_a_class_too_small() -> None:
    check = _tree("t_size_record_check")
    ctx = _ctx(size="small", ndvi=0.35, bsi=0.20)
    assert _leaf(evaluate_tree(check, ctx)) == "leaf_looks_bigger"


def test_size_check_needs_the_ground_to_agree() -> None:
    """A large block whose canopy genuinely collapsed reads a low NDVI without
    being small. BSI is what separates the two: a real size difference has to
    show up as a difference in exposed soil as well."""
    check = _tree("t_size_record_check")
    collapsed = _ctx(size="large", ndvi=0.30, bsi=0.10)
    assert _leaf(evaluate_tree(check, collapsed)) == "leaf_match"


def test_size_check_is_quiet_on_a_consistent_block() -> None:
    check = _tree("t_size_record_check")
    assert _leaf(evaluate_tree(check, _ctx(size="large", ndvi=0.72, bsi=0.08))) == "leaf_match"
    assert _leaf(evaluate_tree(check, _ctx(size="small", ndvi=0.15, bsi=0.45))) == "leaf_match"


def test_size_check_says_nothing_without_a_recorded_size() -> None:
    check = _tree("t_size_record_check")
    assert _leaf(evaluate_tree(check, _ctx(ndvi=0.72, bsi=0.08))) == "leaf_size_unknown"


# ---------------------------------------------------------------------------
# T_DEFICIT_CHECK — the one tree that complains about a reading being GOOD
# ---------------------------------------------------------------------------


def test_deficit_check_only_runs_on_a_bearing_block_in_maturation() -> None:
    ver = _tree("t_deficit_irrigation_verify")
    resting = _ctx(size="medium", bearing="not_bearing", stage="maturation", smi=0.55)
    early = _ctx(size="medium", bearing="bearing", stage="fruit_development", smi=0.55)
    assert _leaf(evaluate_tree(ver, resting)) == "leaf_not_in_window"
    assert _leaf(evaluate_tree(ver, early)) == "leaf_not_in_window"


def test_deficit_check_reports_a_cut_that_never_happened() -> None:
    ver = _tree("t_deficit_irrigation_verify")
    ctx = _ctx(size="medium", bearing="bearing", stage="maturation", smi=0.55)
    r = evaluate_tree(ver, ctx)
    assert _leaf(r) == "leaf_not_detected"
    assert _outcome(r).action_type == "irrigate"


def test_deficit_check_reports_a_cut_that_went_too_deep() -> None:
    ver = _tree("t_deficit_irrigation_verify")
    ctx = _ctx(size="medium", bearing="bearing", stage="maturation", smi=0.20)
    r = evaluate_tree(ver, ctx)
    assert _leaf(r) == "leaf_overshot"
    assert _outcome(r).severity == "critical"


def test_deficit_check_confirms_a_cut_in_the_intended_range() -> None:
    ver = _tree("t_deficit_irrigation_verify")
    ctx = _ctx(size="medium", bearing="bearing", stage="maturation", smi=0.36)
    r = evaluate_tree(ver, ctx)
    assert _leaf(r) == "leaf_confirmed"
    assert _outcome(r).action_type == "no_action"


# ---------------------------------------------------------------------------
# Plan trees
# ---------------------------------------------------------------------------


def test_post_harvest_opens_on_the_flush_stage() -> None:
    care = _tree("t_post_harvest_care")
    due = _ctx(bearing="bearing", stage="post_harvest_flush")
    r = evaluate_tree(care, due)
    assert _leaf(r) == "leaf_due_bearing"
    assert _outcome(r).action_type == "prune"


def test_post_harvest_holds_the_heavy_feed_on_a_resting_block() -> None:
    """A resting tree fed as if it had cropped puts the nitrogen into
    vegetative growth, which delays next season's flowering. The sanitation
    half still applies, so the leaf is different rather than absent."""
    care = _tree("t_post_harvest_care")
    r = evaluate_tree(care, _ctx(bearing="not_bearing", stage="post_harvest_flush"))
    assert _leaf(r) == "leaf_due_resting"
    assert _outcome(r).severity == "info"


def test_post_harvest_silent_outside_its_window() -> None:
    care = _tree("t_post_harvest_care")
    assert _leaf(evaluate_tree(care, _ctx(bearing="bearing", stage="flowering"))) == "leaf_not_due"


def test_induction_holds_while_the_canopy_is_still_growing() -> None:
    """Flowering cannot begin while shoots are still flushing. Starting the
    dry period into an active flush spends the stress on the flush and the
    season is gone -- there is no second attempt."""
    ind = _tree("t_flower_induction_readiness")
    ctx = _ctx(stage="pre_flowering", dev={"ndvi": 1.5})
    r = evaluate_tree(ind, ctx)
    assert _leaf(r) == "leaf_hold_flushing"


def test_induction_starts_once_the_canopy_settles() -> None:
    ind = _tree("t_flower_induction_readiness")
    ctx = _ctx(stage="pre_flowering", dev={"ndvi": 0.0})
    assert _leaf(evaluate_tree(ind, ctx)) == "leaf_start_dry_period"


def test_induction_silent_outside_pre_flowering() -> None:
    ind = _tree("t_flower_induction_readiness")
    ctx = _ctx(stage="fruit_development", dev={"ndvi": 1.5})
    assert _leaf(evaluate_tree(ind, ctx)) == "leaf_not_due"


def test_bloom_protection_treats_only_at_high_risk() -> None:
    """Mango sets its crop through flies and bees. A spray at moderate risk
    during peak bloom costs more fruit than the mildew would have, so the
    middle band is a look and not a spray."""
    bloom = _tree("t_bloom_protection")
    high = _ctx(stage="flowering", risks={"powdery_mildew": 85})
    mid = _ctx(stage="flowering", risks={"powdery_mildew": 60})
    low = _ctx(stage="flowering", risks={"powdery_mildew": 10})
    assert _outcome(evaluate_tree(bloom, high)).action_type == "spray"
    assert _outcome(evaluate_tree(bloom, mid)).action_type == "scout"
    assert _leaf(evaluate_tree(bloom, low)) == "leaf_low_risk"


def test_bloom_protection_silent_outside_bloom() -> None:
    bloom = _tree("t_bloom_protection")
    ctx = _ctx(stage="maturation", risks={"powdery_mildew": 95})
    assert _leaf(evaluate_tree(bloom, ctx)) == "leaf_not_due"


def test_fruit_development_splits_the_two_kno3_sprays() -> None:
    """The two sprays are the same product at the same rate doing different
    jobs -- retention at about 42 days, sizing at about 65. One card listing
    both would leave the reader to guess which is due."""
    prog = _tree("t_fruit_development_program")
    early = _ctx(bearing="bearing", stage="fruit_set")
    late = _ctx(bearing="bearing", stage="fruit_development")
    assert _leaf(evaluate_tree(prog, early)) == "leaf_early_program"
    assert _leaf(evaluate_tree(prog, late)) == "leaf_late_program"


def test_fruit_development_skips_a_resting_block() -> None:
    prog = _tree("t_fruit_development_program")
    ctx = _ctx(bearing="not_bearing", stage="fruit_development")
    assert _leaf(evaluate_tree(prog, ctx)) == "leaf_not_bearing"


def test_anthracnose_runs_across_the_whole_susceptible_window() -> None:
    """Flowering through maturation, not fruit development alone: the disease
    reaches flowers and it reaches ripening fruit, and it stays latent until
    after picking either way."""
    watch = _tree("t_anthracnose_mealybug_watch")
    for stage in ("flowering", "fruit_set", "fruit_development", "maturation"):
        ctx = _ctx(stage=stage, risks={"anthracnose": 90})
        assert _leaf(evaluate_tree(watch, ctx)) == "leaf_treat", stage


def test_anthracnose_silent_when_no_tissue_is_at_risk() -> None:
    watch = _tree("t_anthracnose_mealybug_watch")
    ctx = _ctx(stage="post_harvest_flush", risks={"anthracnose": 90})
    assert _leaf(evaluate_tree(watch, ctx)) == "leaf_not_due"


def test_harvest_opens_a_card_even_when_fly_pressure_is_low() -> None:
    """The picking discipline is the point, not only the pest. A single
    harvest date takes half the crop at the wrong maturity, so the low-risk
    leaf is still a card and not a no_action."""
    harv = _tree("t_fruit_fly_harvest_readiness")
    ctx = _ctx(bearing="bearing", stage="maturation", risks={"fruit_fly": 10})
    r = evaluate_tree(harv, ctx)
    assert _leaf(r) == "leaf_harvest_routine"
    assert _outcome(r).action_type == "harvest_window"


def test_harvest_escalates_with_fly_pressure() -> None:
    harv = _tree("t_fruit_fly_harvest_readiness")
    high = _ctx(bearing="bearing", stage="maturation", risks={"fruit_fly": 90})
    mid = _ctx(bearing="bearing", stage="maturation", risks={"fruit_fly": 60})
    assert _outcome(evaluate_tree(harv, high)).severity == "critical"
    assert _outcome(evaluate_tree(harv, mid)).severity == "warning"


def test_harvest_silent_on_a_resting_block() -> None:
    harv = _tree("t_fruit_fly_harvest_readiness")
    ctx = _ctx(bearing="not_bearing", stage="maturation", risks={"fruit_fly": 90})
    assert _leaf(evaluate_tree(harv, ctx)) == "leaf_not_bearing"
