"""Arabic labels on a signal definition, including the categorical list.

Public migration 0075 added `name_ar`, `description_ar`, `unit_ar` and
`categorical_values_ar`. The last one is a parallel array — same length, same
order, one Arabic label per English code — and the table has a CHECK on the
equal length.

Two things are worth pinning:

* The round-trip. A missing column in the read projection returns a 200 with
  the field absent, which looks like "the save did nothing".
* The length guard. Without the service-layer check, a mismatched pair hits
  the CHECK and surfaces as a 500 with no usable message. It must be a 400.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.signals.test_import_batches import _bootstrap, _build_app

pytestmark = [pytest.mark.integration]

VALUES_EN = ["dry", "moist", "wet"]
VALUES_AR = ["جافة", "رطبة", "مبتلة"]


@pytest.mark.asyncio
async def test_definition_arabic_labels_round_trip(admin_session: AsyncSession) -> None:
    context, _farm_id, _block_id = await _bootstrap(admin_session, "sig-ar-labels")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/signals/definitions",
            json={
                "code": "soil_feel",
                "name": "Soil moisture by feel",
                "name_ar": "رطوبة التربة بالجس",
                "description": "Hand-feel at root depth.",
                "description_ar": "تقدير باللمس على عمق الجذور.",
                "value_kind": "categorical",
                "categorical_values": VALUES_EN,
                "categorical_values_ar": VALUES_AR,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name_ar"] == "رطوبة التربة بالجس"
        assert body["categorical_values"] == VALUES_EN
        assert body["categorical_values_ar"] == VALUES_AR
        definition_id = body["id"]

        resp = await c.get(f"/api/v1/signals/definitions/{definition_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["categorical_values_ar"] == VALUES_AR

        resp = await c.patch(
            f"/api/v1/signals/definitions/{definition_id}",
            json={"name_ar": "رطوبة التربة"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name_ar"] == "رطوبة التربة"
        # An Arabic-only edit leaves the value list alone.
        assert resp.json()["categorical_values_ar"] == VALUES_AR


@pytest.mark.asyncio
async def test_mismatched_arabic_value_list_is_rejected(admin_session: AsyncSession) -> None:
    context, _farm_id, _block_id = await _bootstrap(admin_session, "sig-ar-mismatch")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/signals/definitions",
            json={
                "code": "short_list",
                "name": "Short list",
                "value_kind": "categorical",
                "categorical_values": VALUES_EN,
                "categorical_values_ar": VALUES_AR[:2],
            },
        )
    # 400, not the 500 the raw CHECK would produce.
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_mismatched_arabic_value_list_is_rejected_on_patch(
    admin_session: AsyncSession,
) -> None:
    context, _farm_id, _block_id = await _bootstrap(admin_session, "sig-ar-mismatch-patch")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/signals/definitions",
            json={
                "code": "patch_list",
                "name": "Patch list",
                "value_kind": "categorical",
                "categorical_values": VALUES_EN,
            },
        )
        assert resp.status_code == 201, resp.text
        definition_id = resp.json()["id"]

        # The stored list has three entries; this patch sends two Arabic ones
        # and no new English list, so it must be compared against what the row
        # already holds.
        resp = await c.patch(
            f"/api/v1/signals/definitions/{definition_id}",
            json={"categorical_values_ar": VALUES_AR[:2]},
        )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_platform_scouting_catalog_has_arabic(admin_session: AsyncSession) -> None:
    """Migration 0075 pass 2 translated the nine platform definitions.

    The scouting form is the whole reason `categorical_values_ar` exists: a
    scout picking a value in the Arabic app was reading `emitter_blocked`.
    """
    context, _farm_id, _block_id = await _bootstrap(admin_session, "sig-ar-platform")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/signals/definitions")
        assert resp.status_code == 200, resp.text
        by_code = {d["code"]: d for d in resp.json()}

    fault = by_code["irrigation_fault"]
    assert fault["name_ar"] == "عطل في الري"
    assert fault["categorical_values_ar"] is not None
    assert len(fault["categorical_values_ar"]) == len(fault["categorical_values"])
    blocked = fault["categorical_values"].index("emitter_blocked")
    assert fault["categorical_values_ar"][blocked] == "نقاط تنقيط مسدودة"

    # A definition with no value list still gets a name.
    assert by_code["pest_incidence_pct"]["name_ar"] == "نسبة الإصابة بالآفات"
