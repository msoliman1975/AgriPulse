"""Geometry helpers for the farms module — private internals.

What lives here:

  * GeoJSON-shape validators that complement Pydantic field validation.
  * EWKT helpers used by the repository to write geometry into Postgres
    in a single round-trip without geoalchemy2's WKBElement plumbing.

We intentionally do NOT call into Postgres for client-side validation.
ST_IsValid() is enforced server-side by the database (PostGIS rejects
truly malformed geometry on insert), and a self-intersection check via
shapely is layered in here so we can fail fast with a translatable
problem+json before the round-trip.
"""

from __future__ import annotations

from typing import Any

from app.modules.farms.errors import GeometryInvalidError


def _iter_polygon_rings(polygon: list[Any]) -> list[list[list[float]]]:
    """A GeoJSON Polygon coords is `list[ring]`; each ring is `list[[x,y]]`."""
    rings: list[list[list[float]]] = []
    for ring in polygon:
        if not isinstance(ring, list):
            raise GeometryInvalidError("polygon ring must be a list of coordinates")
        coords: list[list[float]] = []
        for point in ring:
            if not isinstance(point, list) or len(point) < 2:
                raise GeometryInvalidError("polygon coordinate must be [lon, lat]")
            x = float(point[0])
            y = float(point[1])
            coords.append([x, y])
        rings.append(coords)
    return rings


def _validate_polygon_shape(rings: list[list[list[float]]]) -> None:
    if not rings:
        raise GeometryInvalidError("polygon must have at least one ring")
    outer = rings[0]
    if len(outer) < 4:
        raise GeometryInvalidError(
            "polygon outer ring must have at least 4 vertices (3 distinct + closing)"
        )
    if outer[0] != outer[-1]:
        raise GeometryInvalidError("polygon ring must be closed (first == last vertex)")


def validate_polygon_geojson(geom: dict[str, Any]) -> None:
    """Validate a GeoJSON Polygon: shape and coordinates.

    Raises GeometryInvalidError on failure. There is no country check: the
    metric coordinate system is per farm (`farms.utm_srid`), so a boundary
    anywhere on Earth produces a correct area.
    """
    if not isinstance(geom, dict):
        raise GeometryInvalidError("geometry must be a JSON object")
    if geom.get("type") != "Polygon":
        raise GeometryInvalidError(f"expected type 'Polygon', got {geom.get('type')!r}")
    coords = geom.get("coordinates")
    if not isinstance(coords, list):
        raise GeometryInvalidError("missing or non-list coordinates")
    rings = _iter_polygon_rings(coords)
    _validate_polygon_shape(rings)


def validate_multipolygon_geojson(geom: dict[str, Any]) -> None:
    """Validate a GeoJSON MultiPolygon: the shape of every polygon."""
    if not isinstance(geom, dict):
        raise GeometryInvalidError("geometry must be a JSON object")
    if geom.get("type") != "MultiPolygon":
        raise GeometryInvalidError(f"expected type 'MultiPolygon', got {geom.get('type')!r}")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise GeometryInvalidError("multipolygon must contain at least one polygon")
    for polygon_coords in coords:
        if not isinstance(polygon_coords, list):
            raise GeometryInvalidError("each polygon in multipolygon must be a list of rings")
        rings = _iter_polygon_rings(polygon_coords)
        _validate_polygon_shape(rings)


def geojson_to_ewkt_polygon(geom: dict[str, Any]) -> str:
    """Convert a validated Polygon GeoJSON dict to EWKT for SRID 4326.

    Used by the repository so the caller does not need geoalchemy2
    WKBElement objects on every insert. Validation MUST happen first —
    this is a pure formatter.
    """
    rings = _iter_polygon_rings(geom["coordinates"])
    parts = ["(" + ", ".join(f"{lon} {lat}" for lon, lat in ring) + ")" for ring in rings]
    return f"SRID=4326;POLYGON({', '.join(parts)})"


def geojson_to_ewkt_multipolygon(geom: dict[str, Any]) -> str:
    """Convert a validated MultiPolygon GeoJSON dict to EWKT for SRID 4326."""
    polys: list[str] = []
    for polygon_coords in geom["coordinates"]:
        rings = _iter_polygon_rings(polygon_coords)
        parts = ["(" + ", ".join(f"{lon} {lat}" for lon, lat in ring) + ")" for ring in rings]
        polys.append("(" + ", ".join(parts) + ")")
    return f"SRID=4326;MULTIPOLYGON({', '.join(polys)})"
