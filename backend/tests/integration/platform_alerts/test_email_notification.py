"""What the digest mails, once, and when it mails again.

Everything here runs the real SQL. The two production bugs this module was
written after both survived a test suite that used a fake repository, so a
fake would prove nothing about the `notified_at` / `notified_severity`
predicate, which is the whole contract.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.platform_alerts import email as email_mod
from app.modules.platform_alerts.repository import PlatformAlertsRepository

pytestmark = [pytest.mark.integration]


async def _upsert(repo: PlatformAlertsRepository, key: str, **over: Any) -> None:
    kwargs: dict[str, Any] = {
        "alert_key": key,
        "category": "imagery",
        "kind": "stream_silent",
        "severity": "warning",
        "title": "Imagery silent on Green Farm",
        "detail": "No completed pass in 8 days.",
        "context": {},
    }
    kwargs.update(over)
    await repo.upsert(**kwargs)


async def _ids(session: Any, key: str) -> list[Any]:
    rows = (
        await session.execute(
            text("SELECT id FROM public.platform_alerts WHERE alert_key = :k"),
            {"k": key},
        )
    ).all()
    return [r.id for r in rows]


async def _notified(session: Any, key: str) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT notified_at, notified_severity, severity
                      FROM public.platform_alerts
                     WHERE alert_key = :k
                    """
                ),
                {"k": key},
            )
        )
        .mappings()
        .first()
    )
    assert row is not None
    return dict(row)


@pytest.mark.asyncio
async def test_unnotified_lists_new_then_stops(admin_session: Any) -> None:
    """A fresh alert is a candidate once. Stamping it takes it off the list."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:email:{uuid4()}"
    await _upsert(repo, key)
    await admin_session.commit()

    ids = await _ids(admin_session, key)
    first = await repo.list_unnotified(limit=500)
    assert ids[0] in [r["id"] for r in first]

    await repo.mark_notified(alert_ids=ids)
    await admin_session.commit()

    again = await repo.list_unnotified(limit=500)
    assert ids[0] not in [r["id"] for r in again]

    stamped = await _notified(admin_session, key)
    assert stamped["notified_at"] is not None
    assert stamped["notified_severity"] == "warning"


@pytest.mark.asyncio
async def test_escalation_mails_a_second_time(admin_session: Any) -> None:
    """A warning that becomes critical moves the same row.

    A bare timestamp would hide that, because there is no second row to
    notice. `notified_severity` is what catches it.
    """
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:escalate:{uuid4()}"
    await _upsert(repo, key, severity="warning")
    await admin_session.commit()

    ids = await _ids(admin_session, key)
    await repo.mark_notified(alert_ids=ids)
    await admin_session.commit()
    assert ids[0] not in [r["id"] for r in await repo.list_unnotified(limit=500)]

    await _upsert(repo, key, severity="critical")
    await admin_session.commit()

    # Still one row - 0069 escalates in place - and it is a candidate again.
    assert len(await _ids(admin_session, key)) == 1
    assert ids[0] in [r["id"] for r in await repo.list_unnotified(limit=500)]


@pytest.mark.asyncio
async def test_repeat_detection_does_not_mail_again(admin_session: Any) -> None:
    """The sweep re-detects every 10 minutes. That is not news."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:repeat:{uuid4()}"
    await _upsert(repo, key)
    await admin_session.commit()
    ids = await _ids(admin_session, key)
    await repo.mark_notified(alert_ids=ids)
    await admin_session.commit()

    await _upsert(repo, key)
    await _upsert(repo, key)
    await admin_session.commit()

    assert ids[0] not in [r["id"] for r in await repo.list_unnotified(limit=500)]


@pytest.mark.asyncio
async def test_no_recipients_leaves_rows_unstamped(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nobody subscribed, the alert must stay unmailed.

    Marking it as sent would mean the first person to tick the box only
    ever hears about problems that started after they ticked it.
    """
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:norecip:{uuid4()}"
    await _upsert(repo, key)
    await admin_session.commit()

    async def _none() -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(repo, "list_email_recipients", _none)
    result = await email_mod.notify(repo)

    assert result == {"recipients": 0, "alerts": 0, "sent": 0}
    assert (await _notified(admin_session, key))["notified_at"] is None


@pytest.mark.asyncio
async def test_notify_sends_then_stamps(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path, end to end against the real table."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:send:{uuid4()}"
    await _upsert(repo, key, severity="critical")
    await admin_session.commit()

    async def _one() -> list[dict[str, Any]]:
        return [{"email": "ops@example.test", "full_name": "Ops"}]

    outbox: list[dict[str, Any]] = []

    def _fake_send(**kwargs: Any) -> None:
        outbox.append(kwargs)

    monkeypatch.setattr(repo, "list_email_recipients", _one)
    monkeypatch.setattr(email_mod, "send_email", _fake_send)

    result = await email_mod.notify(repo)
    await admin_session.commit()

    assert result["sent"] == 1
    assert len(outbox) == 1
    assert outbox[0]["to_address"] == "ops@example.test"
    assert "critical" in outbox[0]["subject"]
    # Both bodies go out. A client that strips HTML still gets the list.
    assert outbox[0]["body_text"]
    assert "<table" in outbox[0]["body_html"]
    assert (await _notified(admin_session, key))["notified_at"] is not None


@pytest.mark.asyncio
async def test_failed_send_leaves_rows_for_the_next_sweep(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relay that is down must not cost the operator the notification."""
    repo = PlatformAlertsRepository(admin_session)
    key = f"stream_silent:fail:{uuid4()}"
    await _upsert(repo, key)
    await admin_session.commit()

    async def _one() -> list[dict[str, Any]]:
        return [{"email": "ops@example.test", "full_name": "Ops"}]

    def _boom(**kwargs: Any) -> None:
        raise RuntimeError("relay refused")

    monkeypatch.setattr(repo, "list_email_recipients", _one)
    monkeypatch.setattr(email_mod, "send_email", _boom)

    result = await email_mod.notify(repo)
    await admin_session.commit()

    assert result["sent"] == 0
    assert (await _notified(admin_session, key))["notified_at"] is None


def test_digest_names_counts_and_says_what_it_dropped() -> None:
    """The cap must be visible in the mail.

    A digest that truncates without saying so reads as the whole list when
    it is not.
    """
    rows: list[dict[str, Any]] = [
        {
            "severity": "critical",
            "title": "Imagery jobs stuck",
            "detail": "6 jobs.",
            "tenant_name": "Agrosina",
            "farm_name": "Bashier Elkhier",
        },
        {
            "severity": "warning",
            "title": "Thermal silent",
            "detail": None,
            "tenant_name": "Green Valley",
            "farm_name": "Mango Republic",
        },
    ]
    subject, body = email_mod.build_digest(rows, dropped=4)

    assert "1 critical" in subject
    assert "1 warning" in subject
    # Criticals first, whatever order they arrived in.
    assert body.index("Imagery jobs stuck") < body.index("Thermal silent")
    assert "Agrosina / Bashier Elkhier" in body
    assert "4 more alert(s) are not listed" in body


def test_digest_html_escapes_and_keeps_the_same_order() -> None:
    """The HTML twin. Alert titles carry exception messages, which carry
    angle brackets - `Task <Task pending ...>` - so escaping is not
    optional here."""
    rows: list[dict[str, Any]] = [
        {
            "severity": "warning",
            "title": "Thermal silent",
            "detail": None,
            "tenant_name": "Green Valley",
            "farm_name": None,
        },
        {
            "severity": "critical",
            "title": "Background task failing: <weather.fetch>",
            "detail": "RuntimeError: Task <Task pending> & more",
            "tenant_name": None,
            "farm_name": None,
        },
    ]
    html = email_mod.build_digest_html(rows, dropped=0)

    assert "<Task pending>" not in html
    assert "&lt;Task pending&gt;" in html
    assert "&amp; more" in html
    # Criticals first here too, so the mail and its plain-text twin agree.
    assert html.index("weather.fetch") < html.index("Thermal silent")
    # A row with no farm falls back to the tenant, and with neither to a word.
    assert "platform" in html
