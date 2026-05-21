"""Manifest writer — emits the upload-ready records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from imagery_backfill.aoi import Block
from imagery_backfill.indices import IndexAggregates

PROVIDER_CODE = "sentinel_hub"
PRODUCT_CODE = "s2_l2a"


def asset_key(*, scene_id: str, aoi_hash: str, band_or_index: str) -> str:
    return f"{PROVIDER_CODE}/{PRODUCT_CODE}/{scene_id}/{aoi_hash}/{band_or_index}.tif"


def stac_item_id(*, scene_id: str, aoi_hash: str) -> str:
    return f"{PROVIDER_CODE}/{PRODUCT_CODE}/{scene_id}/{aoi_hash}"


def build_pgstac_item(
    *,
    collection_id: str,
    scene_id: str,
    scene_datetime_iso: str,
    aoi_hash: str,
    block: Block,
    cloud_cover_pct: Decimal | None,
    bucket_placeholder: str,
    asset_paths: dict[str, str],
    band_names: tuple[str, ...],
) -> dict[str, Any]:
    bbox = _bbox_polygon(block.boundary_wgs84)
    assets: dict[str, Any] = {
        "raw_bands": {
            "href": f"s3://{bucket_placeholder}/{asset_paths['raw_bands']}",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "bands": list(band_names),
        }
    }
    for index_code, key in asset_paths.items():
        if index_code == "raw_bands":
            continue
        assets[index_code] = {
            "href": f"s3://{bucket_placeholder}/{key}",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data", "index"],
            "title": index_code.upper(),
        }
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": stac_item_id(scene_id=scene_id, aoi_hash=aoi_hash),
        "collection": collection_id,
        "geometry": block.boundary_wgs84,
        "bbox": list(bbox),
        "properties": {
            "datetime": scene_datetime_iso,
            "eo:cloud_cover": float(cloud_cover_pct) if cloud_cover_pct is not None else None,
            "agripulse:scene_id": scene_id,
            "agripulse:aoi_hash": aoi_hash,
        },
        "assets": assets,
        "links": [],
    }


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    block: dict[str, Any]
    subscription: dict[str, Any]
    ingestion_job: dict[str, Any]
    pgstac_item: dict[str, Any]
    assets: dict[str, str]
    aggregates: dict[str, dict[str, Any]]


def aggregates_to_dict(agg: IndexAggregates, *, cloud_cover_pct: Decimal | None) -> dict[str, Any]:
    return {
        "mean": _dec(agg.mean),
        "min": _dec(agg.min),
        "max": _dec(agg.max),
        "p10": _dec(agg.p10),
        "p50": _dec(agg.p50),
        "p90": _dec(agg.p90),
        "std_dev": _dec(agg.std_dev),
        "valid_pixel_count": agg.valid_pixel_count,
        "total_pixel_count": agg.total_pixel_count,
        "cloud_cover_pct": _dec(cloud_cover_pct),
    }


def write_manifest_line(out: Path, record: ManifestRecord) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fp:
        json.dump(asdict(record), fp, default=_json_default, ensure_ascii=False)
        fp.write("\n")


def write_summary(out: Path, payload: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False),
        encoding="utf-8",
    )


def read_existing_manifest_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                seen.add((rec["block"]["block_id"], rec["ingestion_job"]["scene_id"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def _bbox_polygon(geojson_polygon: dict[str, Any]) -> tuple[float, float, float, float]:
    coords = geojson_polygon["coordinates"][0]
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _dec(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unserializable: {type(value).__name__}")
