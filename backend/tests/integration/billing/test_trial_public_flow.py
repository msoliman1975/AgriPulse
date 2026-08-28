"""The unauthenticated half: form, verification, and the visitor's status page.

What these assert is mostly what the endpoint refuses to reveal. The signup
route is the only route in the service anyone on the internet can call, so
"same answer for every input" is the behaviour under test, not a detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Every test here posts the signup form, so every one needs the limiter
# out of the way. Left live, the order of the tests in this file would
# decide whether they pass.
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("_no_rate_limit")]


def _email(prefix: str) -> str:
    return f"{prefix}@{prefix}-{uuid4().hex[:8]}.test"


def _payload(email: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "full_name": "Nadia Farouk",
        "email": email,
        "organisation": f"Delta Farms {uuid4().hex[:6]}",
        "country": "EG",
        "accepts_terms": True,
    }
    body.update(overrides)
    return body


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _row(session: AsyncSession, email: str) -> dict[str, object] | None:
    result = await session.execute(
        text(
            "SELECT id, status, email_domain, status_handle, verification_token_hash "
            "FROM public.trial_signups WHERE lower(email) = :email"
        ),
        {"email": email.lower()},
    )
    row = result.mappings().first()
    return dict(row) if row else None


@pytest.mark.asyncio
async def test_signup_accepts_and_records_the_request(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    email = _email("nadia")
    async with await _client(public_app) as client:
        response = await client.post("/api/v1/public/trial/signups", json=_payload(email))

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    row = await _row(admin_session, email)
    assert row is not None
    assert row["status"] == "pending_verification"
    assert row["email_domain"] == email.split("@")[1]
    # The link is mailed, never stored. Only its hash is on the row.
    assert row["verification_token_hash"] is not None
    assert len(sent_emails) == 1
    assert "Confirm" in sent_emails[0]["subject"]


@pytest.mark.asyncio
async def test_signup_answers_the_same_for_a_repeat_address(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    """No enumeration oracle, and no mail-bombing either.

    A second request for a live address must look identical from outside
    and must not send a second email — otherwise replaying the form is a
    way to flood someone's inbox.
    """
    email = _email("repeat")
    async with await _client(public_app) as client:
        first = await client.post("/api/v1/public/trial/signups", json=_payload(email))
        second = await client.post("/api/v1/public/trial/signups", json=_payload(email))

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(sent_emails) == 1

    count = await admin_session.execute(
        text("SELECT COUNT(*) FROM public.trial_signups WHERE lower(email) = :e"),
        {"e": email.lower()},
    )
    assert count.scalar_one() == 1


@pytest.mark.asyncio
async def test_signup_without_accepting_terms_is_refused(
    public_app: FastAPI,
) -> None:
    async with await _client(public_app) as client:
        response = await client.post(
            "/api/v1/public/trial/signups",
            json=_payload(_email("noterms"), accepts_terms=False),
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_verify_puts_a_company_address_in_the_queue(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    email = _email("queued")
    async with await _client(public_app) as client:
        await client.post("/api/v1/public/trial/signups", json=_payload(email))
        token = _token_from(sent_emails[-1]["body"])
        response = await client.get(
            "/api/v1/public/trial/verify", params={"token": token}, follow_redirects=False
        )

    assert response.status_code == 303
    row = await _row(admin_session, email)
    assert row is not None
    assert row["status"] == "awaiting_approval"
    # Verification alone provisions nothing.
    tenants = await admin_session.execute(
        text("SELECT COUNT(*) FROM public.tenants WHERE contact_email = :e"),
        {"e": email},
    )
    assert tenants.scalar_one() == 0
    assert "with our team" in sent_emails[-1]["subject"]


@pytest.mark.asyncio
async def test_verify_rejects_a_disposable_domain(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    email = f"throwaway-{uuid4().hex[:6]}@mailinator.com"
    async with await _client(public_app) as client:
        await client.post("/api/v1/public/trial/signups", json=_payload(email))
        token = _token_from(sent_emails[-1]["body"])
        await client.get(
            "/api/v1/public/trial/verify", params={"token": token}, follow_redirects=False
        )

    row = await _row(admin_session, email)
    assert row is not None
    assert row["status"] == "rejected"


@pytest.mark.asyncio
async def test_verify_routes_a_known_company_to_its_administrator(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    """The rule that stops a company ending up with two tenants."""
    from app.modules.tenancy import get_tenant_service

    domain = f"already-{uuid4().hex[:8]}.test"
    service = get_tenant_service(admin_session)
    await service.create_tenant(
        slug=f"known-{uuid4().hex[:8]}",
        name="Known Customer",
        contact_email=f"ops@{domain}",
    )
    await admin_session.commit()

    email = f"newperson@{domain}"
    async with await _client(public_app) as client:
        await client.post("/api/v1/public/trial/signups", json=_payload(email))
        token = _token_from(sent_emails[-1]["body"])
        await client.get(
            "/api/v1/public/trial/verify", params={"token": token}, follow_redirects=False
        )

    row = await _row(admin_session, email)
    assert row is not None
    assert row["status"] == "routed_to_existing"
    assert "already uses AgriPulse" in sent_emails[-1]["subject"]


@pytest.mark.asyncio
async def test_an_expired_link_does_not_verify(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    email = _email("stale")
    async with await _client(public_app) as client:
        await client.post("/api/v1/public/trial/signups", json=_payload(email))
        token = _token_from(sent_emails[-1]["body"])

        await admin_session.execute(
            text(
                "UPDATE public.trial_signups SET verification_expires_at = :past "
                "WHERE lower(email) = :e"
            ),
            {"past": datetime.now(UTC) - timedelta(hours=1), "e": email.lower()},
        )
        await admin_session.commit()

        await client.get(
            "/api/v1/public/trial/verify", params={"token": token}, follow_redirects=False
        )

    row = await _row(admin_session, email)
    assert row is not None
    assert row["status"] == "expired"


@pytest.mark.asyncio
async def test_status_page_reads_the_handle(
    public_app: FastAPI,
    admin_session: AsyncSession,
    sent_emails: list[dict[str, str]],
) -> None:
    email = _email("statuspage")
    async with await _client(public_app) as client:
        await client.post("/api/v1/public/trial/signups", json=_payload(email))
        row = await _row(admin_session, email)
        assert row is not None
        response = await client.get(f"/api/v1/public/trial/status/{row['status_handle']}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "pending_verification"
    # The page is keyed on a URL parameter, so it must carry nothing that a
    # stranger holding the link should not see.
    assert "email" not in body
    assert "id" not in body


@pytest.mark.asyncio
async def test_status_page_404s_on_an_unknown_handle(public_app: FastAPI) -> None:
    async with await _client(public_app) as client:
        response = await client.get("/api/v1/public/trial/status/not-a-real-handle")
    assert response.status_code == 404


def _token_from(body: str) -> str:
    """Pull the verification token out of the mail we captured."""
    for word in body.split():
        if "token=" in word:
            return word.split("token=", 1)[1].strip()
    raise AssertionError(f"no verification link in email body: {body!r}")
