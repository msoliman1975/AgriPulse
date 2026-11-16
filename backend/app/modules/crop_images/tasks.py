"""Celery task: make a crop image's renditions after its upload is finalized."""

from __future__ import annotations

from celery import shared_task

from app.core.logging import get_logger
from app.modules.crop_images.renditions import InvalidImageError, make_renditions
from app.shared.storage import StorageObjectMissingError, get_storage_client

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="crop_images.make_renditions",
    bind=False,
    ignore_result=True,
)
def make_crop_image_renditions(original_key: str) -> list[str]:
    """Write the 64/128/256 px WebP renditions next to ``original_key``.

    No database: the key says everything. Idempotent, so a retry or a
    second run for the same key just rewrites the same objects.
    """
    try:
        written = make_renditions(get_storage_client(), original_key)
    except (InvalidImageError, StorageObjectMissingError) as exc:
        # Not retried: the bytes will not change. The crop shows its
        # letter fallback until a curator uploads a readable image.
        _log.warning("crop_image_renditions_failed", key=original_key, error=str(exc))
        return []
    _log.info("crop_image_renditions_written", key=original_key, count=len(written))
    return written
