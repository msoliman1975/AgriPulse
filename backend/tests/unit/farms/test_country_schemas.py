"""Unit tests for country-code validation on the country catalog + farm schemas.

DB-less: exercises only the Pydantic validators added for Decision-Tree
country targeting (PR-1).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.farms.schemas import (
    CountryCreateRequest,
    FarmCreateRequest,
    FarmUpdateRequest,
)

_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]],
}


def test_country_create_uppercases_code() -> None:
    req = CountryCreateRequest(code="eg", name_en="Egypt", name_ar="مصر")
    assert req.code == "EG"


@pytest.mark.parametrize("bad", ["E", "EGY", "E1", "1G", "e-g", ""])
def test_country_create_rejects_non_alpha2(bad: str) -> None:
    with pytest.raises(ValidationError):
        CountryCreateRequest(code=bad, name_en="X", name_ar="X")


def test_farm_create_normalises_country_code() -> None:
    farm = FarmCreateRequest(code="f1", name="Farm 1", boundary=_BOUNDARY, country_code="jo")
    assert farm.country_code == "JO"


def test_farm_create_allows_no_country() -> None:
    farm = FarmCreateRequest(code="f1", name="Farm 1", boundary=_BOUNDARY)
    assert farm.country_code is None


def test_farm_create_rejects_bad_country_code() -> None:
    with pytest.raises(ValidationError):
        FarmCreateRequest(code="f1", name="Farm 1", boundary=_BOUNDARY, country_code="EGY")


def test_farm_update_normalises_country_code() -> None:
    upd = FarmUpdateRequest(country_code="ma")
    assert upd.country_code == "MA"
    # Omitted -> unset (not serialised), so a partial update never clears it.
    assert "country_code" not in FarmUpdateRequest(name="x").model_dump(exclude_unset=True)
