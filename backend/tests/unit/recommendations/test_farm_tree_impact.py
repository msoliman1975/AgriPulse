"""Which trees a farm's blocks match, and what a pending change moves.

Pure functions behind the farm tree selection, the impact preview and the
exclusion reconcile. The matcher is ``evaluate_targeting`` — the sweep's —
so these tests pin the farm-level rules layered on top of it: a farm with no
crop matches nothing, a tree is counted per block, and a preview compares the
farm before and after with the same matcher.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.modules.recommendations.service import (
    apply_block_changes,
    compute_farm_tree_impact,
    farm_has_crops,
    farm_tree_matches,
)


def _tree(code: str, *, crops=(), countries=(), soils=()) -> dict:  # type: ignore[no-untyped-def]
    return {
        "tree_id": uuid4(),
        "tree_code": code,
        "name_en": code,
        "name_ar": None,
        "crop_id": None,
        "crop_paths": list(crops),
        "country_codes": list(countries),
        "soil_textures": list(soils),
    }


def _block(crop: str | None = None, soil: str | None = None) -> dict:
    return {
        "block_id": uuid4(),
        "label": "B",
        "label_ar": None,
        "crop_id": uuid4() if crop else None,
        "crop_path": crop,
        "soil_texture": soil,
    }


def test_a_farm_without_crops_matches_nothing_not_even_any_crop_trees() -> None:
    any_crop = _tree("any")
    blocks = [_block(), _block(soil="clay")]

    assert farm_has_crops(blocks) is False
    assert farm_tree_matches([any_crop], blocks=blocks, country_code="EG") == {}


def test_matching_is_per_block_on_all_three_axes() -> None:
    mango = _tree("mango", crops=["mango"])
    alphonso_clay = _tree("alph", crops=["mango.alphonso"], soils=["clay"])
    jordan = _tree("jo", countries=["JO"])
    any_crop = _tree("any")
    b1 = _block("mango.alphonso.short", soil="clay")
    b2 = _block("mango.keitt", soil="sandy")
    b3 = _block()  # no crop: only crop-agnostic trees reach it

    m = farm_tree_matches(
        [mango, alphonso_clay, jordan, any_crop], blocks=[b1, b2, b3], country_code="EG"
    )

    assert m[mango["tree_id"]] == {b1["block_id"], b2["block_id"]}
    assert m[alphonso_clay["tree_id"]] == {b1["block_id"]}
    assert m[jordan["tree_id"]] == frozenset()
    assert m[any_crop["tree_id"]] == {b1["block_id"], b2["block_id"], b3["block_id"]}


def test_apply_block_changes_only_moves_the_keys_sent() -> None:
    b1 = _block("mango", soil="clay")
    b2 = _block("mango", soil="sandy")
    b3 = _block("potato")

    after = apply_block_changes(
        [b1, b2, b3],
        [
            {"block_id": b1["block_id"], "crop_id": None, "crop_path": None},
            {"block_id": b2["block_id"], "soil_texture": "loam"},
            {"block_id": b3["block_id"], "removed": True},
            {"block_id": uuid4(), "removed": True},  # not on this farm: ignored
        ],
    )

    assert [b["block_id"] for b in after] == [b1["block_id"], b2["block_id"]]
    assert after[0]["crop_path"] is None
    assert after[0]["soil_texture"] == "clay"
    assert after[1]["crop_path"] == "mango"
    assert after[1]["soil_texture"] == "loam"
    # The inputs are untouched.
    assert b1["crop_path"] == "mango"


def _impact(trees, before, after, *, changed, excluded=frozenset(), country=("EG", "EG")):  # type: ignore[no-untyped-def]
    return compute_farm_tree_impact(
        farm_id=uuid4(),
        trees=trees,
        blocks_before=before,
        blocks_after=after,
        country_before=country[0],
        country_after=country[1],
        excluded=frozenset(excluded),
        changed_block_ids=changed,
    )


def test_a_crop_swap_lists_starting_and_stopping_trees_for_that_block() -> None:
    mango = _tree("mango", crops=["mango"])
    potato = _tree("potato", crops=["potato"])
    b1 = _block("mango")
    b2 = _block("mango")
    after = apply_block_changes(
        [b1, b2], [{"block_id": b1["block_id"], "crop_id": uuid4(), "crop_path": "potato"}]
    )

    out = _impact([mango, potato], [b1, b2], after, changed=[b1["block_id"]])

    block = out["blocks"][0]
    assert [t["code"] for t in block["starting"]] == ["potato"]
    assert [(t["code"], t["other_blocks"]) for t in block["stopping"]] == [("mango", 1)]
    # Mango still runs on b2, so the farm does not lose it.
    assert out["farm_stopping"] == []
    assert [t["code"] for t in out["farm_starting"]] == ["potato"]
    assert out["changes_anything"] is True


def test_an_excluded_tree_that_leaves_the_farm_is_reported_as_cleared() -> None:
    mango = _tree("mango", crops=["mango"])
    any_crop = _tree("any")
    b1 = _block("mango")
    b2 = _block("potato")
    after = apply_block_changes([b1, b2], [{"block_id": b1["block_id"], "removed": True}])

    out = _impact(
        [mango, any_crop],
        [b1, b2],
        after,
        changed=[b1["block_id"]],
        excluded={mango["tree_id"], any_crop["tree_id"]},
    )

    assert [t["code"] for t in out["farm_stopping"]] == ["mango"]
    assert out["farm_stopping"][0]["enabled"] is False
    # The crop-agnostic tree still matches b2, so its "off" stays.
    assert [t["code"] for t in out["exclusions_cleared"]] == ["mango"]


def test_removing_the_last_crop_clears_every_exclusion() -> None:
    any_crop = _tree("any")
    b1 = _block("mango")
    after = apply_block_changes([b1], [{"block_id": b1["block_id"], "crop_path": None}])

    out = _impact([any_crop], [b1], after, changed=[b1["block_id"]], excluded={any_crop["tree_id"]})

    assert out["has_crops_before"] is True
    assert out["has_crops_after"] is False
    assert [t["code"] for t in out["exclusions_cleared"]] == ["any"]


def test_a_country_change_moves_trees_farm_wide() -> None:
    egypt = _tree("eg", countries=["EG"])
    jordan = _tree("jo", countries=["JO"])
    blocks = [_block("mango"), _block("mango")]

    out = _impact([egypt, jordan], blocks, blocks, changed=[], country=("EG", "JO"))

    assert out["blocks"] == []
    assert [(t["code"], t["blocks"]) for t in out["farm_starting"]] == [("jo", 2)]
    assert [t["code"] for t in out["farm_stopping"]] == ["eg"]


def test_a_change_that_moves_nothing_says_so() -> None:
    mango = _tree("mango", crops=["mango"])
    b1 = _block("mango.keitt", soil="clay")
    after = apply_block_changes([b1], [{"block_id": b1["block_id"], "soil_texture": "sandy"}])

    out = _impact([mango], [b1], after, changed=[b1["block_id"]])

    assert out["changes_anything"] is False
    assert isinstance(out["blocks"][0]["block_id"], UUID)
