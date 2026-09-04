"""Picking the definition that judges a block.

The rule is shallow merge along the crop path, deepest level winning per
key, then `parse_definition` over the merged body — the same rule
`app.modules.farms.crop_thresholds.resolve_thresholds` already applies to
the catalog's other inherited defaults.

The cases that matter are the ones where a shallow level must NOT overwrite
a deep one, and the ones where a path that looks like a prefix is not one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.health.service import CropHealthDefinitions
from app.shared.health_definition import PLATFORM_DEFAULT_DEFINITION, HealthDefinitionError


class TestResolution:
    def test_no_catalog_means_the_platform_default(self) -> None:
        assert CropHealthDefinitions({}).for_path("mango").definition is PLATFORM_DEFAULT_DEFINITION

    def test_a_crop_with_no_file_gets_the_platform_default(self) -> None:
        """Most crops have no file and never will. They must be untouched,
        not Unknown and not an error."""
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        assert cat.for_path("wheat").definition is PLATFORM_DEFAULT_DEFINITION

    def test_a_block_with_no_crop_gets_the_platform_default(self) -> None:
        """An unassigned block still has alerts, and whether a tree ran on
        it is still the question. It is not an error and not Unknown."""
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        assert cat.for_path(None).definition is PLATFORM_DEFAULT_DEFINITION

    def test_the_crop_level_reaches_every_variety(self) -> None:
        """`crops.classification_depth` is `variety` for mango, so a block
        carries `mango.<variety>`. A file authored at `mango` has to reach
        it, or the shipped seed would apply to nothing."""
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        assert cat.for_path("mango.keitt").definition.stale_after_hours == 72
        assert cat.for_path("mango.tommy_atkins.short").definition.stale_after_hours == 72

    def test_the_deeper_level_wins_per_key(self) -> None:
        cat = CropHealthDefinitions(
            {
                "mango": {"stale_after_hours": 72, "no_tree_coverage": "unknown"},
                "mango.keitt": {"stale_after_hours": 24},
            }
        )
        got = cat.for_path("mango.keitt")
        assert got.definition.stale_after_hours == 24  # the variety's
        assert got.definition.no_tree_coverage == "unknown"  # inherited from the crop
        # The deepest row that applied is the one reported, so "edit the rule
        # that did this" points at the variety and not at the crop.
        assert got.crop_path == "mango.keitt"

    def test_a_key_neither_level_names_comes_from_the_platform(self) -> None:
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        got = cat.for_path("mango")
        assert got.definition.counted_statuses == PLATFORM_DEFAULT_DEFINITION.counted_statuses
        assert got.definition.severity_map == PLATFORM_DEFAULT_DEFINITION.severity_map

    def test_a_variety_file_alone_does_not_reach_its_siblings(self) -> None:
        cat = CropHealthDefinitions({"mango.keitt": {"stale_after_hours": 24}})
        assert cat.for_path("mango.keitt").definition.stale_after_hours == 24
        assert cat.for_path("mango.alphonso").definition is PLATFORM_DEFAULT_DEFINITION

    def test_a_crop_whose_code_is_a_prefix_of_another_does_not_inherit(self) -> None:
        """`citrus_orange` starts with the same letters as nothing here, but
        the shape is the trap: crop codes carry underscores, and `_` is a
        single-character wildcard in SQL LIKE. Resolution splits on "." and
        compares whole segments, so a pattern match can never leak."""
        cat = CropHealthDefinitions({"date_palm": {"stale_after_hours": 72}})
        assert cat.for_path("date_palm").definition.stale_after_hours == 72
        assert cat.for_path("dateXpalm").definition is PLATFORM_DEFAULT_DEFINITION
        assert cat.for_path("date").definition is PLATFORM_DEFAULT_DEFINITION

    def test_a_longer_crop_name_is_not_a_child_of_a_shorter_one(self) -> None:
        # "citrus_mandarin" is not under "citrus": there is no "citrus" crop,
        # and even if there were, the segments differ.
        cat = CropHealthDefinitions({"citrus": {"stale_after_hours": 72}})
        assert cat.for_path("citrus_mandarin").definition is PLATFORM_DEFAULT_DEFINITION

    def test_the_answer_is_memoised_and_stable(self) -> None:
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        first = cat.for_path("mango.keitt")
        assert cat.for_path("mango.keitt") is first

    def test_a_body_this_version_cannot_read_raises(self) -> None:
        """The row is written by a loader that may be older than the process
        reading it. A key this version does not know must be loud, not a
        constructor TypeError from somewhere further down."""
        cat = CropHealthDefinitions({"mango": {"from_a_future_release": 1}})
        with pytest.raises(HealthDefinitionError):
            cat.for_path("mango")


class TestTypes:
    def test_a_share_from_jsonb_survives_as_a_decimal(self) -> None:
        """JSONB gives back a float. The definition compares it against a
        Decimal share, and mixing the two is where the comparison would
        either raise or quietly round."""
        cat = CropHealthDefinitions({"mango": {"cell_critical_share": 0.25}})
        got = cat.for_path("mango")
        assert got.definition.cell_critical_share == Decimal("0.25")
