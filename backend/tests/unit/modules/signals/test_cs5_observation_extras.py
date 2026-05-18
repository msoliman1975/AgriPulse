"""CS-5 unit tests — location_mode + template-filter on the
single-shot observation surface.

Covers:
- create_observation now validates location_mode/location_point
  presence rule (was previously only checked on the template
  submission endpoint).
- _enrich_observation unwraps location_point the same way it
  unwraps value_geopoint.
- list_observations forwards the template_observation_id filter to
  the repository.

Repo mocked — the real SQL filter is a one-line addition exercised by
the integration suite.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.signals.errors import InvalidSignalValueError
from app.modules.signals.schemas import GeopointModel
from app.modules.signals.service import (
    SignalsServiceImpl,
    _enrich_observation,
    _geojson_point_to_geopoint,
)


def _impl_with_mocked_repo(repo: AsyncMock) -> SignalsServiceImpl:
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = MagicMock()
    impl._tenant = None  # type: ignore[attr-defined]
    impl._log = None  # type: ignore[attr-defined]
    return impl


def _numeric_defn() -> dict:
    return {
        "id": uuid4(),
        "code": "ndvi",
        "value_kind": "numeric",
        "value_min": Decimal("0"),
        "value_max": Decimal("1"),
        "categorical_values": None,
        "attachment_allowed": False,
    }


class TestGeoJsonPointHelper:
    def test_point_unwrapped(self) -> None:
        out = _geojson_point_to_geopoint({"type": "Point", "coordinates": [31.0, 30.5]})
        assert out == {"longitude": 31.0, "latitude": 30.5}

    def test_none_passes_through(self) -> None:
        assert _geojson_point_to_geopoint(None) is None

    def test_non_point_geometry_is_none(self) -> None:
        assert _geojson_point_to_geopoint({"type": "LineString", "coordinates": []}) is None

    def test_malformed_coords_are_none(self) -> None:
        assert _geojson_point_to_geopoint({"type": "Point", "coordinates": [1.0]}) is None


class TestEnrichObservationLocationPoint:
    def test_location_point_unwrapped(self) -> None:
        storage = MagicMock()
        storage.presign_download = MagicMock()
        out = _enrich_observation(
            {
                "value_geopoint_geojson": None,
                "location_point_geojson": {"type": "Point", "coordinates": [10.0, 20.0]},
                "attachment_s3_key": None,
            },
            storage=storage,
        )
        assert out["location_point"] == {"longitude": 10.0, "latitude": 20.0}
        # value_geopoint stays None when not set; the unwrap is independent.
        assert out["value_geopoint"] is None
        # Both raw GeoJSON keys removed.
        assert "location_point_geojson" not in out
        assert "value_geopoint_geojson" not in out


@pytest.mark.asyncio
class TestCreateObservationLocationValidation:
    async def test_entity_mode_with_location_point_rejected(self) -> None:
        defn = _numeric_defn()
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=defn)
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(InvalidSignalValueError, match="must not include"):
            await impl.create_observation(
                definition_id=defn["id"],
                time=None,
                farm_id=uuid4(),
                block_id=None,
                value_numeric=Decimal("0.5"),
                value_categorical=None,
                value_event=None,
                value_boolean=None,
                value_geopoint=None,
                attachment_s3_key=None,
                notes=None,
                location_mode="entity",
                location_point=GeopointModel(latitude=20, longitude=30),
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )
        repo.insert_observation.assert_not_called()

    async def test_point_in_entity_requires_point(self) -> None:
        defn = _numeric_defn()
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=defn)
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(InvalidSignalValueError, match="requires a location_point"):
            await impl.create_observation(
                definition_id=defn["id"],
                time=None,
                farm_id=uuid4(),
                block_id=None,
                value_numeric=Decimal("0.5"),
                value_categorical=None,
                value_event=None,
                value_boolean=None,
                value_geopoint=None,
                attachment_s3_key=None,
                notes=None,
                location_mode="point_in_entity",
                location_point=None,
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )
        repo.insert_observation.assert_not_called()

    async def test_default_entity_mode_passes_through_to_repo(self) -> None:
        defn = _numeric_defn()
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=defn)
        repo.insert_observation = AsyncMock()
        repo.list_observations = AsyncMock(return_value=())
        impl = _impl_with_mocked_repo(repo)
        await impl.create_observation(
            definition_id=defn["id"],
            time=None,
            farm_id=uuid4(),
            block_id=None,
            value_numeric=Decimal("0.5"),
            value_categorical=None,
            value_event=None,
            value_boolean=None,
            value_geopoint=None,
            attachment_s3_key=None,
            notes=None,
            recorded_by=uuid4(),
            tenant_schema="t_x",
        )
        kwargs = repo.insert_observation.await_args.kwargs
        assert kwargs["location_mode"] == "entity"
        assert kwargs["location_point_wkt"] is None

    async def test_free_point_renders_wkt(self) -> None:
        defn = _numeric_defn()
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=defn)
        repo.insert_observation = AsyncMock()
        repo.list_observations = AsyncMock(return_value=())
        impl = _impl_with_mocked_repo(repo)
        await impl.create_observation(
            definition_id=defn["id"],
            time=None,
            farm_id=uuid4(),
            block_id=None,
            value_numeric=Decimal("0.5"),
            value_categorical=None,
            value_event=None,
            value_boolean=None,
            value_geopoint=None,
            attachment_s3_key=None,
            notes=None,
            location_mode="free_point",
            location_point=GeopointModel(latitude=30.5, longitude=31.0),
            recorded_by=uuid4(),
            tenant_schema="t_x",
        )
        kwargs = repo.insert_observation.await_args.kwargs
        assert kwargs["location_mode"] == "free_point"
        assert kwargs["location_point_wkt"] == "POINT(31.0 30.5)"


@pytest.mark.asyncio
class TestListObservationsTemplateFilter:
    async def test_forwards_template_observation_id(self) -> None:
        repo = AsyncMock()
        repo.list_observations = AsyncMock(return_value=())
        impl = _impl_with_mocked_repo(repo)
        target = uuid4()
        await impl.list_observations(template_observation_id=target)
        kwargs = repo.list_observations.await_args.kwargs
        assert kwargs["template_observation_id"] == target

    async def test_filter_unset_passes_none(self) -> None:
        repo = AsyncMock()
        repo.list_observations = AsyncMock(return_value=())
        impl = _impl_with_mocked_repo(repo)
        await impl.list_observations(farm_id=uuid4())
        kwargs = repo.list_observations.await_args.kwargs
        assert kwargs["template_observation_id"] is None
