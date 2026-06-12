"""Unit tests for the operations-log report service."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.reports import service as svc_module
from app.modules.reports.service import ReportsService, _truncate


def test_truncate() -> None:
    assert _truncate(None, 10) is None
    assert _truncate("short", 10) == "short"
    assert _truncate("  trimmed  ", 10) == "trimmed"
    out = _truncate("a very long sentence that exceeds", 10)
    assert out is not None
    assert out.endswith("…")
    assert len(out) == 10


def _service() -> ReportsService:
    s = ReportsService.__new__(ReportsService)
    s._session = AsyncMock()  # type: ignore[attr-defined]
    s._public_session = AsyncMock()  # type: ignore[attr-defined]
    s._farms = AsyncMock()  # type: ignore[attr-defined]
    return s


@pytest.mark.asyncio
async def test_operations_log_merges_sorts_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    farm_id = uuid4()
    # Anchor the window so 'now' default covers our timestamps.
    now = datetime.now(UTC)
    t_alert = now - timedelta(days=1)
    t_rec = now - timedelta(days=2)
    old_open = now - timedelta(days=60)  # opened before window, resolved inside

    s = _service()
    s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]

    async def fake_acts(*_a: object, **_k: object) -> list:
        return [
            {
                "scheduled_date": date(2026, 5, 27),
                "activity_type": "fertilize",
                "status": "completed",
                "product_name": "Urea",
                "dosage": "50kg/ha",
                "block_name": "B1",
            },
            {
                "scheduled_date": date(2026, 5, 20),
                "activity_type": "scout",
                "status": "skipped",
                "product_name": None,
                "dosage": None,
                "block_name": "B2",
            },
        ]

    async def fake_alerts(*_a: object, **_k: object) -> list:
        return [
            {
                "created_at": t_alert,
                "resolved_at": None,
                "rule_code": "ndvi_drop",
                "severity": "warning",
                "status": "open",
                "diagnosis_en": "NDVI dropped",
                "block_name": "B1",
            },
            {
                # Opened before window but resolved inside → counts as
                # resolved, but is NOT emitted as an opened entry.
                "created_at": old_open,
                "resolved_at": now - timedelta(days=1),
                "rule_code": "old_rule",
                "severity": "info",
                "status": "resolved",
                "diagnosis_en": "Old",
                "block_name": "B3",
            },
        ]

    async def fake_recs(*_a: object, **_k: object) -> list:
        return [
            {
                "created_at": t_rec,
                "action_type": "irrigate",
                "severity": "info",
                "state": "applied",
                "text_en": "Irrigate block now",
                "dismissal_reason": None,
                "block_name": "B1",
            }
        ]

    monkeypatch.setattr(svc_module, "_select_ops_activities", fake_acts)
    monkeypatch.setattr(svc_module, "_select_ops_alerts", fake_alerts)
    monkeypatch.setattr(svc_module, "_select_ops_recommendations", fake_recs)

    out = await s.get_operations_log_report(farm_id=farm_id, since=None, until=None)

    # 2 activities + 1 in-window alert + 1 rec = 4 entries (old alert excluded).
    assert len(out.entries) == 4
    kinds = [e.kind for e in out.entries]
    assert kinds.count("alert") == 1
    assert kinds.count("recommendation") == 1
    assert kinds.count("activity") == 2

    # Most recent first; the fertilize activity (2026-05-27) is newest.
    assert out.entries[0].time >= out.entries[-1].time

    fert = next(e for e in out.entries if e.title == "fertilize")
    assert fert.detail == "Urea · 50kg/ha"

    assert out.summary.activities_total == 2
    assert out.summary.activities_completed == 1
    assert out.summary.activities_skipped == 1
    assert out.summary.alerts_opened == 1  # old alert not counted as opened
    assert out.summary.alerts_resolved == 1  # old alert resolved in window
    assert out.summary.recommendations_total == 1
    assert out.summary.recommendations_applied == 1
    assert out.summary.recommendations_dismissed == 0


@pytest.mark.asyncio
async def test_operations_log_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    farm_id = uuid4()
    s = _service()
    s._farms.get_farm_by_id = AsyncMock(return_value={"id": farm_id, "name": "F"})  # type: ignore[attr-defined]

    async def empty(*_a: object, **_k: object) -> list:
        return []

    monkeypatch.setattr(svc_module, "_select_ops_activities", empty)
    monkeypatch.setattr(svc_module, "_select_ops_alerts", empty)
    monkeypatch.setattr(svc_module, "_select_ops_recommendations", empty)

    out = await s.get_operations_log_report(farm_id=farm_id, since=None, until=None)
    assert out.entries == []
    assert out.summary.activities_total == 0
    assert out.summary.alerts_opened == 0
