"""The walker behind the save-time crop-attribute check.

Pure half of the validator: which codes a tree references. The half that
needs a database — are those codes defined for the tree's crops — is covered
in tests/integration/recommendations/test_crop_attribute_refs.py.
"""

from __future__ import annotations

from app.modules.recommendations.loader import collect_crop_attribute_codes


def _cond(tree: dict) -> dict:
    return {"condition": {"tree": tree}}


def test_finds_a_ref_on_either_side_of_a_comparison() -> None:
    nodes = {
        "a": _cond(
            {
                "op": "gt",
                "left": {"source": "crop_attribute", "code": "tree_age", "key": "value"},
                "right": 5,
            }
        ),
    }
    assert collect_crop_attribute_codes(nodes) == {"tree_age"}


def test_walks_nested_groups_and_not_wrappers() -> None:
    nodes = {
        "root": _cond(
            {
                "all_of": [
                    {
                        "op": "eq",
                        "left": {"source": "crop_attribute", "code": "rootstock_type"},
                        "right": "seedling",
                    },
                    {
                        "not": {
                            "any_of": [
                                {
                                    "op": "lt",
                                    "left": {
                                        "source": "crop_attribute",
                                        "code": "graft_union_height_cm",
                                    },
                                    "right": 30,
                                }
                            ]
                        }
                    },
                ]
            }
        ),
    }
    assert collect_crop_attribute_codes(nodes) == {"rootstock_type", "graft_union_height_cm"}


def test_collects_across_every_node_and_dedupes() -> None:
    nodes = {
        "a": _cond(
            {
                "op": "gt",
                "left": {"source": "crop_attribute", "code": "tree_age"},
                "right": 5,
            }
        ),
        "b": _cond(
            {
                "op": "lt",
                "left": {"source": "crop_attribute", "code": "tree_age"},
                "right": 20,
            }
        ),
        "c": _cond(
            {
                "op": "in",
                "left": {"source": "crop_attribute", "code": "nursery_source"},
                "values": ["x", "y"],
            }
        ),
    }
    assert collect_crop_attribute_codes(nodes) == {"tree_age", "nursery_source"}


def test_ignores_other_sources() -> None:
    nodes = {
        "a": _cond(
            {
                "op": "lt",
                "left": {"source": "indices", "index_code": "ndvi", "key": "baseline_deviation"},
                "right": {"source": "params", "name": "threshold"},
            }
        ),
        "b": _cond(
            {
                "op": "eq",
                "left": {"source": "block", "field": "growth_stage"},
                "right": "kimri",
            }
        ),
    }
    assert collect_crop_attribute_codes(nodes) == set()


def test_ignores_a_leaf_outcome() -> None:
    # `crop_attribute` is a value ref; the outcome block holds literals, and
    # a parameter that happens to be named "source" must not be mistaken for
    # a ref.
    nodes = {
        "leaf": {
            "outcome": {
                "action_type": "scout",
                "text_en": "go look",
                "parameters": {"source": "crop_attribute", "code": "not_a_ref"},
            }
        }
    }
    assert collect_crop_attribute_codes(nodes) == set()


def test_skips_a_ref_with_no_usable_code() -> None:
    # A blank code is what the builder emits before the author picks one.
    # Reporting "" as unknown would be a confusing way to say "unfinished".
    nodes = {
        "a": _cond({"op": "gt", "left": {"source": "crop_attribute", "code": ""}, "right": 1}),
        "b": _cond({"op": "gt", "left": {"source": "crop_attribute"}, "right": 1}),
    }
    assert collect_crop_attribute_codes(nodes) == set()


def test_tolerates_a_malformed_nodes_map() -> None:
    assert collect_crop_attribute_codes({}) == set()
    assert collect_crop_attribute_codes({"a": "not a mapping"}) == set()  # type: ignore[dict-item]
    assert collect_crop_attribute_codes({"a": {"condition": None}}) == set()
