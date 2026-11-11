"""The API compresses JSON bodies, and leaves the SSE stream alone.

Nothing in front of the API compresses (ingress-nginx runs with its default
use-gzip off), so this middleware is the only thing that shrinks a farm map
full of GeoJSON. Routes are added under the public prefix so the real
middleware stack from ``create_app`` runs without a bearer token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core.app_factory import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    app: FastAPI = create_app()

    @app.get("/api/v1/public/__gzip_big")
    async def big() -> dict[str, str]:
        return {"x": "a" * 5000}

    @app.get("/api/v1/public/__gzip_small")
    async def small() -> dict[str, str]:
        return {"x": "a"}

    @app.get("/api/v1/public/__gzip_sse")
    async def sse() -> StreamingResponse:
        async def events() -> AsyncIterator[bytes]:
            yield b"data: " + b"a" * 5000 + b"\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return TestClient(app)


def test_large_json_is_gzipped(client: TestClient) -> None:
    resp = client.get("/api/v1/public/__gzip_big", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in resp.headers["vary"]
    assert resp.json() == {"x": "a" * 5000}


def test_small_json_is_not_gzipped(client: TestClient) -> None:
    resp = client.get("/api/v1/public/__gzip_small", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in resp.headers


def test_without_accept_encoding_nothing_is_gzipped(client: TestClient) -> None:
    resp = client.get("/api/v1/public/__gzip_big", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in resp.headers


def test_event_stream_is_not_gzipped(client: TestClient) -> None:
    resp = client.get("/api/v1/public/__gzip_sse", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
