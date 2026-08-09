"""Unit tests for multi-axis decision-tree targeting (DT targeting PR-3).

Pure-fn tests of ``tree_targets_block`` — AND across axes, OR within an
axis, empty set = matches any, unknown block value never matches a
constrained axis. DB-less.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.recommendations.service import evaluate_targeting, tree_targets_block


def _tree(**axes: object) -> dict[str, object]:
    """A tree dict with all axes empty unless overridden."""
    return {
        "crop_paths": [],
        "country_codes": [],
        "soil_textures": [],
        "crop_id": None,
        **axes,
    }


# --- empty = matches any ----------------------------------------------------


def test_all_empty_matches_any_block() -> None:
    assert tree_targets_block(
        _tree(), crop_path=None, crop_id=None, country_code=None, soil_texture=None
    )
    assert tree_targets_block(
        _tree(),
        crop_path="mango.alphonso",
        crop_id=uuid4(),
        country_code="EG",
        soil_texture="sandy",
    )


# --- crop axis (OR within, prefix match, legacy crop_id fallback) -----------


def test_crop_paths_prefix_match() -> None:
    tree = _tree(crop_paths=["mango"])
    assert tree_targets_block(
        tree, crop_path="mango.alphonso.short", crop_id=None, country_code=None, soil_texture=None
    )
    assert not tree_targets_block(
        tree, crop_path="citrus.valencia", crop_id=None, country_code=None, soil_texture=None
    )


def test_crop_paths_or_within_axis() -> None:
    tree = _tree(crop_paths=["mango", "citrus"])
    for path in ("mango.alphonso", "citrus.valencia"):
        assert tree_targets_block(
            tree, crop_path=path, crop_id=None, country_code=None, soil_texture=None
        )
    assert not tree_targets_block(
        tree, crop_path="wheat", crop_id=None, country_code=None, soil_texture=None
    )


def test_crop_constrained_block_without_crop_never_matches() -> None:
    tree = _tree(crop_paths=["mango"])
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture=None
    )


def test_legacy_crop_id_fallback_when_no_paths() -> None:
    cid = uuid4()
    tree = _tree(crop_id=cid)  # crop_paths empty, legacy crop_id set
    assert tree_targets_block(
        tree, crop_path=None, crop_id=cid, country_code=None, soil_texture=None
    )
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=uuid4(), country_code=None, soil_texture=None
    )


# --- country axis (AND, unknown-country exclusion) --------------------------


def test_country_axis_membership() -> None:
    tree = _tree(country_codes=["EG", "JO"])
    assert tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code="JO", soil_texture=None
    )
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code="SA", soil_texture=None
    )


def test_country_constrained_block_without_country_never_matches() -> None:
    tree = _tree(country_codes=["EG"])
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture=None
    )


# --- soil axis (AND) --------------------------------------------------------


def test_soil_axis_membership() -> None:
    tree = _tree(soil_textures=["sandy", "loam"])
    assert tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture="sandy"
    )
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture="clay"
    )
    assert not tree_targets_block(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture=None
    )


# --- AND across axes --------------------------------------------------------


def test_and_across_axes() -> None:
    tree = _tree(crop_paths=["mango"], country_codes=["EG"], soil_textures=["sandy"])
    # All three satisfied → match.
    assert tree_targets_block(
        tree, crop_path="mango.alphonso", crop_id=None, country_code="EG", soil_texture="sandy"
    )
    # One axis fails → no match, for each axis in turn.
    assert not tree_targets_block(
        tree, crop_path="wheat", crop_id=None, country_code="EG", soil_texture="sandy"
    )
    assert not tree_targets_block(
        tree, crop_path="mango.alphonso", crop_id=None, country_code="JO", soil_texture="sandy"
    )
    assert not tree_targets_block(
        tree, crop_path="mango.alphonso", crop_id=None, country_code="EG", soil_texture="clay"
    )


# --- the verdict: which axis rejected it, and both sides -------------------
#
# `tree_targets_block` answers "did it match". These cover the reason, which
# is what an evaluation trace stores and what the console renders instead of
# a bare "skipped".


def test_matched_verdict_carries_no_reason() -> None:
    verdict = evaluate_targeting(
        _tree(crop_paths=["mango"]),
        crop_path="mango.alphonso",
        crop_id=None,
        country_code=None,
        soil_texture=None,
    )
    assert verdict.matched
    assert verdict.axis is None
    assert verdict.required == ()
    assert verdict.actual is None


def test_crop_rejection_names_the_axis_and_both_sides() -> None:
    verdict = evaluate_targeting(
        _tree(crop_paths=["mango", "citrus"]),
        crop_path="wheat.durum",
        crop_id=None,
        country_code=None,
        soil_texture=None,
    )
    assert not verdict.matched
    assert verdict.axis == "crop"
    assert verdict.required == ("mango", "citrus")
    assert verdict.actual == "wheat.durum"


def test_country_rejection_distinguishes_unset_from_mismatched() -> None:
    """The two cases look identical in the old boolean world, and the unset
    one is the usual cause of "why is nothing firing on this farm?"."""
    tree = _tree(country_codes=["EG"])
    mismatched = evaluate_targeting(
        tree, crop_path=None, crop_id=None, country_code="JO", soil_texture=None
    )
    assert mismatched.axis == "country"
    assert mismatched.actual == "JO"

    unset = evaluate_targeting(
        tree, crop_path=None, crop_id=None, country_code=None, soil_texture=None
    )
    assert unset.axis == "country"
    assert unset.actual is None
    assert unset.required == ("EG",)


def test_soil_rejection_names_the_soil_axis() -> None:
    verdict = evaluate_targeting(
        _tree(soil_textures=["sandy", "loam"]),
        crop_path=None,
        crop_id=None,
        country_code=None,
        soil_texture="clay",
    )
    assert verdict.axis == "soil"
    assert verdict.required == ("sandy", "loam")
    assert verdict.actual == "clay"


def test_crop_is_reported_first_when_several_axes_would_reject() -> None:
    """Axes are ANDed so the order cannot change the verdict, only which
    reason is shown. Crop first: it is the axis authors set most often."""
    verdict = evaluate_targeting(
        _tree(crop_paths=["mango"], country_codes=["EG"], soil_textures=["sandy"]),
        crop_path="wheat",
        crop_id=None,
        country_code="JO",
        soil_texture="clay",
    )
    assert verdict.axis == "crop"


def test_legacy_crop_id_rejection_reports_the_crop_axis() -> None:
    wanted, actual = uuid4(), uuid4()
    verdict = evaluate_targeting(
        _tree(crop_id=wanted),
        crop_path=None,
        crop_id=actual,
        country_code=None,
        soil_texture=None,
    )
    assert verdict.axis == "crop"
    assert verdict.required == (str(wanted),)
    assert verdict.actual == str(actual)


def test_boolean_wrapper_still_agrees_with_the_verdict() -> None:
    """tree_targets_block is now a thin face over evaluate_targeting; the
    dry-run block picker depends on the two never diverging."""
    cases = [
        (_tree(), None, None, None),
        (_tree(crop_paths=["mango"]), "mango.alphonso", "EG", "sandy"),
        (_tree(crop_paths=["mango"]), "wheat", "EG", "sandy"),
        (_tree(country_codes=["EG"]), "mango", None, "sandy"),
        (_tree(soil_textures=["sandy"]), "mango", "EG", None),
    ]
    for tree, crop_path, country, soil in cases:
        kwargs = {
            "crop_path": crop_path,
            "crop_id": None,
            "country_code": country,
            "soil_texture": soil,
        }
        assert tree_targets_block(tree, **kwargs) is evaluate_targeting(tree, **kwargs).matched
