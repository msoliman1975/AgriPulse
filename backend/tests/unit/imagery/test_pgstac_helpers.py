"""Unit tests for pgstac collection / item helpers (pure-function parts)."""

from __future__ import annotations

import pytest

from app.modules.imagery.pgstac import (
    CollectionIdError,
    build_collection_doc,
    build_item_doc,
    collection_id_for,
)


def test_collection_id_for_valid_inputs() -> None:
    cid = collection_id_for("tenant_abc123", "s2_l2a")
    assert cid == "tenant_abc123__s2_l2a"


@pytest.mark.parametrize(
    ("schema", "product"),
    [
        ("not_a_tenant", "s2_l2a"),  # missing tenant_ prefix
        ("tenant_BadCase", "s2_l2a"),  # uppercase rejected
        ("tenant_abc", "S2-L2A"),  # product code with dash + uppercase
    ],
)
def test_collection_id_for_rejects_malformed_inputs(schema: str, product: str) -> None:
    with pytest.raises(CollectionIdError):
        collection_id_for(schema, product)


def test_build_collection_doc_minimal_shape() -> None:
    doc = build_collection_doc(collection_id="tenant_x__s2_l2a", product_code="s2_l2a")
    assert doc["type"] == "Collection"
    assert doc["id"] == "tenant_x__s2_l2a"
    assert doc["stac_version"].startswith("1.")
    assert "extent" in doc
    assert "spatial" in doc["extent"]


def test_build_item_doc_carries_assets_and_datetime() -> None:
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    doc = build_item_doc(
        collection_id="tenant_x__s2_l2a",
        item_id="sentinel_hub/s2_l2a/SCENE/AOI",
        geometry_geojson=geometry,
        bbox=(0.0, 0.0, 1.0, 1.0),
        scene_datetime_iso="2026-05-01T10:00:00Z",
        assets={
            "raw_bands": {
                "href": "s3://bucket/key.tif",
                "type": "image/tiff",
                "roles": ["data"],
            }
        },
        properties={"eo:cloud_cover": 12.5},
    )
    assert doc["type"] == "Feature"
    assert doc["id"] == "sentinel_hub/s2_l2a/SCENE/AOI"
    assert doc["collection"] == "tenant_x__s2_l2a"
    assert doc["properties"]["datetime"] == "2026-05-01T10:00:00Z"
    assert doc["properties"]["eo:cloud_cover"] == 12.5
    assert "raw_bands" in doc["assets"]
