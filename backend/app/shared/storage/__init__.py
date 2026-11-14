"""S3-compatible object storage primitives.

Public surface:

  - `StorageClient`: protocol for presigned-URL generation, head, delete.
  - `get_storage_client()`: process-wide singleton wired from settings.
  - `build_attachment_key()`: deterministic S3 key builder for attachments.
  - `build_crop_document_key()`: key builder for platform crop documents.
  - `content_disposition()`: an RFC 6266 header value for a download name.

Modules outside `app.shared` import from this package — never from the
boto3-backed implementation directly.
"""

from app.shared.storage.client import (
    PresignedDownload,
    PresignedUpload,
    StorageClient,
    StorageObjectMissingError,
    content_disposition,
    get_storage_client,
)
from app.shared.storage.keys import build_attachment_key, build_crop_document_key

__all__ = [
    "PresignedDownload",
    "PresignedUpload",
    "StorageClient",
    "StorageObjectMissingError",
    "build_attachment_key",
    "build_crop_document_key",
    "content_disposition",
    "get_storage_client",
]
