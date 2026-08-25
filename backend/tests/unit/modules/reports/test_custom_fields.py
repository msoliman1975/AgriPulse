"""Unit tests for custom (tenant-defined) report columns.

Covers the pure ref parsing, the definition resolution that turns a picked ref
back into a renderable column, and the wiring that attaches a value to a block
row — including the block that has no value, which must come back as an absent
key rather than as a zero.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports import custom_fields as cf_module
from app.modules.reports import service as svc_module
from app.modules.reports.custom_fields import (
    MAX_CUSTOM_FIELDS,
    CustomFieldRef,
    parse_field_refs,
)
from app.modules.reports.schemas import CustomFieldDef, CustomFieldValue
from app.modules.reports.service import ReportsService


class TestParseFieldRefs:
    def test_empty_input(self) -> None:
        assert parse_field_refs(None) == []
        assert parse_field_refs("") == []
        assert parse_field_refs("   ") == []

    def test_parses_both_sources_and_keeps_order(self) -> None:
        refs = parse_field_refs("signal:trap_count,crop_attribute:brix")
        assert [r.key for r in refs] == ["signal:trap_count", "crop_attribute:brix"]
        assert refs[0].source == "signal"
        assert refs[1].code == "brix"

    def test_tolerates_whitespace(self) -> None:
        refs = parse_field_refs(" crop_attribute:brix ,  signal:trap_count ")
        assert [r.key for r in refs] == ["crop_attribute:brix", "signal:trap_count"]

    def test_drops_junk_rather_than_raising(self) -> None:
        # A report URL is bookmarked and shared; a 422 on a stale or malformed
        # column would break the bookmark instead of telling anybody anything.
        refs = parse_field_refs("nosuchsource:x,crop_attribute:,:y,plain,crop_attribute:ok")
        assert [r.key for r in refs] == ["crop_attribute:ok"]

    def test_collapses_duplicates_to_first_occurrence(self) -> None:
        refs = parse_field_refs("signal:a,signal:a,crop_attribute:a")
        assert [r.key for r in refs] == ["signal:a", "crop_attribute:a"]

    def test_caps_the_column_count(self) -> None:
        raw = ",".join(f"signal:s{i}" for i in range(MAX_CUSTOM_FIELDS + 5))
        assert len(parse_field_refs(raw)) == MAX_CUSTOM_FIELDS


def _service() -> ReportsService:
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    return s


def _def(key: str, name: str) -> CustomFieldDef:
    source, _, code = key.partition(":")
    return CustomFieldDef(
        key=key,
        source=source,  # type: ignore[arg-type]
        code=code,
        name_en=name,
        value_type="decimal" if source == "crop_attribute" else "numeric",
    )


@pytest.mark.asyncio
class TestCustomFieldDefs:
    async def test_returns_picked_columns_in_picker_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _service()

        async def fake_list(*_args: object, **_kwargs: object) -> list[CustomFieldDef]:
            # Catalog order is alphabetical by label; the caller asked for the
            # reverse, and the response must follow the caller.
            return [_def("crop_attribute:brix", "Brix"), _def("signal:trap", "Trap count")]

        monkeypatch.setattr(svc_module, "list_custom_fields", fake_list)
        out = await s._custom_field_defs(
            farm_id=uuid4(),
            refs=[
                CustomFieldRef(source="signal", code="trap"),
                CustomFieldRef(source="crop_attribute", code="brix"),
            ],
        )
        assert [d.key for d in out] == ["signal:trap", "crop_attribute:brix"]

    async def test_drops_a_ref_the_farm_no_longer_offers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _service()

        async def fake_list(*_args: object, **_kwargs: object) -> list[CustomFieldDef]:
            return [_def("crop_attribute:brix", "Brix")]

        monkeypatch.setattr(svc_module, "list_custom_fields", fake_list)
        out = await s._custom_field_defs(
            farm_id=uuid4(),
            refs=[
                CustomFieldRef(source="signal", code="retired"),
                CustomFieldRef(source="crop_attribute", code="brix"),
            ],
        )
        assert [d.key for d in out] == ["crop_attribute:brix"]

    async def test_no_refs_means_no_catalog_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = _service()
        called = False

        async def fake_list(*_args: object, **_kwargs: object) -> list[CustomFieldDef]:
            nonlocal called
            called = True
            return []

        monkeypatch.setattr(svc_module, "list_custom_fields", fake_list)
        assert await s._custom_field_defs(farm_id=uuid4(), refs=[]) == []
        assert called is False


@pytest.mark.asyncio
class TestCropHealthCarriesCustomColumns:
    async def test_attaches_values_and_leaves_a_valueless_block_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        farm_id = uuid4()
        with_value, without_value = uuid4(), uuid4()
        now = datetime(2026, 5, 30, tzinfo=UTC)

        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Orchard"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"id": with_value, "name": "A-Has-Brix"},
                {"id": without_value, "name": "B-No-Brix"},
            ]
        )

        async def fake_stats(*_args: object, **_kwargs: object) -> dict:
            return {
                with_value: {
                    "scene_count": 1,
                    "min_mean": Decimal("0.5"),
                    "max_mean": Decimal("0.5"),
                    "avg_valid_pct": Decimal("99"),
                    "avg_cloud_pct": Decimal("1"),
                    "last_time": now,
                    "last_mean": Decimal("0.5"),
                    "last_p10": Decimal("0.4"),
                    "last_p50": Decimal("0.5"),
                    "last_p90": Decimal("0.6"),
                    "last_z": Decimal("0.1"),
                    "first_mean": Decimal("0.5"),
                }
            }

        async def fake_crops(*_args: object, **_kwargs: object) -> dict:
            return {}

        async def fake_values(*_args: object, **_kwargs: object) -> dict:
            return {
                with_value: {
                    "crop_attribute:brix": CustomFieldValue(
                        key="crop_attribute:brix",
                        source="crop_attribute",
                        code="brix",
                        value_numeric=Decimal("14.5"),
                    )
                }
            }

        async def fake_list(*_args: object, **_kwargs: object) -> list[CustomFieldDef]:
            return [_def("crop_attribute:brix", "Brix")]

        monkeypatch.setattr(svc_module, "_select_crop_health_stats", fake_stats)
        monkeypatch.setattr(svc_module, "_select_block_current_crops", fake_crops)
        monkeypatch.setattr(svc_module, "load_custom_values", fake_values)
        monkeypatch.setattr(svc_module, "list_custom_fields", fake_list)

        out = await s.get_crop_health_report(
            farm_id=farm_id,
            index_code="ndvi",
            since=None,
            until=None,
            fields="crop_attribute:brix",
        )

        assert [d.key for d in out.custom_fields] == ["crop_attribute:brix"]
        rows = {r.block_name: r for r in out.blocks}
        assert rows["A-Has-Brix"].custom["crop_attribute:brix"].value_numeric == Decimal("14.5")
        # The block with no value carries an empty map, not a zero — the two
        # read very differently in a Brix column.
        assert rows["B-No-Brix"].custom == {}

    async def test_no_fields_param_skips_both_queries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A report nobody customised must not pay for the feature."""
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Orchard"})  # type: ignore[attr-defined]
        s._farms.list_blocks = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        catalog_calls = 0

        async def fake_stats(*_args: object, **_kwargs: object) -> dict:
            return {}

        async def fake_crops(*_args: object, **_kwargs: object) -> dict:
            return {}

        async def fake_list(*_args: object, **_kwargs: object) -> list[CustomFieldDef]:
            nonlocal catalog_calls
            catalog_calls += 1
            return []

        monkeypatch.setattr(svc_module, "_select_crop_health_stats", fake_stats)
        monkeypatch.setattr(svc_module, "_select_block_current_crops", fake_crops)
        monkeypatch.setattr(svc_module, "list_custom_fields", fake_list)

        out = await s.get_crop_health_report(
            farm_id=farm_id, index_code="ndvi", since=None, until=None
        )
        assert out.custom_fields == []
        assert catalog_calls == 0


class TestAttributeOptions:
    def test_none_for_a_non_select(self) -> None:
        assert cf_module._attribute_options(None) is None
        assert cf_module._attribute_options([]) is None

    def test_maps_options_and_survives_a_malformed_entry(self) -> None:
        # The column is JSONB, so a hand-written seed can put anything in it.
        # One bad entry should cost that option, not the whole report.
        out = cf_module._attribute_options(
            [
                {"code": "drip", "name_en": "Drip", "name_ar": "تنقيط"},
                {"name_en": "no code"},
                "not a dict",
                {"code": "flood"},
            ]
        )
        assert out is not None
        assert [o.code for o in out] == ["drip", "flood"]
        assert out[0].name_ar == "تنقيط"
        # No name_en on the row falls back to the code rather than to None.
        assert out[1].name_en == "flood"
