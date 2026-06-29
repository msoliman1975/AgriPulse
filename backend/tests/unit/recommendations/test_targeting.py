"""Unit tests for multi-axis decision-tree targeting (DT targeting PR-3).

Pure-fn tests of ``tree_targets_block`` — AND across axes, OR within an
axis, empty set = matches any, unknown block value never matches a
constrained axis. DB-less.
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.recommendations.service import tree_targets_block


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
