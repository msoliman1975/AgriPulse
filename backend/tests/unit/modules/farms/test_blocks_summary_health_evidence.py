"""Blocks summary — the evidence the bounded health definition reads.

Phase 3 gathers the inputs and reports them; it does not switch the rule.
So every test here asserts two things at once: what `health_evidence`
says, and that `health` is still whatever the NDVI rule made it. A change
that quietly flipped the shipped class would fail these.

The composition is what is covered. The SQL is exercised by the
integration suite for this endpoint; here the rows are handed in, because
the way a block silently gets someone else's evidence is the dict keying,
not the query.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.farms.blocks_summary_router import get_blocks_summary


@pytest.fixture
def _definition_on(monkeypatch: pytest.MonkeyPatch):
    """Turn `health_definition_enabled` on for one test.

    Env plus `cache_clear`, the way this repo flips every other flag:
    `get_settings` is an lru_cache, so setting the variable alone changes
    nothing and the test would silently exercise the off path.
    """
    monkeypatch.setenv("HEALTH_DEFINITION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


def _session(*result_sets: list[Any]) -> AsyncMock:
    """Results in call order. See `test_blocks_summary_grid._session` for
    the full list; the order is the same and is positional."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(rows) for rows in result_sets])
    return session


def _alert(block_id: Any, severity: str, status: str, cell_id: Any = None, n: int = 1) -> dict:
    return {
        "block_id": block_id,
        "severity": severity,
        "status": status,
        "cell_id": cell_id,
        "n": n,
    }


def _traces(
    block_id: Any,
    *,
    fired: int = 0,
    clear: int = 0,
    skipped: int = 0,
    error: int = 0,
    at: datetime | None = None,
) -> dict:
    return {
        "block_id": block_id,
        "traces_fired": fired,
        "traces_clear": clear,
        "traces_skipped": skipped,
        "traces_error": error,
        "last_evaluated_at": at,
    }


@pytest.mark.asyncio
class TestHealthEvidence:
    async def test_a_block_the_sweep_never_reached_is_unknown_not_healthy(self) -> None:
        """No alert is not the same as no problem.

        This block has nothing: no alert, no trace. The old rule reads its
        NDVI and answers. The definition refuses to, because nothing looked.
        """
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],  # badge rollup
            [],  # alert evidence
            [],  # recommendation confidence
            [],  # trace counts
            [],  # grid cell counts
            [],  # grid configs
            [b1],  # roster
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.7, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.health == "healthy"  # the shipped NDVI rule, untouched
        assert unit.health_evidence.preview_health == "unknown"
        assert unit.health_evidence.preview_reason == "no_coverage"

    async def test_a_clear_fresh_sweep_is_healthy_at_an_ndvi_the_old_rule_calls_critical(
        self,
    ) -> None:
        """The whole reason for the project, in one case.

        A wide-spaced mango orchard on desert soil averages under 0.40 NDVI
        and the shipped rule calls it Critical for its whole life. Every tree
        that ran on it came out clear, this morning. The definition says
        healthy, and names why.
        """
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=21, at=now - timedelta(hours=6))],
            [],  # grid cell counts
            [],  # grid configs
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.health == "critical"
        assert unit.health_evidence.preview_health == "healthy"
        assert unit.health_evidence.preview_reason == "all_clear"
        assert unit.health_evidence.traces_clear == 21

    async def test_an_old_sweep_makes_the_healthy_answer_unknown(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=4, at=now - timedelta(hours=72))],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_reason == "stale"
        assert out.units[0].health_evidence.preview_health == "unknown"

    async def test_a_stale_sweep_never_hides_an_open_critical(self) -> None:
        """Freshness gates the healthy answer only. A real finding on a block
        nobody has swept for a week is still a real finding."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [_alert(b1, "critical", "open")],
            [],
            [_traces(b1, fired=1, at=now - timedelta(days=7))],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_health == "critical"
        assert out.units[0].health_evidence.preview_reason == "critical_alert"

    async def test_every_tree_skipped_reads_no_tree(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, skipped=19, at=now)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        # The platform default answers "unknown" here: no tree applies, so
        # nothing has an opinion about this block.
        assert out.units[0].health_evidence.preview_reason == "no_tree"
        assert out.units[0].health_evidence.preview_health == "unknown"

    async def test_the_counters_include_alerts_the_badge_deliberately_drops(self) -> None:
        """`alert_count` is open, warning-or-critical. The evidence counters
        are wider on purpose, and the two must be allowed to disagree."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            # The badge sees nothing: this block's only alert is acknowledged.
            [],
            [
                _alert(b1, "critical", "acknowledged"),
                _alert(b1, "info", "open", n=3),
            ],
            [],
            [_traces(b1, fired=1, at=now)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        ev = out.units[0].health_evidence
        assert out.units[0].alert_count == 0
        assert ev.alerts_by_status == {"acknowledged": 1, "open": 3}
        assert ev.alerts_by_severity == {"critical": 1, "info": 3}
        # Acknowledged means somebody saw it, not that the block recovered.
        assert ev.preview_health == "critical"

    async def test_cell_scoped_criticals_are_counted_distinctly_against_the_grid(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        c1, c2 = uuid4(), uuid4()
        product = uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [
                _alert(b1, "critical", "open", cell_id=c1, n=2),
                _alert(b1, "critical", "open", cell_id=c2),
            ],
            [],
            [_traces(b1, fired=2, at=now)],
            [{"block_id": b1, "total_cells": 121}],  # grid cell counts
            [{"block_id": b1, "product_id": product}],  # grid configs
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        ev = out.units[0].health_evidence
        # Three rows, two cells. The share test counts cells, not alerts.
        assert ev.critical_cells == 2
        assert ev.total_cells == 121
        assert ev.alerts_by_severity == {"critical": 3}
        # The platform default sets no share, so one critical cell is enough.
        assert ev.preview_health == "critical"

    async def test_evidence_does_not_leak_between_blocks(self) -> None:
        farm_id, loud, quiet = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [_alert(loud, "critical", "open")],
            [{"block_id": loud, "max_confidence": 0.9}],
            [_traces(loud, fired=1, at=now), _traces(quiet, clear=3, at=now)],
            [],
            [],
            [loud, quiet],
            [
                {"block_id": loud, "index_code": "ndvi", "mean": 0.8, "time": now},
                {"block_id": quiet, "index_code": "ndvi", "mean": 0.8, "time": now},
            ],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        by_id = {u.id: u.health_evidence for u in out.units}
        assert by_id[loud].preview_health == "critical"
        assert by_id[loud].max_recommendation_confidence == pytest.approx(0.9)
        assert by_id[quiet].preview_health == "healthy"
        assert by_id[quiet].alerts_by_severity == {}
        assert by_id[quiet].max_recommendation_confidence is None

    async def test_a_naive_at_does_not_crash_the_freshness_test(self) -> None:
        """`at` arrives from a query string and may carry no offset. The
        resolver subtracts it from a timestamptz, so it has to be stamped."""
        farm_id, b1 = uuid4(), uuid4()
        naive = datetime(2026, 9, 1, 12, 0, 0)
        swept = datetime(2026, 9, 1, 6, 0, 0, tzinfo=UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=2, at=swept)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": swept}],
        )

        out = await get_blocks_summary(
            farm_id=farm_id, at=naive, context=None, tenant_session=session
        )

        assert out.units[0].health_evidence.preview_health == "healthy"
        # The echo is left exactly as the caller sent it; only the resolver's
        # own clock is normalised.
        assert out.as_of == naive


@pytest.mark.asyncio
class TestTheSwitch:
    """`health_definition_enabled` — which of the two answers ships.

    The preview is asserted alongside `health` in every case, because the
    promise the flag makes is that turning it on delivers exactly what the
    off state was already reporting. A test that only checked `health`
    would pass while the two drifted.
    """

    async def test_off_by_default_the_answer_is_still_ndvi(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=12, at=now)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.health == "critical"  # 0.31 is under the 0.40 break point
        assert unit.health_reason is None  # the NDVI rule has no reason to give
        assert unit.health_evidence.preview_health == "healthy"

    @pytest.mark.usefixtures("_definition_on")
    async def test_on_the_answer_is_the_definition_and_it_carries_a_reason(self) -> None:
        """The mango orchard stops being Critical for its greenness."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=12, at=now)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        unit = out.units[0]
        assert unit.health == "healthy"
        assert unit.health_reason == "all_clear"
        # The switch delivers exactly what the off state advertised.
        assert unit.health_evidence.preview_health == unit.health
        assert unit.health_evidence.preview_reason == unit.health_reason

    @pytest.mark.usefixtures("_definition_on")
    async def test_on_a_block_nobody_swept_turns_unknown_not_green(self) -> None:
        """The direction of the change a tenant has to be warned about.

        Healthy NDVI and no alert used to read Healthy. It now reads
        Unknown, because nothing looked. That is the truth arriving late,
        and it will be reported as a regression if nobody says so first.
        """
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.82, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health == "unknown"
        assert out.units[0].health_reason == "no_coverage"

    @pytest.mark.usefixtures("_definition_on")
    async def test_on_the_ndvi_value_is_still_reported(self) -> None:
        """NDVI leaves the RULE, not the response. The dock charts it and
        the scorecard shows the number; dropping it would blank both."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            [],
            [],
            [],
            [_traces(b1, clear=3, at=now)],
            [],
            [],
            [b1],
            [{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].ndvi_current == pytest.approx(0.31)
        assert out.units[0].last_index_at == now
