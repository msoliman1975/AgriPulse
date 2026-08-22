"""Unit tests for the farms geometry helpers."""

from __future__ import annotations

import pytest

from app.modules.farms.errors import GeometryInvalidError
from app.modules.farms.geometry import (
    geojson_to_ewkt_multipolygon,
    geojson_to_ewkt_polygon,
    validate_multipolygon_geojson,
    validate_polygon_geojson,
)


def _square_polygon(lon: float, lat: float, size: float = 0.001) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + size, lat],
                [lon + size, lat + size],
                [lon, lat + size],
                [lon, lat],
            ]
        ],
    }


class TestPolygonValidator:
    def test_valid_square(self) -> None:
        validate_polygon_geojson(_square_polygon(31.2, 30.0))  # no exception

    def test_accepts_a_square_outside_egypt(self) -> None:
        # Tripoli: ~13E, 32N. There is no country check — the metric
        # coordinate system is per farm, so any longitude produces a
        # correct area. See tests/integration/farms/test_farm_utm_zone.py.
        validate_polygon_geojson(_square_polygon(13.0, 32.0))  # no exception

    def test_rejects_non_polygon_type(self) -> None:
        geom = {"type": "Point", "coordinates": [31.0, 30.0]}
        with pytest.raises(GeometryInvalidError):
            validate_polygon_geojson(geom)

    def test_rejects_unclosed_ring(self) -> None:
        # Dropping the closing vertex.
        unclosed = {
            "type": "Polygon",
            "coordinates": [[[31.0, 30.0], [31.001, 30.0], [31.001, 30.001], [31.0, 30.001]]],
        }
        with pytest.raises(GeometryInvalidError):
            validate_polygon_geojson(unclosed)

    def test_rejects_too_few_vertices(self) -> None:
        triangle = {
            "type": "Polygon",
            "coordinates": [[[31.0, 30.0], [31.001, 30.0], [31.0, 30.0]]],
        }
        with pytest.raises(GeometryInvalidError):
            validate_polygon_geojson(triangle)


class TestMultiPolygonValidator:
    def test_valid_multipolygon(self) -> None:
        geom = {
            "type": "MultiPolygon",
            "coordinates": [_square_polygon(31.2, 30.0)["coordinates"]],
        }
        validate_multipolygon_geojson(geom)  # no exception

    def test_rejects_empty(self) -> None:
        with pytest.raises(GeometryInvalidError):
            validate_multipolygon_geojson({"type": "MultiPolygon", "coordinates": []})

    def test_accepts_a_polygon_outside_egypt(self) -> None:
        geom = {
            "type": "MultiPolygon",
            "coordinates": [_square_polygon(13.0, 32.0)["coordinates"]],
        }
        validate_multipolygon_geojson(geom)  # no exception


class TestEwktFormatters:
    def test_polygon_round_trip(self) -> None:
        ewkt = geojson_to_ewkt_polygon(_square_polygon(31.2, 30.0))
        assert ewkt.startswith("SRID=4326;POLYGON((")
        assert "31.2 30.0" in ewkt

    def test_multipolygon_round_trip(self) -> None:
        geom = {
            "type": "MultiPolygon",
            "coordinates": [_square_polygon(31.2, 30.0)["coordinates"]],
        }
        ewkt = geojson_to_ewkt_multipolygon(geom)
        assert ewkt.startswith("SRID=4326;MULTIPOLYGON(((")
