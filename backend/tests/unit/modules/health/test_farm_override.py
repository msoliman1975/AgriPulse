"""The farm override — the deepest of the three resolution tiers.

    PLATFORM_DEFAULT_DEFINITION
      <- public.crop_health_definitions, merged along the crop path
        <- farms.health_definition

The cases that matter are the ones where the farm must NOT overwrite a key
it never named, and the one where it must overwrite one the crop did.
"""

from __future__ import annotations

import pytest

from app.modules.health.service import CropHealthDefinitions
from app.shared.health_definition import PLATFORM_DEFAULT_DEFINITION, HealthDefinitionError


class TestTheThirdTier:
    def test_the_farm_beats_the_crop(self) -> None:
        cat = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72}},
            farm_override={"stale_after_hours": 12},
        )
        assert cat.for_path("mango.keitt").stale_after_hours == 12

    def test_the_farm_only_overwrites_what_it_names(self) -> None:
        """The reason the override is stored as a partial body. A farm that
        cares about freshness must not silently pin the crop's other values
        and stop tracking the knowledge base for them."""
        cat = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72, "no_tree_coverage": "healthy"}},
            farm_override={"stale_after_hours": 12},
        )
        got = cat.for_path("mango")
        assert got.stale_after_hours == 12  # the farm's
        assert got.no_tree_coverage == "healthy"  # still the crop's

    def test_the_farm_applies_to_a_crop_with_no_file(self) -> None:
        """The override is about the farm's own operations, not agronomy, so
        it reaches every block whatever its crop."""
        cat = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72}},
            farm_override={"stale_after_hours": 12},
        )
        assert cat.for_path("wheat").stale_after_hours == 12

    def test_the_farm_applies_to_a_block_with_no_crop(self) -> None:
        cat = CropHealthDefinitions({}, farm_override={"stale_after_hours": 12})
        assert cat.for_path(None).stale_after_hours == 12

    def test_the_farm_applies_when_the_catalog_is_empty(self) -> None:
        """The crop tier can resolve to nothing at all. The farm still has
        the last word, over the platform default directly."""
        cat = CropHealthDefinitions({}, farm_override={"no_tree_coverage": "healthy"})
        assert cat.for_path("mango").no_tree_coverage == "healthy"

    def test_two_crops_on_one_farm_both_take_the_override(self) -> None:
        cat = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72}, "potato": {"stale_after_hours": 24}},
            farm_override={"stale_after_hours": 6},
        )
        assert cat.for_path("mango.keitt").stale_after_hours == 6
        assert cat.for_path("potato").stale_after_hours == 6

    def test_no_override_changes_nothing(self) -> None:
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}}, farm_override=None)
        assert cat.for_path("mango").stale_after_hours == 72
        assert cat.for_path("wheat") is PLATFORM_DEFAULT_DEFINITION

    def test_an_empty_override_changes_nothing(self) -> None:
        """`{}` and NULL are the same to the resolver. The API stores `{}` as
        NULL so the difference does not survive to be read here, but nothing
        stops an older row holding one."""
        cat = CropHealthDefinitions({"mango": {"stale_after_hours": 72}}, farm_override={})
        assert cat.for_path("mango").stale_after_hours == 72
        assert cat.for_path("wheat") is PLATFORM_DEFAULT_DEFINITION

    def test_a_bad_override_raises_rather_than_being_ignored(self) -> None:
        """The column has no CHECK that can express the schema, so a row
        written by something other than the API — a migration, a fix applied
        by hand — has to fail loudly at read time."""
        cat = CropHealthDefinitions({}, farm_override={"stale_hours": 12})
        with pytest.raises(HealthDefinitionError):
            cat.for_path("mango")

    def test_the_memo_accounts_for_the_override(self) -> None:
        """The cache is keyed on the crop path alone, so the override has to
        be part of the instance. Two catalogs over the same crop must not be
        able to return each other's answer."""
        plain = CropHealthDefinitions({"mango": {"stale_after_hours": 72}})
        overridden = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72}}, farm_override={"stale_after_hours": 12}
        )
        assert plain.for_path("mango").stale_after_hours == 72
        assert overridden.for_path("mango").stale_after_hours == 12
