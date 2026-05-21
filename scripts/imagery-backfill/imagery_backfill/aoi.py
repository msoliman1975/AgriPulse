"""AOI loading + per-block metadata derivation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

_NS_BLOCK = uuid.UUID("c8e0a2a8-2c20-5f3f-b1f1-aab1e1b1a001")
_NS_SUBSCRIPTION = uuid.UUID("c8e0a2a8-2c20-5f3f-b1f1-aab1e1b1a002")
_NS_JOB = uuid.UUID("c8e0a2a8-2c20-5f3f-b1f1-aab1e1b1a003")


@dataclass(frozen=True, slots=True)
class Block:
    block_id: uuid.UUID
    name: str
    boundary_wgs84: dict[str, Any]
    boundary_utm: dict[str, Any]
    aoi_hash: str
    area_m2: float


def load_blocks(
    aoi_path: Path,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    utm_epsg: int = 32636,
) -> tuple[Block, ...]:
    payload = json.loads(aoi_path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{aoi_path}: expected FeatureCollection, got {payload.get('type')!r}")
    features = payload.get("features") or []
    if not features:
        raise ValueError(f"{aoi_path}: FeatureCollection has zero features")

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
    project = transformer.transform

    seen_names: set[str] = set()
    blocks: list[Block] = []
    for idx, feature in enumerate(features):
        props = feature.get("properties") or {}
        name = props.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"{aoi_path}: feature[{idx}] is missing required string `properties.name`"
            )
        name = name.strip()
        if name in seen_names:
            raise ValueError(f"{aoi_path}: duplicate `properties.name`={name!r}")
        seen_names.add(name)

        geom_dict = feature.get("geometry")
        if not geom_dict or geom_dict.get("type") != "Polygon":
            raise ValueError(
                f"{aoi_path}: feature[{idx}] ({name!r}) geometry must be a Polygon"
            )
        geom_wgs84: BaseGeometry = shape(geom_dict)
        if not geom_wgs84.is_valid:
            raise ValueError(f"{aoi_path}: feature[{idx}] ({name!r}) polygon is invalid")

        geom_utm = shapely_transform(project, geom_wgs84)
        aoi_hash = hashlib.sha256(geom_utm.wkt.encode("ascii")).hexdigest()

        block_id_seed = f"{tenant_id}|{farm_id}|{name}"
        blocks.append(
            Block(
                block_id=uuid.uuid5(_NS_BLOCK, block_id_seed),
                name=name,
                boundary_wgs84=mapping(geom_wgs84),
                boundary_utm=mapping(geom_utm),
                aoi_hash=aoi_hash,
                area_m2=float(geom_utm.area),
            )
        )

    return tuple(blocks)


def derive_subscription_id(block_id: uuid.UUID, product_code: str) -> uuid.UUID:
    return uuid.uuid5(_NS_SUBSCRIPTION, f"{block_id}|{product_code}")


def derive_job_id(subscription_id: uuid.UUID, scene_id: str) -> uuid.UUID:
    return uuid.uuid5(_NS_JOB, f"{subscription_id}|{scene_id}")
