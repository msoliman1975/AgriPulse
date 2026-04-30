"""Unit tests for the storage client wrapper.

We don't talk to a real S3 here — `boto3.client('s3').generate_presigned_url`
is pure: it produces a string from the request shape without touching the
network. Verifying it returns a non-empty URL with the expected query args
is enough to catch wiring regressions.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from botocore.exceptions import ClientError

from app.core.settings import get_settings
from app.shared.storage.client import (
    StorageObjectMissingError,
    _Boto3StorageClient,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Boto3StorageClient:
    # Pin settings so the test isn't sensitive to dev .env values.
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("S3_BUCKET_UPLOADS", "test-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("S3_PRESIGN_EXPIRES_SECONDS", "300")
    get_settings.cache_clear()
    return _Boto3StorageClient()


def test_presign_upload_returns_url_with_signed_querystring(
    client: _Boto3StorageClient,
) -> None:
    upload = client.presign_upload(
        key="tenants/x/y/file.bin", content_type="image/jpeg", content_length=1234
    )
    parsed = urlparse(upload.url)
    qs = parse_qs(parsed.query)
    assert "X-Amz-Signature" in qs
    assert "X-Amz-Expires" in qs
    assert upload.headers == {
        "Content-Type": "image/jpeg",
        "Content-Length": "1234",
    }


def test_presign_download_returns_url(client: _Boto3StorageClient) -> None:
    download = client.presign_download(key="tenants/x/y/file.bin")
    assert download.url.startswith("http")
    assert "X-Amz-Signature" in download.url


def test_head_object_translates_404_to_missing_error(
    client: _Boto3StorageClient,
) -> None:
    # Replace the bound boto3 client with a stub that raises a NotFound.
    class _Stub:
        def head_object(self, **_kwargs: object) -> object:
            raise ClientError(
                error_response={"Error": {"Code": "404", "Message": "Not Found"}},
                operation_name="HeadObject",
            )

    client._client = _Stub()  # type: ignore[assignment]
    with pytest.raises(StorageObjectMissingError):
        client.head_object(key="missing")


def test_head_object_propagates_other_client_errors(
    client: _Boto3StorageClient,
) -> None:
    class _Stub:
        def head_object(self, **_kwargs: object) -> object:
            raise ClientError(
                error_response={"Error": {"Code": "AccessDenied"}},
                operation_name="HeadObject",
            )

    client._client = _Stub()  # type: ignore[assignment]
    with pytest.raises(ClientError):
        client.head_object(key="any")
