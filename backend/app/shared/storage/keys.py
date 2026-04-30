"""Deterministic S3 key builder for tenant-scoped attachments.

Layout: ``tenants/<tenant_uuid>/<owner_kind>/<owner_uuid>/attachments/<attachment_uuid>/<safe_filename>``.

The leading ``tenants/<tenant_uuid>`` prefix lets us apply a per-tenant
S3 lifecycle policy or hand a presigned listing URL to support without
exposing other tenants. ``safe_filename`` keeps a URL-safe slug of the
original so the human-friendly name survives the round trip; consumers
should still rely on the row's ``original_filename`` for display.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

OwnerKind = Literal["farms", "blocks"]

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LEN = 80


def build_attachment_key(
    *,
    tenant_id: UUID,
    owner_kind: OwnerKind,
    owner_id: UUID,
    attachment_id: UUID,
    original_filename: str,
) -> str:
    safe = _SAFE_FILENAME_RE.sub("_", original_filename).strip("._-") or "file"
    if len(safe) > _MAX_FILENAME_LEN:
        # Preserve extension when truncating.
        if "." in safe:
            stem, _, ext = safe.rpartition(".")
            safe = f"{stem[: _MAX_FILENAME_LEN - len(ext) - 1]}.{ext}"
        else:
            safe = safe[:_MAX_FILENAME_LEN]
    return f"tenants/{tenant_id}/{owner_kind}/{owner_id}/attachments/{attachment_id}/{safe}"
