"""Publish a farm outline where the tile server can read it.

The tile server cuts every rendered tile to the farm boundary, which
removes the pixel of colour the stored raster still carries outside the
border. It cannot ask the database for that boundary: it holds no tenant
context, no credentials, and no knowledge of which farm a raster belongs
to. So the boundary is written beside the imagery, as one small GeoJSON
object per distinct polygon.

The key is the AOI hash, which is a hash of the polygon itself. That
makes the object content-addressed: it can never describe a shape other
than the one the raster was cut from, a re-write is the same bytes, and
the tile server can cache it for the life of the process.

A farm without this object draws exactly as it drew before the cutline
existed - with the fringe. That is why every caller here treats a
failure as something to log and carry on from, never as a reason to fail
an imagery job.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.modules.imagery.storage import aoi_boundary_key
from app.shared.storage import StorageClient

_log = get_logger(__name__)


def publish_aoi_boundary(
    storage: StorageClient,
    *,
    aoi_hash: str | None,
    boundary_geojson: dict[str, Any] | None,
) -> str | None:
    """Write one AOI outline. Returns the key written, or None.

    Stored in EPSG:4326, which is what GeoJSON means by coordinates and
    what the tile server reprojects from.
    """
    if not aoi_hash or not boundary_geojson:
        return None
    try:
        key = aoi_boundary_key(aoi_hash=aoi_hash)
        storage.put_object(
            key=key,
            body=json.dumps(boundary_geojson, separators=(",", ":")).encode("utf-8"),
            content_type="application/geo+json",
        )
    except Exception:
        # Losing the outline costs the border cut, not the imagery.
        _log.warning("aoi_boundary_publish_failed", aoi_hash=aoi_hash, exc_info=True)
        return None
    return key
