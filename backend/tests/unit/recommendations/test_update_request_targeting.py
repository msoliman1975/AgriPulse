"""The PATCH body for a decision tree accepts an empty crop set.

Empty means "matches any" on every targeting axis. The loader accepts it,
the engine matcher implements it, and 20 of the 41 shipped platform trees
store it. ``DecisionTreeUpdateRequest`` used to require at least one crop
path, so the editor's targeting form could not save a tree that targets
every crop: it PATCHed the row's own stored value back and got a 422.

These assert on the schema, not the service. The service never saw the
rule — it lived in the request model alone, which is why the existing
service-level tests all passed while the screen was broken.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.recommendations.schemas import DecisionTreeUpdateRequest


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name_en": "Potato — frost risk",
        "crop_paths": [],
        "country_codes": [],
        "soil_textures": [],
        "scope": "block",
    }
    base.update(overrides)
    return base


def test_empty_crop_paths_is_accepted() -> None:
    req = DecisionTreeUpdateRequest.model_validate(_body())
    assert req.crop_paths == []


def test_crop_paths_may_be_omitted_entirely() -> None:
    body = _body()
    del body["crop_paths"]
    assert DecisionTreeUpdateRequest.model_validate(body).crop_paths == []


def test_an_any_crop_tree_can_change_country_soil_and_scope() -> None:
    """The exact edit that returned 422: keep crop_paths empty, change the
    other three axes."""
    req = DecisionTreeUpdateRequest.model_validate(
        _body(country_codes=["EG"], soil_textures=["sandy"], scope="cell")
    )
    assert req.crop_paths == []
    assert req.country_codes == ["EG"]
    assert req.soil_textures == ["sandy"]
    assert req.scope == "cell"


def test_name_is_still_required() -> None:
    body = _body()
    del body["name_en"]
    with pytest.raises(ValidationError):
        DecisionTreeUpdateRequest.model_validate(body)
