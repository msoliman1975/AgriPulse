"""boto3-backed S3 client with presigned-URL helpers.

Why boto3 (sync) inside async handlers:
    All operations are short metadata calls (presign builds a string,
    head_object/delete_object are single HTTP requests). Wrapping in a
    thread executor would buy nothing and add scheduler overhead. The
    server has tens of milliseconds of headroom on these calls; if we
    ever need bulk listing or large copies we'll add an async path.

The factory is process-wide and cached so the boto3 session and HTTP
connection pool are reused across requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.settings import get_settings
from app.shared import clock


class StorageObjectMissingError(Exception):
    """Raised by `head_object` / `delete_object` when the key is gone.

    Consumers translate this to a 404 or warning depending on whether the
    missing object is expected (delete after delete) or a hard error
    (finalize before upload).
    """

    def __init__(self, bucket: str, key: str) -> None:
        super().__init__(f"object missing: {bucket}/{key}")
        self.bucket = bucket
        self.key = key


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PresignedDownload:
    url: str
    expires_at: datetime


class StorageClient(Protocol):
    """The narrow surface other modules consume."""

    @property
    def bucket(self) -> str: ...

    def presign_upload(
        self,
        *,
        key: str,
        content_type: str,
        content_length: int,
        expires_seconds: int | None = None,
    ) -> PresignedUpload: ...

    def presign_download(
        self,
        *,
        key: str,
        expires_seconds: int | None = None,
        response_content_disposition: str | None = None,
        response_content_type: str | None = None,
    ) -> PresignedDownload: ...

    def head_object(self, *, key: str) -> dict[str, Any]: ...

    def delete_object(self, *, key: str) -> None: ...

    def put_object(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None: ...


class _Boto3StorageClient:
    """Concrete boto3 implementation. Internal — consumers use StorageClient."""

    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket_uploads
        self._default_expires = settings.s3_presign_expires_seconds
        # In-cluster the workloads run with IRSA — we want boto3 to walk
        # its default credential chain (which finds the IRSA-projected
        # token). Passing empty-string creds to boto3.client overrides
        # that chain with broken creds, so only forward explicit creds
        # when they're actually set. Same for endpoint_url: an empty
        # string is the "no override → real AWS S3" signal from the
        # chart overlay.
        kwargs: dict[str, Any] = {
            "region_name": settings.s3_region,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_path_style else "auto"},
            ),
        }
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        if settings.s3_access_key_id and settings.s3_secret_access_key:
            kwargs["aws_access_key_id"] = settings.s3_access_key_id
            kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
        self._client = boto3.client("s3", **kwargs)

    @property
    def bucket(self) -> str:
        return self._bucket

    def presign_upload(
        self,
        *,
        key: str,
        content_type: str,
        content_length: int,
        expires_seconds: int | None = None,
    ) -> PresignedUpload:
        expires = expires_seconds or self._default_expires
        url: str = self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
            },
            ExpiresIn=expires,
            HttpMethod="PUT",
        )
        # The presigned URL signs ContentType and ContentLength into the
        # querystring; the client must echo both as request headers.
        return PresignedUpload(
            url=url,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(content_length),
            },
            expires_at=clock.now() + timedelta(seconds=expires),
        )

    def presign_download(
        self,
        *,
        key: str,
        expires_seconds: int | None = None,
        response_content_disposition: str | None = None,
        response_content_type: str | None = None,
    ) -> PresignedDownload:
        expires = expires_seconds or self._default_expires
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        # S3 signs these into the URL and answers with them as headers, which
        # is how one stored object serves both "view" (inline) and "download"
        # (attachment) without a second copy.
        if response_content_disposition is not None:
            params["ResponseContentDisposition"] = response_content_disposition
        if response_content_type is not None:
            params["ResponseContentType"] = response_content_type
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires,
            HttpMethod="GET",
        )
        return PresignedDownload(
            url=url,
            expires_at=clock.now() + timedelta(seconds=expires),
        )

    def head_object(self, *, key: str) -> dict[str, Any]:
        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                raise StorageObjectMissingError(self._bucket, key) from exc
            raise

    def delete_object(self, *, key: str) -> None:
        # S3 deletes are idempotent — but we surface the missing-object
        # signal so audit can log it.
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def put_object(
        self,
        *,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        """Server-side upload — used by Celery workers writing imagery COGs.

        Presigned URLs are the right pattern when the client (browser
        or mobile app) holds the bytes. The Celery worker holds the
        bytes itself, so a single boto3 call is simpler and skips the
        round-trip the presigned-PUT pattern requires.
        """
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


def content_disposition(filename: str, *, inline: bool) -> str:
    """An RFC 6266 ``Content-Disposition`` value that survives any filename.

    The ASCII ``filename=`` is a fallback for old clients; ``filename*`` carries
    the real name UTF-8 percent-encoded, so an Arabic title downloads as itself.
    """
    disposition = "inline" if inline else "attachment"
    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename)
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{fallback or 'file'}\"; filename*=UTF-8''{encoded}"


@lru_cache(maxsize=1)
def get_storage_client() -> StorageClient:
    """Return the singleton storage client.

    Tests override by clearing the cache and patching `get_storage_client`
    at the import site.
    """
    return _Boto3StorageClient()
