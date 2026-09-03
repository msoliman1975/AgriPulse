"""The scorecard under `health_definition_enabled`.

Two surfaces render a block's health: this page and the map. They used to
disagree, because the scorecard counted open, acknowledged and snoozed
alerts and the map counted open only. Both now read
`app.shared.health_evidence`, so the tests that matter here are the ones
that pin the scorecard to the same answer the map gives.

The repos are mocked; the loader's four statements are fed to
`_session.execute` in order. The SQL is exercised against a real schema
elsewhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.settings import get_settings
from app.modules.insights.service import InsightsService


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Row:
    def __init__(self, **cols: Any) -> None:
        self.__dict__.update(cols)


@pytest.fixture
def _definition_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEALTH_DEFINITION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _service(
    *,
    farm_id: UUID,
    blocks: list[dict[str, Any]],
    ndvi: dict[UUID, Decimal],
    alerts: list[Any] | None = None,
    recommendations: list[Any] | None = None,
    traces: list[Any] | None = None,
    cells: list[Any] | None = None,
    crops: list[Any] | None = None,
    definitions: list[Any] | None = None,
    farm_override: dict[str, Any] | None = None,
    with_evidence: bool = True,
) -> InsightsService:
    """A service with mocked repos and a session that returns, in order, the
    evidence loader's five statements, then the per-crop health catalog and
    this farm's override.

    Named rather than positional: this file used to pass a bare list of
    lists, and Phase 5's two extra queries shifted every one of them onto
    the wrong reader. `with_evidence=False` supplies nothing at all, which
    is what the flag-off path must do — it must not touch the session.
    """
    evidence_sets: list[list[Any]] = (
        [
            alerts or [],
            recommendations or [],
            traces or [],
            cells or [],
            crops or [],
            definitions or [],
            [_Row(health_definition=farm_override)] if farm_override is not None else [],
        ]
        if with_evidence
        else []
    )
    svc = InsightsService.__new__(InsightsService)
    now = datetime.now(UTC)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(rows) for rows in evidence_sets])
    svc._session = session  # type: ignore[attr-defined]

    svc._farms = AsyncMock()  # type: ignore[attr-defined]
    svc._indices = AsyncMock()  # type: ignore[attr-defined]
    svc._alerts = AsyncMock()  # type: ignore[attr-defined]
    svc._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id})  # type: ignore[attr-defined]
    svc._farms.list_blocks = AsyncMock(return_value=blocks)  # type: ignore[attr-defined]
    svc._indices.get_timeseries = AsyncMock(  # type: ignore[attr-defined]
        side_effect=lambda **kw: ({"bucket_time": now, "mean": ndvi[kw["block_id"]]},)
    )
    svc._alerts.list_alerts = AsyncMock(return_value=())  # type: ignore[attr-defined]
    return svc


def _traces(block_id: UUID, *, fired: int = 0, clear: int = 0, at: datetime) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "traces_fired": fired,
        "traces_clear": clear,
        "traces_skipped": 0,
        "traces_error": 0,
        "last_evaluated_at": at,
    }


@pytest.mark.asyncio
class TestScorecardUnderTheDefinition:
    async def test_off_the_scorecard_is_unchanged(self) -> None:
        """No flag, no new behaviour, and no queries either: the loader is
        not called at all, so a farm on the old rule pays nothing for the
        new one."""
        farm_id, b1 = uuid4(), uuid4()
        svc = _service(
            farm_id=farm_id,
            blocks=[{"id": b1, "name": "North"}],
            ndvi={b1: Decimal("0.31")},
            with_evidence=False,
        )

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        assert out.blocks[0].current_health == "critical"
        assert out.blocks[0].health_reason is None
        svc._session.execute.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.usefixtures("_definition_on")
    async def test_on_a_low_ndvi_block_with_a_clear_sweep_reads_healthy(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        svc = _service(
            farm_id=farm_id,
            blocks=[{"id": b1, "name": "North"}],
            ndvi={b1: Decimal("0.31")},
            traces=[_traces(b1, clear=9, at=now)],
        )

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        row = out.blocks[0]
        assert row.current_health == "healthy"
        assert row.health_reason == "all_clear"
        # NDVI still reaches the page as a reading. Only the verdict moved.
        assert row.current_value == Decimal("0.31")

    @pytest.mark.usefixtures("_definition_on")
    async def test_on_an_unswept_block_reads_unknown(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        svc = _service(
            farm_id=farm_id,
            blocks=[{"id": b1, "name": "North"}],
            ndvi={b1: Decimal("0.82")},
        )

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        assert out.blocks[0].current_health == "unknown"
        assert out.blocks[0].health_reason == "no_coverage"

    @pytest.mark.usefixtures("_definition_on")
    async def test_the_evidence_is_loaded_once_for_the_farm(self) -> None:
        """Seven statements for the whole farm, not seven per block — the
        evidence loader's five, the per-crop catalog and the farm override.
        The loop around this call is already N+1 on indices and alerts; a
        per-block load would have made a 36-block farm 252 round trips."""
        farm_id = uuid4()
        b1, b2, b3 = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        svc = _service(
            farm_id=farm_id,
            blocks=[
                {"id": b1, "name": "North"},
                {"id": b2, "name": "South"},
                {"id": b3, "name": "East"},
            ],
            ndvi={b1: Decimal("0.7"), b2: Decimal("0.7"), b3: Decimal("0.7")},
            traces=[_traces(b1, clear=4, at=now), _traces(b2, clear=4, at=now)],
        )

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        assert svc._session.execute.await_count == 7  # type: ignore[attr-defined]
        by_name = {r.block_name: r for r in out.blocks}
        assert by_name["North"].current_health == "healthy"
        assert by_name["South"].current_health == "healthy"
        # The block the sweep missed is the one that reads unknown, and only
        # that one: evidence must not spread to blocks it was not loaded for.
        assert by_name["East"].current_health == "unknown"
        assert by_name["East"].health_reason == "no_coverage"

    @pytest.mark.usefixtures("_definition_on")
    async def test_unknown_sorts_above_healthy_and_below_critical(self) -> None:
        """The existing sort already ranks unknown between watch and
        healthy. Turning the definition on makes that ordering load-bearing:
        unknown stops being rare, so a farm mid-rollout must not bury its
        unswept blocks under its green ones."""
        farm_id = uuid4()
        crit, unk, ok = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        svc = _service(
            farm_id=farm_id,
            blocks=[
                {"id": ok, "name": "Aaa healthy"},
                {"id": unk, "name": "Bbb unswept"},
                {"id": crit, "name": "Ccc critical"},
            ],
            ndvi={ok: Decimal("0.7"), unk: Decimal("0.7"), crit: Decimal("0.7")},
            alerts=[
                {
                    "block_id": crit,
                    "severity": "critical",
                    "status": "open",
                    "cell_id": None,
                    "n": 1,
                }
            ],
            traces=[_traces(ok, clear=4, at=now), _traces(crit, fired=1, at=now)],
        )

        out = await svc.get_farm_health_summary(farm_id=farm_id)

        assert [r.current_health for r in out.blocks] == ["critical", "unknown", "healthy"]
