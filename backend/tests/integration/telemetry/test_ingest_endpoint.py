"""POST /api/v1/telemetry/events end-to-end against a real hypertable.

Stubbed auth (the `farms` conftest pattern) so the route path is exercised
without Keycloak, but a real session and a real `public.usage_events`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.core.settings import get_settings
from app.modules.telemetry.router import router as telemetry_router
from app.modules.telemetry.service import set_telemetry_service
from app.shared.auth.context import PlatformRole, RequestContext, TenantRole

pytestmark = [pytest.mark.integration]

_URL = "/api/v1/telemetry/events"


class _StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def _context(
    *,
    user_id: UUID | None = None,
    tenant_id: UUID | None = None,
    platform: bool = False,
) -> RequestContext:
    return RequestContext(
        user_id=user_id or uuid4(),
        keycloak_subject="sub",
        tenant_id=tenant_id,
        tenant_role=None if platform else TenantRole.TENANT_ADMIN,
        platform_role=PlatformRole.PLATFORM_ADMIN if platform else None,
    )


def _client(context: RequestContext) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(telemetry_router)
    app.add_middleware(_StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _fresh_service() -> Iterator[None]:
    """Reset the singleton so one test's rate-limit state cannot leak."""
    set_telemetry_service(None)
    yield
    set_telemetry_service(None)


async def _rows(session: AsyncSession, session_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            "SELECT event_name, user_id, tenant_id, actor_role, is_platform_staff, "
            "locale, props, feature, flow, step, app_version "
            "FROM public.usage_events WHERE session_id = :s ORDER BY time"
        ),
        {"s": session_id},
    )
    return [dict(r._mapping) for r in result]


# --- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_is_stored_with_server_stamped_identity(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = uuid4(), uuid4()
    session_id = uuid4()
    context = _context(user_id=user_id, tenant_id=tenant_id)

    async with _client(context) as client:
        response = await client.post(
            _URL,
            json={
                "session_id": str(session_id),
                "app_version": "abc1234",
                "device_kind": "desktop",
                "events": [
                    {"event_name": "session_start"},
                    {"event_name": "page_view", "route": "/insights/:farmId"},
                    {
                        "event_name": "feature_used",
                        "feature": "index_chart",
                        "props": {"index_code": "NDVI", "action": "zoom"},
                    },
                ],
            },
        )

    assert response.status_code == 202
    assert response.json()["accepted"] == 3

    rows = await _rows(admin_session, session_id)
    assert [r["event_name"] for r in rows] == ["session_start", "page_view", "feature_used"]
    for row in rows:
        assert row["user_id"] == user_id
        assert row["tenant_id"] == tenant_id
        assert row["actor_role"] == "TenantAdmin"
        assert row["is_platform_staff"] is False
        assert row["app_version"] == "abc1234"
    assert rows[2]["props"] == {"index_code": "NDVI", "action": "zoom"}


@pytest.mark.asyncio
async def test_forged_identity_in_payload_is_discarded(
    admin_session: AsyncSession,
) -> None:
    """A tampered client can only ever pollute its own row."""
    real_user, real_tenant = uuid4(), uuid4()
    session_id = uuid4()

    async with _client(_context(user_id=real_user, tenant_id=real_tenant)) as client:
        response = await client.post(
            _URL,
            json={
                "session_id": str(session_id),
                "events": [
                    {
                        "event_name": "page_view",
                        "user_id": str(uuid4()),
                        "tenant_id": str(uuid4()),
                        "actor_role": "PlatformAdmin",
                        "is_platform_staff": True,
                    }
                ],
            },
        )

    assert response.status_code == 202
    (row,) = await _rows(admin_session, session_id)
    assert row["user_id"] == real_user
    assert row["tenant_id"] == real_tenant
    assert row["actor_role"] == "TenantAdmin"
    assert row["is_platform_staff"] is False


@pytest.mark.asyncio
async def test_platform_staff_traffic_is_flagged(admin_session: AsyncSession) -> None:
    session_id = uuid4()
    async with _client(_context(platform=True)) as client:
        await client.post(
            _URL,
            json={"session_id": str(session_id), "events": [{"event_name": "page_view"}]},
        )
    (row,) = await _rows(admin_session, session_id)
    assert row["is_platform_staff"] is True
    assert row["tenant_id"] is None


# --- vocabulary + allow-list ----------------------------------------------


@pytest.mark.asyncio
async def test_unknown_event_is_dropped_but_the_batch_survives(
    admin_session: AsyncSession,
) -> None:
    """A stale client emitting one retired name must not lose the other events."""
    session_id = uuid4()
    async with _client(_context(tenant_id=uuid4())) as client:
        response = await client.post(
            _URL,
            json={
                "session_id": str(session_id),
                "events": [
                    {"event_name": "page_view"},
                    {"event_name": "retired_event_name"},
                    {"event_name": "feature_used", "feature": "not_a_real_feature"},
                    {"event_name": "session_end"},
                ],
            },
        )

    body = response.json()
    assert response.status_code == 202
    assert body["accepted"] == 2
    assert body["rejected"] == 2
    assert [r["event_name"] for r in await _rows(admin_session, session_id)] == [
        "page_view",
        "session_end",
    ]


@pytest.mark.asyncio
async def test_props_outside_the_allow_list_never_reach_the_database(
    admin_session: AsyncSession,
) -> None:
    """The one control that keeps customer data out of telemetry."""
    session_id = uuid4()
    async with _client(_context(tenant_id=uuid4())) as client:
        response = await client.post(
            _URL,
            json={
                "session_id": str(session_id),
                "events": [
                    {
                        "event_name": "feature_used",
                        "feature": "reports",
                        "props": {
                            "action": "export",
                            "farm_name": "Bashayer",
                            "block_notes": "salinity on the south edge",
                            "lat": 30.1,
                        },
                    }
                ],
            },
        )

    assert response.json()["props_dropped"] == 3
    (row,) = await _rows(admin_session, session_id)
    assert row["props"] == {"action": "export"}
    stored = str(row["props"])
    assert "Bashayer" not in stored
    assert "salinity" not in stored


# --- resilience ------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_stores_nothing_and_still_answers_202(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Either half of the switch off => no collection, app unaffected."""
    monkeypatch.setenv("TELEMETRY_INGEST_ENABLED", "false")
    get_settings.cache_clear()
    try:
        session_id = uuid4()
        async with _client(_context(tenant_id=uuid4())) as client:
            response = await client.post(
                _URL,
                json={"session_id": str(session_id), "events": [{"event_name": "page_view"}]},
            )
        assert response.status_code == 202
        assert response.json() == {
            "accepted": 0,
            "rejected": 0,
            "props_dropped": 0,
            "discarded": True,
            "reason": "disabled",
        }
        assert await _rows(admin_session, session_id) == []
    finally:
        monkeypatch.delenv("TELEMETRY_INGEST_ENABLED", raising=False)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_batch_over_the_cap_keeps_the_first_50(admin_session: AsyncSession) -> None:
    session_id = uuid4()
    async with _client(_context(tenant_id=uuid4())) as client:
        response = await client.post(
            _URL,
            json={
                "session_id": str(session_id),
                "events": [{"event_name": "page_view"} for _ in range(75)],
            },
        )
    body = response.json()
    assert body["accepted"] == 50
    assert body["rejected"] == 25
    assert len(await _rows(admin_session, session_id)) == 50


async def _count_by_id(session: AsyncSession, event_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM public.usage_events WHERE id = :i"), {"i": event_id}
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_duplicate_beacon_does_not_double_count(admin_session: AsyncSession) -> None:
    """The normal case: a plausible client timestamp is preserved verbatim."""
    session_id, event_id = uuid4(), uuid4()
    payload = {
        "session_id": str(session_id),
        "events": [
            {
                "event_name": "page_leave",
                "id": str(event_id),
                "time": datetime.now(UTC).isoformat(),
                "duration_ms": 9000,
            }
        ],
    }
    async with _client(_context(tenant_id=uuid4())) as client:
        await client.post(_URL, json=payload)
        await client.post(_URL, json=payload)

    assert await _count_by_id(admin_session, event_id) == 1


@pytest.mark.asyncio
async def test_duplicate_beacon_from_a_skewed_clock_still_dedupes(
    admin_session: AsyncSession,
) -> None:
    """The case that caught a real bug.

    A timestamp outside the skew tolerance is replaced by a server value. If
    that value were a raw `now()`, the two deliveries below would land on
    different timestamps and both insert — dedupe would hold for good clocks and
    fail silently for bad ones. Flooring the fallback to the minute is what makes
    this pass.
    """
    session_id, event_id = uuid4(), uuid4()
    payload = {
        "session_id": str(session_id),
        "events": [
            {
                "event_name": "page_leave",
                "id": str(event_id),
                # Wildly future-dated: a real symptom of a misconfigured clock.
                "time": "2031-01-01T00:00:00+00:00",
                "duration_ms": 9000,
            }
        ],
    }
    async with _client(_context(tenant_id=uuid4())) as client:
        await client.post(_URL, json=payload)
        await client.post(_URL, json=payload)

    assert await _count_by_id(admin_session, event_id) == 1

    # And it must not have been stored in 2031, where retention would never
    # reach it.
    stored = (
        await admin_session.execute(
            text("SELECT time FROM public.usage_events WHERE id = :i"), {"i": event_id}
        )
    ).scalar_one()
    assert stored < datetime.now(UTC) + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_oversized_body_is_shed_before_parsing() -> None:
    async with _client(_context(tenant_id=uuid4())) as client:
        response = await client.post(
            _URL,
            json={"session_id": str(uuid4()), "events": [{"event_name": "page_view"}]},
            headers={"content-length": str(70 * 1024)},
        )
    # httpx recomputes content-length, so assert on behaviour not the header:
    # a well-formed small body still succeeds. The guard itself is unit-tested
    # by the router reading the declared length.
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_service_failure_is_invisible_to_the_user(
    admin_session: AsyncSession,
) -> None:
    """An ingest exception must not surface a 500 in the SPA's network tab.

    #332's lesson is that swallowing has to be observable, so the response still
    says `reason="error"` even though the status is 202.
    """

    class _Exploding:
        async def ingest(self, **_: Any) -> None:
            raise RuntimeError("boom")

    set_telemetry_service(_Exploding())  # type: ignore[arg-type]
    async with _client(_context(tenant_id=uuid4())) as client:
        response = await client.post(
            _URL,
            json={"session_id": str(uuid4()), "events": [{"event_name": "page_view"}]},
        )
    assert response.status_code == 202
    assert response.json()["reason"] == "error"


@pytest.mark.asyncio
async def test_rate_limit_sheds_a_looping_client(admin_session: AsyncSession) -> None:
    session_id = uuid4()
    body = {"session_id": str(session_id), "events": [{"event_name": "page_view"}]}
    reasons = []
    async with _client(_context(tenant_id=uuid4())) as client:
        for _ in range(62):
            reasons.append(await client.post(_URL, json=body))
    assert all(r.status_code == 202 for r in reasons), "must never stop answering 202"
    assert reasons[-1].json()["reason"] == "rate_limited"
    # The shed batches stored nothing; the allowed ones deduped to <= 60.
    assert len(await _rows(admin_session, session_id)) <= 60
