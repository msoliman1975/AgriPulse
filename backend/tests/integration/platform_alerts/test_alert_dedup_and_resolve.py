"""Dedup, escalation and auto-resolve semantics of `public.platform_alerts`.

These four behaviours are the whole contract between the sweep and the
operator's screen, and each is a partial-index or ON CONFLICT detail that
unit tests cannot reach.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.platform_alerts.repository import PlatformAlertsRepository

pytestmark = [pytest.mark.integration]


async def _fetch(session: Any, alert_key: str) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT severity, status, occurrences, title,
                           first_seen_at, last_seen_at, resolved_reason
                      FROM public.platform_alerts
                     WHERE alert_key = :k
                     ORDER BY first_seen_at
                    """
                ),
                {"k": alert_key},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _upsert(repo: PlatformAlertsRepository, key: str, **over: Any) -> None:
    kwargs: dict[str, Any] = {
        "alert_key": key,
        "category": "imagery",
        "kind": "stream_silent",
        "severity": "warning",
        "title": "Imagery silent",
        "detail": "d",
        "context": {},
    }
    kwargs.update(over)
    await repo.upsert(**kwargs)


@pytest.mark.asyncio
async def test_repeat_detection_bumps_instead_of_duplicating(admin_session: Any) -> None:
    """A sweep every 10 minutes must not add a row every 10 minutes."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:test:{uuid4()}"

    await _upsert(repo, key)
    await _upsert(repo, key)
    await _upsert(repo, key)
    await admin_session.commit()

    rows = await _fetch(admin_session, key)
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 3


@pytest.mark.asyncio
async def test_escalation_moves_the_existing_row(admin_session: Any) -> None:
    """Severity is deliberately absent from the unique index.

    An alert that gets worse has to move the card the operator is already
    looking at. If severity were part of the key, a warning that became
    critical would leave the warning standing beside it and the platform
    would report two problems where there is one.
    """
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:test:{uuid4()}"

    await _upsert(repo, key, severity="warning")
    await admin_session.commit()
    first_seen = (await _fetch(admin_session, key))[0]["first_seen_at"]

    await _upsert(repo, key, severity="critical", title="Imagery silent (worse)")
    await admin_session.commit()

    rows = await _fetch(admin_session, key)
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["title"] == "Imagery silent (worse)"
    # How long this has been going on must not reset when it escalates.
    assert rows[0]["first_seen_at"] == first_seen


@pytest.mark.asyncio
async def test_acknowledged_alert_is_not_reopened_by_a_later_sweep(
    admin_session: Any,
) -> None:
    """Re-detecting a problem an operator has already seen must not quietly
    flip it back to `open` and re-surface it as new work."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:test:{uuid4()}"

    await _upsert(repo, key)
    await admin_session.commit()
    alert_id = (
        await admin_session.execute(
            text("SELECT id FROM public.platform_alerts WHERE alert_key = :k"), {"k": key}
        )
    ).scalar_one()

    await repo.acknowledge(alert_id=alert_id, user_id=None, user_email="ops@example.com")
    await admin_session.commit()

    await _upsert(repo, key)
    await admin_session.commit()

    rows = await _fetch(admin_session, key)
    assert rows[0]["status"] == "acknowledged"
    assert rows[0]["occurrences"] == 2


@pytest.mark.asyncio
async def test_absence_resolves_and_a_return_opens_a_fresh_alert(
    admin_session: Any,
) -> None:
    """The recovery path, and the reason the unique index is partial.

    Once resolved, the row leaves the uniqueness scope, so the same
    `alert_key` coming back opens a second row rather than reviving the
    closed one. That is what keeps the history of "this broke twice"
    readable instead of collapsing it into one card with a big counter.
    """
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:test:{uuid4()}"

    await _upsert(repo, key)
    await admin_session.commit()

    # A later sweep that does not see this key closes it.
    closed = await repo.auto_resolve_absent(kinds=["stream_silent"], seen_keys=["something-else"])
    await admin_session.commit()
    assert closed >= 1

    rows = await _fetch(admin_session, key)
    assert len(rows) == 1
    assert rows[0]["status"] == "resolved"
    assert rows[0]["resolved_reason"] == "auto"

    # It breaks again.
    await _upsert(repo, key)
    await admin_session.commit()

    rows = await _fetch(admin_session, key)
    assert len(rows) == 2
    assert [r["status"] for r in rows] == ["resolved", "open"]


@pytest.mark.asyncio
async def test_auto_resolve_only_touches_the_kinds_it_is_given(
    admin_session: Any,
) -> None:
    """`task_error` is written by a Celery signal, not by the sweep, so an
    absence-based resolve must never be able to reach it."""
    repo = PlatformAlertsRepository(admin_session)
    silent_key = f"stream_silent:test:{uuid4()}"
    task_key = f"task_error:test:{uuid4()}"

    await _upsert(repo, silent_key)
    await _upsert(repo, task_key, kind="task_error", category="task", severity="critical")
    await admin_session.commit()

    await repo.auto_resolve_absent(kinds=["stream_silent"], seen_keys=[])
    await admin_session.commit()

    assert (await _fetch(admin_session, silent_key))[0]["status"] == "resolved"
    assert (await _fetch(admin_session, task_key))[0]["status"] == "open"
