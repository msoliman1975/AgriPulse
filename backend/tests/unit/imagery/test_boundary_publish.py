"""Publishing a farm outline for the tile server's cutline.

The rule under test is that this is never allowed to sink an imagery job.
Losing the outline costs the border cut; losing the job costs the scene.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.imagery.boundary import publish_aoi_boundary

_AOI = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
_BOUNDARY = {
    "type": "Polygon",
    "coordinates": [[[31.0, 30.0], [31.1, 30.0], [31.1, 30.1], [31.0, 30.1], [31.0, 30.0]]],
}


class FakeStorage:
    """Records what was written. Raises on demand."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.puts: list[dict[str, Any]] = []

    @property
    def bucket(self) -> str:
        return "bucket"

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        if self.fail:
            raise RuntimeError("s3 is down")
        self.puts.append({"key": key, "body": body, "content_type": content_type})


def test_writes_the_outline_at_the_aoi_key() -> None:
    storage = FakeStorage()

    key = publish_aoi_boundary(storage, aoi_hash=_AOI, boundary_geojson=_BOUNDARY)

    assert key == f"aoi/{_AOI}.geojson"
    assert storage.puts[0]["key"] == key
    assert storage.puts[0]["content_type"] == "application/geo+json"
    assert json.loads(storage.puts[0]["body"]) == _BOUNDARY


def test_a_storage_failure_is_reported_as_none_not_raised() -> None:
    storage = FakeStorage(fail=True)

    assert publish_aoi_boundary(storage, aoi_hash=_AOI, boundary_geojson=_BOUNDARY) is None


def test_a_key_the_tile_server_would_refuse_is_not_written() -> None:
    storage = FakeStorage()

    assert publish_aoi_boundary(storage, aoi_hash="has/slash", boundary_geojson=_BOUNDARY) is None
    assert storage.puts == []


def test_nothing_to_publish_writes_nothing() -> None:
    storage = FakeStorage()

    assert publish_aoi_boundary(storage, aoi_hash=None, boundary_geojson=_BOUNDARY) is None
    assert publish_aoi_boundary(storage, aoi_hash=_AOI, boundary_geojson=None) is None
    assert storage.puts == []
