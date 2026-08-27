"""Unit tests for the signal-details report.

The SQL itself is exercised by the integration suite; what is checked here is
the part that is easy to get quietly wrong — the truncation flag, and a
per-signal roll-up that must not invent a mean for a non-numeric signal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.modules.reports import service as svc_module
from app.modules.reports.schemas import SignalDetailRow
from app.modules.reports.service import ReportsService
from app.modules.reports.signal_details import TOP_CATEGORIES, signal_detail_stats

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _row(
    *,
    code: str = "trap_count",
    kind: str = "numeric",
    numeric: Decimal | None = None,
    categorical: str | None = None,
    boolean: bool | None = None,
    block_id: UUID | None = None,
    recorded_by: UUID | None = None,
    minutes_ago: int = 0,
) -> SignalDetailRow:
    return SignalDetailRow(
        observation_id=uuid4(),
        observed_at=NOW - timedelta(minutes=minutes_ago),
        recorded_at=NOW,
        signal_code=code,
        signal_name=code.replace("_", " ").title(),
        signal_name_ar=None,
        value_kind=kind,
        unit="count" if kind == "numeric" else None,
        value_numeric=numeric,
        value_categorical=categorical,
        value_boolean=boolean,
        block_id=block_id,
        recorded_by=recorded_by or uuid4(),
        location_mode="entity",
        has_attachment=False,
    )


class TestSignalDetailStats:
    def test_numeric_signal_gets_min_mean_max_and_no_categories(self) -> None:
        block = uuid4()
        rows = [
            _row(numeric=Decimal("10"), block_id=block, minutes_ago=0),
            _row(numeric=Decimal("20"), block_id=block, minutes_ago=30),
            _row(numeric=Decimal("30"), block_id=uuid4(), minutes_ago=60),
        ]
        (stat,) = signal_detail_stats(rows)
        assert stat.observation_count == 3
        assert stat.block_count == 2
        assert stat.min_value == Decimal("10")
        assert stat.max_value == Decimal("30")
        assert stat.mean_value == Decimal("20.0000")
        assert stat.categories == []
        assert stat.first_observed_at == NOW - timedelta(minutes=60)
        assert stat.last_observed_at == NOW

    def test_categorical_signal_gets_a_breakdown_and_no_mean(self) -> None:
        rows = [
            _row(code="pest", kind="categorical", categorical="aphid"),
            _row(code="pest", kind="categorical", categorical="aphid"),
            _row(code="pest", kind="categorical", categorical="mite"),
        ]
        (stat,) = signal_detail_stats(rows)
        # A "mean" over category labels would be meaningless, so there is none.
        assert stat.mean_value is None
        assert [(c.value, c.count) for c in stat.categories] == [("aphid", 2), ("mite", 1)]

    def test_boolean_signal_counts_true_and_false(self) -> None:
        rows = [
            _row(code="flowering", kind="boolean", boolean=True),
            _row(code="flowering", kind="boolean", boolean=False),
            _row(code="flowering", kind="boolean", boolean=False),
        ]
        (stat,) = signal_detail_stats(rows)
        assert [(c.value, c.count) for c in stat.categories] == [("false", 2), ("true", 1)]

    def test_equal_counts_break_ties_on_value(self) -> None:
        rows = [
            _row(code="pest", kind="categorical", categorical="mite"),
            _row(code="pest", kind="categorical", categorical="aphid"),
        ]
        (stat,) = signal_detail_stats(rows)
        assert [c.value for c in stat.categories] == ["aphid", "mite"]

    def test_category_breakdown_is_capped(self) -> None:
        rows = [
            _row(code="pest", kind="categorical", categorical=f"v{i:02d}")
            for i in range(TOP_CATEGORIES + 4)
        ]
        (stat,) = signal_detail_stats(rows)
        assert len(stat.categories) == TOP_CATEGORIES

    def test_groups_by_signal_busiest_first(self) -> None:
        rows = [
            _row(code="quiet", numeric=Decimal("1")),
            _row(code="busy", numeric=Decimal("1")),
            _row(code="busy", numeric=Decimal("2")),
        ]
        assert [s.signal_code for s in signal_detail_stats(rows)] == ["busy", "quiet"]

    def test_farm_level_rows_do_not_count_towards_block_count(self) -> None:
        rows = [
            _row(numeric=Decimal("1"), block_id=None),
            _row(numeric=Decimal("2"), block_id=uuid4()),
        ]
        (stat,) = signal_detail_stats(rows)
        assert stat.block_count == 1


def _service() -> ReportsService:
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    return s


def _raw(index: int) -> dict:
    return {
        "id": uuid4(),
        "observed_at": NOW - timedelta(minutes=index),
        "recorded_at": NOW,
        "signal_code": "trap_count",
        "signal_name": "Trap count",
        "signal_name_ar": None,
        "value_kind": "numeric",
        "unit": "count",
        "unit_ar": None,
        "categorical_values": None,
        "categorical_values_ar": None,
        "value_numeric": Decimal(index),
        "value_categorical": None,
        "value_event": None,
        "value_boolean": None,
        "block_id": uuid4(),
        "block_name": f"Block {index}",
        "block_name_ar": None,
        "crop_path": "mango",
        "notes": None,
        "recorded_by": uuid4(),
        "recorded_by_name": "A Scout",
        "recorded_by_name_ar": None,
        "location_mode": "entity",
        "attachment_s3_key": None,
        "template_observation_id": None,
        "import_batch_id": None,
    }


@pytest.mark.asyncio
class TestSignalDetailsReport:
    async def test_reports_truncation_and_trims_the_probe_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The extra row fetched to detect the cap must not reach the table.

        The stats are computed over the returned rows, so a report that
        silently kept the probe row would present a mean over limit+1 readings
        under a table showing limit of them.
        """
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Orchard"})  # type: ignore[attr-defined]

        captured: dict = {}

        async def fake_select(*_args: object, **kwargs: object) -> list[dict]:
            captured.update(kwargs)
            # One more than the caller's limit: the cap was hit.
            return [_raw(i) for i in range(4)]

        monkeypatch.setattr(svc_module, "select_signal_details", fake_select)
        out = await s.get_signal_details_report(farm_id=farm_id, since=None, until=None, limit=3)

        assert captured["limit"] == 4  # limit + 1 probe
        assert len(out.rows) == 3
        assert out.summary.truncated is True
        assert out.summary.observation_count == 3
        assert out.stats[0].observation_count == 3

    async def test_a_full_page_is_not_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Orchard"})  # type: ignore[attr-defined]

        async def fake_select(*_args: object, **_kwargs: object) -> list[dict]:
            return [_raw(i) for i in range(3)]

        monkeypatch.setattr(svc_module, "select_signal_details", fake_select)
        out = await s.get_signal_details_report(farm_id=farm_id, since=None, until=None, limit=3)
        assert out.summary.truncated is False
        assert len(out.rows) == 3

    async def test_echoes_the_filters_it_ran_with(self, monkeypatch: pytest.MonkeyPatch) -> None:
        farm_id = uuid4()
        block_id = uuid4()
        s = _service()
        s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "Orchard"})  # type: ignore[attr-defined]

        async def fake_select(*_args: object, **_kwargs: object) -> list[dict]:
            return []

        monkeypatch.setattr(svc_module, "select_signal_details", fake_select)
        out = await s.get_signal_details_report(
            farm_id=farm_id,
            since=None,
            until=None,
            signal_codes=["trap_count"],
            block_ids=[block_id],
            min_value=Decimal("5"),
            with_notes_only=True,
        )
        assert out.filters.signal_codes == ["trap_count"]
        assert out.filters.block_ids == [block_id]
        assert out.filters.min_value == Decimal("5")
        assert out.filters.with_notes_only is True
        assert out.summary.observation_count == 0
