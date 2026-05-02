"""Unit tests for the deterministic imagery asset-key builder."""

from __future__ import annotations

import pytest

from app.modules.imagery.storage import (
    AssetKeyError,
    build_asset_key,
    raw_bands_key,
)

_VALID_AOI = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"


def test_build_key_layout_per_arch_section_9() -> None:
    """`{provider}/{product}/{scene_id}/{aoi_hash}/{band_or_index}.tif`"""
    key = build_asset_key(
        provider_code="sentinel_hub",
        product_code="s2_l2a",
        scene_id="S2A_MSIL2A_20260501T084601",
        aoi_hash=_VALID_AOI,
        band_or_index="ndvi",
    )
    assert key == f"sentinel_hub/s2_l2a/S2A_MSIL2A_20260501T084601/{_VALID_AOI}/ndvi.tif"


def test_raw_bands_key_uses_raw_bands_filename() -> None:
    key = raw_bands_key(
        provider_code="sentinel_hub",
        product_code="s2_l2a",
        scene_id="abc",
        aoi_hash=_VALID_AOI,
    )
    assert key.endswith("/raw_bands.tif")


def test_keys_are_deterministic_across_calls() -> None:
    """Two calls with the same args must produce byte-identical keys."""
    a = build_asset_key(
        provider_code="sentinel_hub",
        product_code="s2_l2a",
        scene_id="abc",
        aoi_hash=_VALID_AOI,
        band_or_index="ndvi",
    )
    b = build_asset_key(
        provider_code="sentinel_hub",
        product_code="s2_l2a",
        scene_id="abc",
        aoi_hash=_VALID_AOI,
        band_or_index="ndvi",
    )
    assert a == b


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("provider_code", "bad slash/here"),
        ("product_code", "with space"),
        ("scene_id", "with;semi"),
        ("aoi_hash", "naïve"),
    ],
)
def test_unsafe_chars_in_id_raises(field: str, bad: str) -> None:
    args = {
        "provider_code": "sentinel_hub",
        "product_code": "s2_l2a",
        "scene_id": "S2A",
        "aoi_hash": _VALID_AOI,
        "band_or_index": "ndvi",
    }
    args[field] = bad
    with pytest.raises(AssetKeyError):
        build_asset_key(**args)


def test_band_or_index_must_be_lower_snake() -> None:
    """No uppercase, no dashes — keeps the assets dictionary keys stable."""
    with pytest.raises(AssetKeyError):
        build_asset_key(
            provider_code="sentinel_hub",
            product_code="s2_l2a",
            scene_id="abc",
            aoi_hash=_VALID_AOI,
            band_or_index="NDVI",
        )
