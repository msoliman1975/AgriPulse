"""Unit tests for the correlation ID middleware.

We mount the middleware on a tiny Starlette app and exercise it with the
synchronous TestClient.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.shared.correlation.middleware import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
    get_correlation_id,
)


@pytest.fixture
def app() -> Starlette:
    async def echo(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "state_id": getattr(request.state, "correlation_id", None),
                "ctxvar_id": get_correlation_id(),
            }
        )

    starlette_app = Starlette(routes=[Route("/echo", echo)])
    starlette_app.add_middleware(CorrelationIdMiddleware)
    return starlette_app


@pytest.fixture
def client(app: Starlette) -> TestClient:
    return TestClient(app)


def test_generates_uuid_when_header_missing(client: TestClient) -> None:
    response = client.get("/echo")
    assert response.status_code == 200
    cid = response.headers[CORRELATION_HEADER]
    assert len(cid) == 36  # uuid4 string form
    body = response.json()
    assert body["state_id"] == cid
    assert body["ctxvar_id"] == cid


def test_propagates_existing_header(client: TestClient) -> None:
    response = client.get(
        "/echo", headers={CORRELATION_HEADER: "00000000-0000-0000-0000-deadbeef0001"}
    )
    assert response.status_code == 200
    assert response.headers[CORRELATION_HEADER] == "00000000-0000-0000-0000-deadbeef0001"
    body = response.json()
    assert body["state_id"] == "00000000-0000-0000-0000-deadbeef0001"


def test_per_request_ids_are_independent(client: TestClient) -> None:
    a = client.get("/echo").headers[CORRELATION_HEADER]
    b = client.get("/echo").headers[CORRELATION_HEADER]
    assert a != b
