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
        / "scout_for_stress_v1.yaml"
    )
    return yaml.safe_load(seed_path.read_text(encoding="utf-8"))


def test_seed_yaml_compiles() -> None:
    spec = _load_seed()
    compiled = compile_tree(spec, source_path="seed")
    assert compiled["code"] == "scout_for_stress_v1"
    assert compiled["root"] == "root"
    assert set(compiled["nodes"]) >= {"root", "severity_check", "leaf_no_action"}


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
