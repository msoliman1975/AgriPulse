"""The platform half: the queue, the caps, and who is allowed to approve.

The cap tests are the reason this file exists. A cap that is only shown on
a screen is not a cap, so what is asserted here is that the API refuses,
that the refusal names the number, and that an override is recorded rather
than silently allowed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.shared.auth.context import PlatformRole

pytestmark = [pytest.mark.integration]


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _queued_signup(session: AsyncSession, *, status: str = "awaiting_approval") -> UUID:
    """Insert a signup already sitting in the queue.

    Written directly rather than driven through the public routes: these
    tests are about the decision, and walking the whole funnel for each one
    would make a cap failure look like a signup failure.
    """
    suffix = uuid4().hex[:8]
    result = await session.execute(
        text(
            """
            INSERT INTO public.trial_signups
                (status, full_name, email, email_domain, organisation,
                 country, status_handle, verified_at)
            VALUES
                (:status, 'Queue Person', :email, :domain, :org,
                 'EG', :handle, now())
            RETURNING id
            """
        ),
        {
            "status": status,
            "email": f"person@{suffix}.example.com",
            "domain": f"{suffix}.example.com",
            "org": f"Org {suffix}",
            "handle": f"h-{suffix}",
        },
    )
    signup_id = result.scalar_one()
    await session.commit()
    return signup_id


@pytest.mark.asyncio
async def test_queue_lists_signups_with_capacity_numbers(
    platform_app_factory: Any,
    admin_session: AsyncSession,
) -> None:
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        response = await client.get("/api/v1/platform/trials")

    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body["signups"]]
    assert str(signup_id) in ids

    capacity = body["capacity"]
    settings = get_settings()
    assert capacity["cap_per_day"] == settings.trial_approvals_per_day
    assert capacity["cap_per_week"] == settings.trial_approvals_per_week
    # The screen has to be able to say when a reached cap lifts.
    assert capacity["day_resets_at"]
    assert capacity["week_resets_at"]
    assert capacity["queue_depth"] >= 1


@pytest.mark.asyncio
async def test_support_can_read_the_queue_but_not_approve(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
) -> None:
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_SUPPORT)

    async with await _client(app) as client:
        read = await client.get("/api/v1/platform/trials")
        approve = await client.post(f"/api/v1/platform/trials/{signup_id}/approve", json={})

    assert read.status_code == 200
    assert approve.status_code == 403
    assert enqueued_tasks == []


@pytest.mark.asyncio
async def test_a_tenant_user_cannot_reach_the_queue(platform_app_factory: Any) -> None:
    """A trial owner holds no platform role, so this is the shape of every
    platform route for them.
    """
    app = platform_app_factory(None)
    async with await _client(app) as client:
        response = await client.get("/api/v1/platform/trials")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_approve_records_the_actor_and_enqueues_provisioning(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
) -> None:
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        response = await client.post(f"/api/v1/platform/trials/{signup_id}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    # Approval is the only trigger for provisioning.
    assert enqueued_tasks == [str(signup_id)]

    row = await admin_session.execute(
        text("SELECT status, reviewed_by, reviewed_at FROM public.trial_signups WHERE id = :i"),
        {"i": signup_id},
    )
    status, reviewed_by, reviewed_at = row.one()
    assert status == "approved"
    assert reviewed_by is not None
    assert reviewed_at is not None


@pytest.mark.asyncio
async def test_approve_is_refused_past_the_daily_cap(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_caps(monkeypatch, per_day=1, per_week=10)
    first = await _queued_signup(admin_session)
    second = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        ok = await client.post(f"/api/v1/platform/trials/{first}/approve", json={})
        blocked = await client.post(f"/api/v1/platform/trials/{second}/approve", json={})

    assert ok.status_code == 200
    assert blocked.status_code == 409
    problem = blocked.json()
    # The refusal must name the cap. "Not allowed" with no number leaves an
    # admin with nothing to act on.
    assert problem["scope"] == "daily"
    assert problem["cap"] == 1
    assert problem["resets_at"]
    # The blocked one never reached the worker.
    assert enqueued_tasks == [str(first)]


@pytest.mark.asyncio
async def test_override_past_the_cap_is_allowed_and_recorded(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_caps(monkeypatch, per_day=1, per_week=10)
    first = await _queued_signup(admin_session)
    second = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        await client.post(f"/api/v1/platform/trials/{first}/approve", json={})
        override = await client.post(
            f"/api/v1/platform/trials/{second}/approve",
            json={"override_reason": "Large prospect, agreed with sales."},
        )

    assert override.status_code == 200
    body = override.json()
    assert body["status"] == "approved"
    assert body["cap_override"] is True
    assert body["decision_reason"] == "Large prospect, agreed with sales."
    assert enqueued_tasks == [str(first), str(second)]


@pytest.mark.asyncio
async def test_pause_keeps_the_row_in_the_queue(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
    enqueued_tasks: list[str],
) -> None:
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        paused = await client.post(
            f"/api/v1/platform/trials/{signup_id}/pause",
            json={"reason": "At capacity this week."},
        )
        queue = await client.get("/api/v1/platform/trials")

    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    # Paused is held, not closed — it must still be visible to approve later.
    assert str(signup_id) in [row["id"] for row in queue.json()["signups"]]
    assert enqueued_tasks == []
    assert any("held" in mail["subject"] for mail in sent_emails)


@pytest.mark.asyncio
async def test_a_paused_row_can_still_be_approved(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
) -> None:
    signup_id = await _queued_signup(admin_session, status="paused")
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        response = await client.post(f"/api/v1/platform/trials/{signup_id}/approve", json={})

    assert response.status_code == 200
    assert enqueued_tasks == [str(signup_id)]


@pytest.mark.asyncio
async def test_reject_sends_the_reason_to_the_person(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
    enqueued_tasks: list[str],
) -> None:
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        response = await client.post(
            f"/api/v1/platform/trials/{signup_id}/reject",
            json={"reason": "We do not operate in this region yet."},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert enqueued_tasks == []
    assert any("We do not operate in this region yet." in mail["body"] for mail in sent_emails)


@pytest.mark.asyncio
async def test_approving_twice_is_refused(
    platform_app_factory: Any,
    admin_session: AsyncSession,
    enqueued_tasks: list[str],
) -> None:
    """Two clicks must not mean two tenants."""
    signup_id = await _queued_signup(admin_session)
    app = platform_app_factory(PlatformRole.PLATFORM_ADMIN)

    async with await _client(app) as client:
        first = await client.post(f"/api/v1/platform/trials/{signup_id}/approve", json={})
        second = await client.post(f"/api/v1/platform/trials/{signup_id}/approve", json={})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["current_status"] == "approved"
    assert enqueued_tasks == [str(signup_id)]


def _set_caps(monkeypatch: pytest.MonkeyPatch, *, per_day: int, per_week: int) -> None:
    """Move the caps for one test.

    The settings object is cached, so the env var is set and the cache
    cleared — patching the attribute alone would leave any code path that
    calls `get_settings()` again reading the old value.
    """
    monkeypatch.setenv("TRIAL_APPROVALS_PER_DAY", str(per_day))
    monkeypatch.setenv("TRIAL_APPROVALS_PER_WEEK", str(per_week))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Any:
    """Any test that moved a cap must not leave it moved."""
    yield
    get_settings.cache_clear()
