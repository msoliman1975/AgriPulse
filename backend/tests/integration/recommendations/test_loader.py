"""Tests for the YAML decision-tree loader.

Pure-fn tests of compile_tree validation; the DB-touching sync_from_disk
flow is covered by the live-tenant smoke check during PR-A development
and is exercised whenever app startup runs in tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.loader import compile_tree

pytestmark = [pytest.mark.integration]


def _load_seed() -> dict[str, object]:
    seed_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "modules"
        / "recommendations"
        / "seeds"
        / "ndvi_baseline_alert_v1.yaml"
    )
    return yaml.safe_load(seed_path.read_text(encoding="utf-8"))


def _minimal_leaf_spec(**extra: object) -> dict[str, object]:
    """A smallest-valid single-leaf tree, with optional extra top-level keys."""
    return {
        "code": "x",
        "name_en": "x",
        "root": "leaf",
        "nodes": {"leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}}},
        **extra,
    }


def _seeds_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def test_seed_yaml_compiles() -> None:
    """One named seed, compiled in full.

    Was `scout_for_stress_v1` until public migration 0073 archived it; this
    now reads `ndvi_baseline_alert_v1`, the remaining crop-agnostic seed.
    `test_all_seed_files_compile` below covers the rest of the catalogue."""
    spec = _load_seed()
    compiled = compile_tree(spec, source_path="seed")
    assert compiled["code"] == "ndvi_baseline_alert_v1"
    assert compiled["root"] == "root"
    assert set(compiled["nodes"]) >= {"root", "severity_gate"}


def test_all_seed_files_compile() -> None:
    """Every shipped seed YAML must compile — guards new catalog entries
    (e.g. the potato static-threshold trees) from shipping malformed."""
    seeds = sorted(_seeds_dir().glob("*.yaml"))
    assert seeds, "no seed YAML files found"
    for path in seeds:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        compiled = compile_tree(spec, source_path=str(path))
        assert compiled["code"], f"{path.name} compiled without a code"


# --- crop_path targeting (crop taxonomy) -------------------------------


def test_crop_path_defaults_to_none() -> None:
    compiled = compile_tree(_minimal_leaf_spec(), source_path="x")
    assert compiled["crop_path"] is None


def test_crop_path_compiles_when_present() -> None:
    compiled = compile_tree(_minimal_leaf_spec(crop_path="mango.alphonso.short"), source_path="x")
    assert compiled["crop_path"] == "mango.alphonso.short"


def test_crop_path_rejects_empty_segment() -> None:
    with pytest.raises(Exception, match="empty segment"):
        compile_tree(_minimal_leaf_spec(crop_path="mango..short"), source_path="x")


def test_crop_path_rejects_non_string() -> None:
    with pytest.raises(Exception, match="crop_path"):
        compile_tree(_minimal_leaf_spec(crop_path=123), source_path="x")


# --- multi-axis targeting (PR-2: crop_paths / country_codes / soil_textures) --


def test_targeting_axes_default_empty() -> None:
    compiled = compile_tree(_minimal_leaf_spec(), source_path="x")
    assert compiled["crop_paths"] == []
    assert compiled["country_codes"] == []
    assert compiled["soil_textures"] == []


def test_crop_paths_list_compiles() -> None:
    compiled = compile_tree(
        _minimal_leaf_spec(crop_paths=["mango", "citrus.valencia"]), source_path="x"
    )
    assert compiled["crop_paths"] == ["mango", "citrus.valencia"]
    # Legacy single column is the first targeted path.
    assert compiled["crop_path"] == "mango"


def test_legacy_crop_path_folds_into_crop_paths() -> None:
    compiled = compile_tree(_minimal_leaf_spec(crop_path="mango"), source_path="x")
    assert compiled["crop_paths"] == ["mango"]


def test_crop_paths_and_legacy_merge_and_dedupe() -> None:
    compiled = compile_tree(
        _minimal_leaf_spec(crop_paths=["mango"], crop_path="mango"), source_path="x"
    )
    assert compiled["crop_paths"] == ["mango"]


def test_country_codes_normalise_to_upper() -> None:
    compiled = compile_tree(_minimal_leaf_spec(country_codes=["eg", "JO"]), source_path="x")
    assert compiled["country_codes"] == ["EG", "JO"]


def test_country_codes_reject_non_alpha2() -> None:
    with pytest.raises(Exception, match="country code"):
        compile_tree(_minimal_leaf_spec(country_codes=["EGY"]), source_path="x")


def test_soil_textures_accept_enum_values() -> None:
    compiled = compile_tree(
        _minimal_leaf_spec(soil_textures=["sandy", "clay_loam"]), source_path="x"
    )
    assert compiled["soil_textures"] == ["sandy", "clay_loam"]


def test_soil_textures_reject_unknown_value() -> None:
    with pytest.raises(Exception, match="soil texture"):
        compile_tree(_minimal_leaf_spec(soil_textures=["mud"]), source_path="x")


# --- execution scope (PR-C1: block | cell) ---------------------------------


def test_scope_defaults_to_block() -> None:
    assert compile_tree(_minimal_leaf_spec(), source_path="x")["scope"] == "block"


def test_scope_cell_compiles() -> None:
    assert compile_tree(_minimal_leaf_spec(scope="cell"), source_path="x")["scope"] == "cell"


def test_scope_rejects_unknown_value() -> None:
    with pytest.raises(Exception, match="scope"):
        compile_tree(_minimal_leaf_spec(scope="pixel"), source_path="x")


# --- evidence / transferability provenance blocks (KB P1-A) -----------


def test_seed_carries_evidence_and_transferability() -> None:
    compiled = compile_tree(_load_seed(), source_path="seed")
    assert compiled["evidence"]["confidence"] == "high"
    assert compiled["evidence"]["citations"]  # at least one citation
    assert compiled["transferability"]["egypt"] == "high"


def test_provenance_blocks_default_to_none() -> None:
    compiled = compile_tree(_minimal_leaf_spec(), source_path="x")
    assert compiled["evidence"] is None
    assert compiled["transferability"] is None


def test_evidence_block_parses_citations() -> None:
    compiled = compile_tree(
        _minimal_leaf_spec(
            evidence={
                "confidence": "medium",
                "notes": "contested above 40C",
                "citations": [
                    {"source_type": "fao", "title": "FAO bulletin", "year": 2019},
                ],
            }
        ),
        source_path="x",
    )
    cite = compiled["evidence"]["citations"][0]
    assert cite["source_type"] == "fao"
    assert cite["title"] == "FAO bulletin"
    assert cite["doi"] is None


def test_evidence_rejects_unknown_confidence() -> None:
    with pytest.raises(DecisionTreeParseError, match="evidence 'confidence'"):
        compile_tree(
            _minimal_leaf_spec(evidence={"confidence": "rock_solid"}),
            source_path="x",
        )


def test_evidence_rejects_citation_without_title() -> None:
    with pytest.raises(DecisionTreeParseError, match="non-empty 'title'"):
        compile_tree(
            _minimal_leaf_spec(
                evidence={
                    "confidence": "high",
                    "citations": [{"source_type": "peer_reviewed"}],
                }
            ),
            source_path="x",
        )


def test_evidence_rejects_unknown_source_type() -> None:
    with pytest.raises(DecisionTreeParseError, match="source_type"):
        compile_tree(
            _minimal_leaf_spec(
                evidence={
                    "confidence": "high",
                    "citations": [{"source_type": "blog", "title": "t"}],
                }
            ),
            source_path="x",
        )


def test_transferability_rejects_unknown_region() -> None:
    with pytest.raises(DecisionTreeParseError, match="region"):
        compile_tree(
            _minimal_leaf_spec(transferability={"mars": "high"}),
            source_path="x",
        )


def test_transferability_rejects_unknown_grade() -> None:
    with pytest.raises(DecisionTreeParseError, match="transferability"):
        compile_tree(
            _minimal_leaf_spec(transferability={"egypt": "excellent"}),
            source_path="x",
        )


def test_transferability_missing_region_normalizes_to_none() -> None:
    compiled = compile_tree(
        _minimal_leaf_spec(transferability={"egypt": "high"}),
        source_path="x",
    )
    assert compiled["transferability"]["egypt"] == "high"
    assert compiled["transferability"]["global"] is None


# --- 4-horizon outcome actions (KB P1-B) ------------------------------


def _leaf_with_actions(actions: object) -> dict[str, object]:
    return {
        "code": "x",
        "name_en": "x",
        "root": "leaf",
        "nodes": {
            "leaf": {
                "outcome": {
                    "action_type": "scout",
                    "text_en": "x",
                    "actions": actions,
                }
            }
        },
    }


def test_seed_actions_compile() -> None:
    # The scout seed demonstrates the actions block on its critical leaf.
    compiled = compile_tree(_load_seed(), source_path="seed")
    crit = compiled["nodes"]["leaf_scout_critical"]["outcome"]["actions"]
    assert crit["immediate"][0]["text_en"]


def test_actions_valid_block_compiles() -> None:
    compile_tree(
        _leaf_with_actions(
            {
                "immediate": [{"text_en": "now", "text_ar": "الآن"}],
                "long_term": [{"text_en": "later"}],
            }
        ),
        source_path="x",
    )


def test_actions_rejects_unknown_horizon() -> None:
    with pytest.raises(DecisionTreeParseError, match="horizon"):
        compile_tree(
            _leaf_with_actions({"someday": [{"text_en": "x"}]}),
            source_path="x",
        )


def test_actions_rejects_item_without_text_en() -> None:
    with pytest.raises(DecisionTreeParseError, match="text_en"):
        compile_tree(
            _leaf_with_actions({"immediate": [{"text_ar": "only ar"}]}),
            source_path="x",
        )


def test_actions_rejects_non_list_horizon() -> None:
    with pytest.raises(DecisionTreeParseError, match="must be a list"):
        compile_tree(
            _leaf_with_actions({"immediate": {"text_en": "x"}}),
            source_path="x",
        )


def test_compile_rejects_missing_code() -> None:
    with pytest.raises(DecisionTreeParseError, match="missing 'code'"):
        compile_tree(
            {
                "name_en": "x",
                "nodes": {"root": {"outcome": {"action_type": "no_action", "text_en": "x"}}},
            },
            source_path="x",
        )


def test_compile_rejects_missing_root_node() -> None:
    with pytest.raises(DecisionTreeParseError, match="root"):
        compile_tree(
            {
                "code": "x",
                "name_en": "x",
                "root": "missing_id",
                "nodes": {
                    "some_other_id": {"outcome": {"action_type": "no_action", "text_en": "x"}}
                },
            },
            source_path="x",
        )


def test_compile_rejects_dangling_pointer() -> None:
    with pytest.raises(DecisionTreeParseError, match="not a known node"):
        compile_tree(
            {
                "code": "x",
                "name_en": "x",
                "root": "root",
                "nodes": {
                    "root": {
                        "condition": {
                            "tree": {
                                "op": "lt",
                                "left": {
                                    "source": "indices",
                                    "index_code": "ndvi",
                                    "key": "baseline_deviation",
                                },
                                "right": 0,
                            }
                        },
                        "on_match": "missing_target",
                        "on_miss": "leaf",
                    },
                    "leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}},
                },
            },
            source_path="x",
        )


def test_compile_rejects_leaf_missing_outcome_action_type() -> None:
    with pytest.raises(DecisionTreeParseError, match="action_type"):
        compile_tree(
            {
                "code": "x",
                "name_en": "x",
                "root": "leaf",
                "nodes": {"leaf": {"outcome": {"text_en": "x"}}},
            },
            source_path="x",
        )
