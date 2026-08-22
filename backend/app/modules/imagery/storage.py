"""Deterministic S3 asset-key builder for imagery COGs.

ARCHITECTURE.md § 9 commits to the layout
``{provider}/{product}/{scene_id}/{aoi_hash}/{band_or_index}.tif``.
Every imagery write goes through this builder; uniqueness across the
five components is what makes ingestion idempotent — re-running the
same job overwrites the same key rather than producing a fresh asset.

`raw_bands` is the canonical name for the multi-band TIFF the provider
returns. The six standard indices use their lowercase code
(``ndvi``, ``ndwi``, ...). Future band-level COGs would use
``b02``/``b03``/etc.; not in MVP.
"""

from __future__ import annotations

import re

# Constrain user-supplied components so a malformed `scene_id` from a
# provider can't escape the asset prefix. Sentinel-2 scene IDs match
# this; Planet/Airbus IDs are similarly conservative. A failure here
# is a programmer error, not user input.
_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_BAND_OR_INDEX_RE = re.compile(r"^[a-z0-9_]+$")
# Mirrors `AOI_RE` in tile-server/agripulse_tiles/cutline.py.
_AOI_HASH_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")


class AssetKeyError(ValueError):
    """Raised when a deterministic key would not round-trip safely."""


def build_asset_key(
    *,
    provider_code: str,
    product_code: str,
    scene_id: str,
    aoi_hash: str,
    band_or_index: str,
) -> str:
    """Return the canonical S3 key for an imagery COG.

    All inputs must be ASCII-safe; we do *not* URL-encode silently
    because a key that round-trips through STAC, presigned URLs, and
    the tile server has to be predictable.
    """
    for value, label in (
        (provider_code, "provider_code"),
        (product_code, "product_code"),
        (scene_id, "scene_id"),
        (aoi_hash, "aoi_hash"),
    ):
        if not _SAFE_RE.fullmatch(value):
            raise AssetKeyError(f"{label}={value!r} contains characters outside [A-Za-z0-9._-]")
    if not _BAND_OR_INDEX_RE.fullmatch(band_or_index):
        raise AssetKeyError(
            f"band_or_index={band_or_index!r} contains characters outside [a-z0-9_]"
        )
    return f"{provider_code}/{product_code}/{scene_id}/{aoi_hash}/{band_or_index}.tif"


def aoi_boundary_key(*, aoi_hash: str) -> str:
    """Where the tile server looks for an AOI's outline.

    One object per distinct polygon, outside the per-scene prefixes,
    because every scene cut from that polygon shares one boundary.

    The character class is narrower than `_SAFE_RE` on purpose: it has to
    match what the tile server accepts in its `cutline` parameter, so a
    key that would be refused there fails here instead of writing an
    object nothing can read.
    """
    if not _AOI_HASH_RE.fullmatch(aoi_hash):
        raise AssetKeyError(f"aoi_hash={aoi_hash!r} is not 4-128 chars of [A-Za-z0-9_-]")
    return f"aoi/{aoi_hash}.geojson"


def raw_bands_key(*, provider_code: str, product_code: str, scene_id: str, aoi_hash: str) -> str:
    """Convenience: the multi-band raw COG path."""
    return build_asset_key(
        provider_code=provider_code,
        product_code=product_code,
        scene_id=scene_id,
        aoi_hash=aoi_hash,
        band_or_index="raw_bands",
    )
