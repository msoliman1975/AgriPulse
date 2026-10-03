"""The platform tier read from the database (public migration 0095).

Covers:
  * the migration's platform body equals the code defaults it replaces, so
    the migration moves no block;
  * a platform body is the base every other tier sits on;
  * the platform's rollup rule maps the same way the tenant's does;
  * the admin routes' body checks: the platform names every key and never
    `cell_rollup`, a crop names any subset, both pass `parse_definition`;
  * what a crop path inherits, key by key, and from where.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.health.admin_router import (
    PLATFORM_KEYS,
    InvalidHealthBodyError,
    check_crop_body,
    check_platform_body,
    inherited_for,
)
from app.modules.health.service import (
    CropHealthDefinitions,
    platform_rollup,
    tenant_tier_from_settings,
)
from app.shared.health_definition import PLATFORM_DEFAULT_DEFINITION, parse_definition

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "public"
    / "versions"
    / "0095_health_definitions_editable.py"
)


def _migration_body() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("m0095", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.PLATFORM_BODY)


def _platform(**changes: Any) -> dict[str, Any]:
    return {**_migration_body(), **changes}


def _settings(rollup: str, share: int, *, overridden: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "key": "health.cell_rollup",
            "value": rollup,
            "platform_value": rollup,
            "overridden": overridden,
        },
        {
            "key": "health.cell_share_pct",
            "value": str(share),
            "platform_value": str(share),
            "overridden": False,
        },
    ]


class TestMigrationBody:
    def test_equals_the_code_defaults(self) -> None:
        assert parse_definition(_migration_body()) == PLATFORM_DEFAULT_DEFINITION

    def test_names_every_platform_key(self) -> None:
        assert set(_migration_body()) == PLATFORM_KEYS


class TestPlatformTier:
    def test_platform_body_decides_when_nothing_else_does(self) -> None:
        cat = CropHealthDefinitions(
            {}, platform=_platform(stale_after_hours=96), platform_version=3
        )
        got = cat.for_path("wheat")
        assert got.source == "platform"
        assert got.version == 3
        assert got.crop_path is None
        assert got.definition.stale_after_hours == 96

    def test_crop_row_sits_on_the_platform_body(self) -> None:
        cat = CropHealthDefinitions(
            {"mango": {"stale_after_hours": 72}},
            platform=_platform(no_tree_coverage="healthy"),
        )
        got = cat.for_path("mango.keitt").definition
        assert got.stale_after_hours == 72
        assert got.no_tree_coverage == "healthy"

    def test_no_platform_row_falls_back_to_the_code_defaults(self) -> None:
        got = CropHealthDefinitions({}).for_path("mango")
        assert got.definition is PLATFORM_DEFAULT_DEFINITION
        assert got.version is None


class TestPlatformRollup:
    def test_worst_sets_no_share(self) -> None:
        assert platform_rollup(_settings("worst", 20)) == {"cell_rollup": "worst"}

    def test_share_sets_the_share_as_a_fraction(self) -> None:
        got = platform_rollup(_settings("share", 35))
        assert got["cell_rollup"] == "share"
        assert Decimal(got["cell_critical_share"]) == Decimal("0.35")

    def test_missing_keys_give_nothing(self) -> None:
        assert platform_rollup([]) == {}

    def test_tenant_tier_still_needs_an_override(self) -> None:
        assert tenant_tier_from_settings(_settings("share", 35)) is None
        assert tenant_tier_from_settings(_settings("share", 35, overridden=True)) == {
            "cell_rollup": "share",
            "cell_critical_share": "0.35",
        }


class TestPlatformBodyCheck:
    def test_accepts_the_migration_body(self) -> None:
        check_platform_body(_migration_body())

    def test_refuses_a_missing_key(self) -> None:
        body = _migration_body()
        del body["snoozed_as"]
        with pytest.raises(InvalidHealthBodyError, match="snoozed_as"):
            check_platform_body(body)

    def test_refuses_cell_rollup_and_names_where_it_lives(self) -> None:
        with pytest.raises(InvalidHealthBodyError, match=r"health\.cell_rollup"):
            check_platform_body(_platform(cell_rollup="share"))

    def test_refuses_a_value_the_resolver_refuses(self) -> None:
        with pytest.raises(InvalidHealthBodyError, match="stale_after_hours"):
            check_platform_body(_platform(stale_after_hours=0))


class TestCropBodyCheck:
    def test_accepts_a_partial_body(self) -> None:
        check_crop_body({"stale_after_hours": 72})

    def test_accepts_an_empty_body(self) -> None:
        check_crop_body({})

    def test_accepts_a_rollup(self) -> None:
        check_crop_body({"cell_rollup": "most_common"})

    def test_refuses_an_unknown_key(self) -> None:
        with pytest.raises(InvalidHealthBodyError, match="stale_hours"):
            check_crop_body({"stale_hours": 72})

    def test_refuses_version(self) -> None:
        with pytest.raises(InvalidHealthBodyError, match="version"):
            check_crop_body({"version": 2})


class TestInherited:
    def test_a_crop_inherits_the_platform(self) -> None:
        got = inherited_for("mango", platform={"stale_after_hours": 48}, crops={})
        assert got["stale_after_hours"].value == 48
        assert got["stale_after_hours"].source == "platform"

    def test_a_variety_inherits_its_crop_and_not_itself(self) -> None:
        got = inherited_for(
            "mango.keitt",
            platform={"stale_after_hours": 48, "no_tree_coverage": "unknown"},
            crops={"mango": {"stale_after_hours": 72}, "mango.keitt": {"stale_after_hours": 24}},
        )
        assert got["stale_after_hours"].value == 72
        assert got["stale_after_hours"].source == "mango"
        assert got["no_tree_coverage"].source == "platform"

    def test_paths_compare_whole_segments(self) -> None:
        got = inherited_for(
            "date_palm.medjool",
            platform={"stale_after_hours": 48},
            crops={"date": {"stale_after_hours": 1}},
        )
        assert got["stale_after_hours"].source == "platform"
