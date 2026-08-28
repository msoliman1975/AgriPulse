"""Fixtures for the trial signup surface.

Two apps are built here, because the two routers are reached differently:

  * the public router runs with **no auth middleware at all** — that is the
    thing under test, so stubbing a context would test the wrong app;
  * the platform router runs behind the same stubbed context the other
    platform-admin suites use, so the capability dependency is exercised.

Emails are captured rather than sent. The point of the assertions is which
message went to whom, not SMTP.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.billing.public_router import router as public_router
from app.modules.billing.trials_router import router as trials_router
from app.shared.auth.context import PlatformRole, RequestContext


class StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def make_context(platform_role: PlatformRole | None) -> RequestContext:
    """`platform_role` is the enum, not its string.

    `CapabilityRegistry.has_capability` reads `.value` off it, so a plain
    string raises AttributeError rather than denying — a test written with
    a string would fail for the wrong reason.
    """
    user_id = uuid4()
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=None,
        tenant_role=None,
        platform_role=platform_role,
        farm_scopes=(),
    )


@pytest.fixture
def public_app() -> FastAPI:
    """No auth middleware — exactly how the route is reached in production,
    where `_is_public` short-circuits before any token is looked for.
    """
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(public_router)
    return app


@pytest.fixture
def platform_app_factory() -> Any:
    def _build(platform_role: PlatformRole | None) -> FastAPI:
        app = FastAPI()
        install_exception_handlers(app)
        app.include_router(trials_router)
        app.add_middleware(StubAuth, context=make_context(platform_role))
        return app

    return _build


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, str]]]:
    """Capture every trial email.

    Patched at `app.modules.billing.emails.send_email`, which is the name
    the module actually calls — patching the notifications module would
    leave this import bound to the original function.
    """
    captured: list[dict[str, str]] = []

    def _capture(*, to_address: str, subject: str, body_text: str, **_: object) -> None:
        captured.append({"to": to_address, "subject": subject, "body": body_text})

    monkeypatch.setattr("app.modules.billing.emails.send_email", _capture)
    return captured


@pytest.fixture
def no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004 — named for the test signatures that request it
    """Let every request through the limiter.

    The limiter is tested on its own. Leaving it live here would make the
    order of tests in this file decide whether they pass, which is the kind
    of green suite that hides a real failure.
    """
    from app.shared.ratelimit import LimitResult

    async def _allow(**_: object) -> LimitResult:
        return LimitResult(allowed=True, used=1, limit=99, retry_after_seconds=0)

    monkeypatch.setattr("app.modules.billing.public_router.check_and_increment", _allow)


@pytest.fixture
def enqueued_tasks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record what the approve route hands to Celery instead of sending it.

    Asserting the enqueue is the point: approval is the only trigger for
    provisioning, and a test that let the task run would be testing Celery.
    """
    calls: list[str] = []

    def _enqueue(signup_id: UUID) -> None:
        calls.append(str(signup_id))

    monkeypatch.setattr(
        "app.modules.billing.trials_router._enqueue_provisioning", _enqueue
    )
    return calls
