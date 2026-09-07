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

    def first(self) -> Any:
        """The farm-override read uses `.first()`, not `.all()`.

        Returning None for an empty set is the "farm has no override" case
        and is what most of these tests want.
        """
        return self._rows[0] if self._rows else None


class _Row:
    """A row object with attribute access, for the reads that use `.first()`
    and then read a column off it rather than going through `.mappings()`."""

    def __init__(self, **cols: Any) -> None:
        self.__dict__.update(cols)


def _session(
    *,
    badge: list[Any] | None = None,
    alerts: list[Any] | None = None,
    recommendations: list[Any] | None = None,
    traces: list[Any] | None = None,
    verdicts: list[Any] | None = None,
    cells: list[Any] | None = None,
    crops: list[Any] | None = None,
    definitions: list[Any] | None = None,
    farm_override: dict[str, Any] | None = None,
    grid: list[Any] | None = None,
    roster: list[Any] | None = None,
    indices: list[Any] | None = None,
    unbounded: list[Any] | None = None,
) -> AsyncMock:
    """Feed `execute` its results, named rather than positional.

    The endpoint's call order lives HERE and nowhere else. It used to live
    in every call site as a bare list of lists, and it broke silently every
    time a query was added: the rows landed on the wrong reader and
    surfaced as a shape error rather than a missing stub. Phase 3 added
    three queries, Phase 5 added two more, and Phase 6 another.

    Order, which is the one thing this function knows:

      1. badge         — the map's open-alert rollup
      2. alerts        — counted alerts per (severity, status, cell)   ┐
      3. recommendations — max open confidence per block               │ the
      4. traces        — per-status counts from the newest sweep       │ evidence
      5. verdicts      — each tree's current status for the block      │ loader
      6. cells         — live grid cell count per block                │
      7. crops         — current crop path per block                   ┘
      8. definitions   — the per-crop health catalog          ┐ the health
      9. farm_override — this farm's own health override      ┘ definitions
     10. grid          — current grid config per block
     11. roster        — the active block ids
     12. indices       — latest values, bounded to the recent window
     13. unbounded     — latest values, unbounded; issued ONLY for blocks
                         the recent window returned nothing for

    `unbounded` defaults to not being supplied at all, so a test whose
    blocks all have recent readings fails loudly if a fallback sweep
    happens rather than passing on a stub nobody meant to provide.
    """
    sets: list[list[Any]] = [
        badge or [],
        alerts or [],
        recommendations or [],
        traces or [],
        verdicts or [],
        cells or [],
        crops or [],
        definitions or [],
        [_Row(health_definition=farm_override)] if farm_override is not None else [],
        grid or [],
        roster or [],
        indices or [],
    ]
    if unbounded is not None:
        sets.append(unbounded)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_Result(rows) for rows in sets])
    return session


def _definition(crop_path: str, *, version: int = 1, **body: Any) -> dict[str, Any]:
    """One row of the per-crop catalog, as `load_health_definitions` reads
    it. `version` is what the dock renders beside the class."""
    return {"crop_path": crop_path, "definition": body, "version": version}


def _crop(block_id: Any, crop_path: str) -> dict[str, Any]:
    return {"block_id": block_id, "crop_path": crop_path}


def _alert(block_id: Any, severity: str, status: str, n: int = 1, cells: int = 0) -> dict[str, Any]:
    """One FINDING. `cells` is how many distinct cells it is made of; zero
    means it is a statement about the whole block."""
    return {
        "kind": "finding",
        "block_id": block_id,
        "severity": severity,
        "status": status,
        "cell_id": None,
        "n": n,
        "cells": cells,
    }


def _cell(block_id: Any, severity: str, status: str, cell_id: Any, n: int = 1) -> dict[str, Any]:
    """One distinct cell of a grouped finding, with its OWN severity."""
    return {
        "kind": "cell",
        "block_id": block_id,
        "severity": severity,
        "status": status,
        "cell_id": cell_id,
        "n": n,
        "cells": 0,
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
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.7, "time": now}],
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
            traces=[_traces(b1, clear=21, at=now - timedelta(hours=6))],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
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
            traces=[_traces(b1, clear=4, at=now - timedelta(hours=72))],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
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
            alerts=[_alert(b1, "critical", "open")],
            traces=[_traces(b1, fired=1, at=now - timedelta(days=7))],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_health == "critical"
        assert out.units[0].health_evidence.preview_reason == "critical_alert"

    async def test_every_tree_skipped_reads_no_tree(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            traces=[_traces(b1, skipped=19, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
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
            alerts=[
                _alert(b1, "critical", "acknowledged"),
                _alert(b1, "info", "open", n=3),
            ],
            traces=[_traces(b1, fired=1, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
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
            alerts=[
                # One grouped finding made of two cells, plus the cells.
                _alert(b1, "critical", "open", cells=2),
                _cell(b1, "critical", "open", c1, n=2),
                _cell(b1, "critical", "open", c2),
            ],
            traces=[_traces(b1, fired=2, at=now)],
            cells=[{"block_id": b1, "total_cells": 121}],
            grid=[{"block_id": b1, "product_id": product}],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        ev = out.units[0].health_evidence
        # Two distinct cells. The share test counts cells, not alert rows.
        assert ev.critical_cells == 2
        assert ev.total_cells == 121
        # One finding, though. A 12-cell outbreak is one thing that is wrong.
        assert ev.alerts_by_severity == {"critical": 1}
        # The platform default sets no share, so one critical cell is enough.
        assert ev.preview_health == "critical"

    async def test_evidence_does_not_leak_between_blocks(self) -> None:
        farm_id, loud, quiet = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            alerts=[_alert(loud, "critical", "open")],
            recommendations=[{"block_id": loud, "max_confidence": 0.9}],
            traces=[_traces(loud, fired=1, at=now), _traces(quiet, clear=3, at=now)],
            roster=[loud, quiet],
            indices=[
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
            traces=[_traces(b1, clear=2, at=swept)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": swept}],
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
            traces=[_traces(b1, clear=12, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
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
            traces=[_traces(b1, clear=12, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
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
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.82, "time": now}],
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
            traces=[_traces(b1, clear=3, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].ndvi_current == pytest.approx(0.31)
        assert out.units[0].last_index_at == now


@pytest.mark.asyncio
class TestThePerCropDefinition:
    """Phase 5 — the crop decides which definition judges the block.

    Every case here turns on freshness, because that is the one value the
    shipped seeds change and the one where crop and platform genuinely
    disagree. A 60-hour-old sweep is stale under the platform's 48 and
    current under mango's 72.
    """

    async def test_the_crop_definition_beats_the_platform_default(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            traces=[_traces(b1, clear=12, at=now - timedelta(hours=60))],
            crops=[_crop(b1, "mango")],
            definitions=[_definition("mango", stale_after_hours=72)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        # 60 hours is past the platform's 48 and inside mango's 72.
        assert out.units[0].health_evidence.preview_health == "healthy"
        assert out.units[0].health_evidence.preview_reason == "all_clear"

    async def test_without_the_crop_row_the_same_block_reads_stale(self) -> None:
        """The other half of the previous test. Same evidence, same
        definition in the catalog, no crop assignment on the block — so
        nothing connects the two and the platform default decides."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            traces=[_traces(b1, clear=12, at=now - timedelta(hours=60))],
            definitions=[_definition("mango", stale_after_hours=72)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_reason == "stale"

    async def test_a_crop_level_file_reaches_a_variety_block(self) -> None:
        """Mango's `classification_depth` is `variety`, so a real block
        carries `mango.<variety>`. A seed authored at `mango` that did not
        reach it would apply to nothing at all."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            traces=[_traces(b1, clear=12, at=now - timedelta(hours=60))],
            crops=[_crop(b1, "mango.keitt")],
            definitions=[_definition("mango", stale_after_hours=72)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_health == "healthy"

    async def test_two_crops_on_one_farm_are_judged_by_their_own_definitions(self) -> None:
        """The case a single shared definition could never get right, and
        the reason the catalog exists."""
        farm_id = uuid4()
        tree, spud = uuid4(), uuid4()
        now = datetime.now(UTC)
        stale_by_36h = now - timedelta(hours=36)
        session = _session(
            traces=[
                _traces(tree, clear=12, at=stale_by_36h),
                _traces(spud, clear=6, at=stale_by_36h),
            ],
            crops=[_crop(tree, "mango.keitt"), _crop(spud, "potato")],
            definitions=[
                _definition("mango", stale_after_hours=72),
                _definition("potato", stale_after_hours=24),
            ],
            roster=[tree, spud],
            indices=[
                {"block_id": tree, "index_code": "ndvi", "mean": 0.31, "time": now},
                {"block_id": spud, "index_code": "ndvi", "mean": 0.72, "time": now},
            ],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        by_id = {u.id: u.health_evidence for u in out.units}
        # One sweep, one age, two answers — which is the whole point.
        assert by_id[tree].preview_health == "healthy"
        assert by_id[spud].preview_reason == "stale"

    async def test_the_crop_path_is_reported_on_the_response(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            crops=[_crop(b1, "mango.keitt")],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.5, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.crop_path == "mango.keitt"

    @pytest.mark.usefixtures("_definition_on")
    async def test_with_the_flag_on_the_crop_definition_decides_the_shipped_class(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            traces=[_traces(b1, clear=12, at=now - timedelta(hours=60))],
            crops=[_crop(b1, "mango")],
            definitions=[_definition("mango", stale_after_hours=72)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.31, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health == "healthy"
        assert out.units[0].health_reason == "all_clear"


@pytest.mark.asyncio
class TestTheCellShare:
    """Phase 8 — `cell_critical_share` was unreachable, and this is why.

    A grouped alert is one finding stored as a parent plus one child per
    cell, and the parent carries `cell_id = NULL`. The evidence query
    filtered to findings — which the counters must do, or a 12-cell outbreak
    reads as 13 — and so threw away every cell there was. Measured on prod:
    ZERO cell-scoped findings out of 542 unresolved rows. `critical_cells`
    was always 0 and no share a farm set could ever be reached.
    """

    async def test_a_grouped_finding_is_judged_by_its_cells_not_by_its_parent(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        cells = [uuid4() for _ in range(3)]
        now = datetime.now(UTC)
        session = _session(
            alerts=[
                _alert(b1, "critical", "open", cells=3),
                *[_cell(b1, "critical", "open", c) for c in cells],
            ],
            cells=[{"block_id": b1, "total_cells": 100}],
            traces=[_traces(b1, fired=1, at=now)],
            crops=[_crop(b1, "mango")],
            # 50% of the block's cells must be critical. 3 of 100 is not.
            definitions=[_definition("mango", cell_critical_share=0.5)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        ev = out.units[0].health_evidence
        assert ev.critical_cells == 3
        assert ev.total_cells == 100
        # Held back to watch, and the reason names the test that decided.
        assert ev.preview_health == "watch"
        assert ev.preview_reason == "cell_share"

    async def test_enough_cells_still_make_the_block_critical(self) -> None:
        farm_id, b1 = uuid4(), uuid4()
        cells = [uuid4() for _ in range(60)]
        now = datetime.now(UTC)
        session = _session(
            alerts=[
                _alert(b1, "critical", "open", cells=60),
                *[_cell(b1, "critical", "open", c) for c in cells],
            ],
            cells=[{"block_id": b1, "total_cells": 100}],
            traces=[_traces(b1, fired=1, at=now)],
            crops=[_crop(b1, "mango")],
            definitions=[_definition("mango", cell_critical_share=0.5)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_health == "critical"
        assert out.units[0].health_evidence.preview_reason == "critical_alert"

    async def test_a_block_scoped_critical_ignores_the_share(self) -> None:
        """An alert about the whole block is already about the whole block.
        Holding it back for want of cells would hide a real finding behind a
        test that does not apply to it."""
        farm_id, b1 = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            alerts=[_alert(b1, "critical", "open")],
            cells=[{"block_id": b1, "total_cells": 100}],
            traces=[_traces(b1, fired=1, at=now)],
            crops=[_crop(b1, "mango")],
            definitions=[_definition("mango", cell_critical_share=0.5)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        assert out.units[0].health_evidence.preview_health == "critical"

    async def test_the_counters_still_count_findings_not_cells(self) -> None:
        """The two readings disagree on purpose. One outbreak is one thing
        that is wrong; the share needs to know it covers twelve cells."""
        farm_id, b1 = uuid4(), uuid4()
        cells = [uuid4() for _ in range(12)]
        now = datetime.now(UTC)
        session = _session(
            alerts=[
                _alert(b1, "critical", "open", cells=12),
                *[_cell(b1, "critical", "open", c) for c in cells],
            ],
            cells=[{"block_id": b1, "total_cells": 100}],
            traces=[_traces(b1, fired=1, at=now)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        ev = out.units[0].health_evidence
        assert ev.alerts_by_severity == {"critical": 1}
        assert ev.critical_cells == 12

    async def test_a_cell_carries_its_own_severity_not_its_parent_card_s(self) -> None:
        """`attach_child` updates a member's severity in place, so a card at
        critical can hold cells that have since dropped to warning. Counting
        those as critical cells would inflate the share."""
        farm_id, b1 = uuid4(), uuid4()
        hot, cool = uuid4(), uuid4()
        now = datetime.now(UTC)
        session = _session(
            alerts=[
                _alert(b1, "critical", "open", cells=2),
                _cell(b1, "critical", "open", hot),
                _cell(b1, "warning", "open", cool),
            ],
            cells=[{"block_id": b1, "total_cells": 4}],
            traces=[_traces(b1, fired=1, at=now)],
            crops=[_crop(b1, "mango")],
            definitions=[_definition("mango", cell_critical_share=0.5)],
            roster=[b1],
            indices=[{"block_id": b1, "index_code": "ndvi", "mean": 0.8, "time": now}],
        )

        out = await get_blocks_summary(farm_id=farm_id, context=None, tenant_session=session)

        # One critical cell of four is 25%, under the 50% share.
        assert out.units[0].health_evidence.critical_cells == 1
        assert out.units[0].health_evidence.preview_reason == "cell_share"
