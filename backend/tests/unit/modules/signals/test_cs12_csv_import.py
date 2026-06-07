"""CS-12 unit tests — CSV parser extensions + templated-row grouping.

Pure functions (no DB): the location/attachment/template columns and the
group_rows splitter. Service-level template resolution + insertion is
covered separately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.signals.csv_import import group_rows, parse_csv
from app.modules.signals.service import SignalsServiceImpl

_HEADER = (
    "signal_code,observed_at,block_id,value_numeric,value_categorical,"
    "value_event,value_boolean,notes,location_mode,location_point_lat,"
    "location_point_lon,attachment_s3_key,template_code,template_member_position"
)


def _csv(*rows: str) -> str:
    return _HEADER + "\n" + "\n".join(rows) + "\n"


def _row(**cols: str) -> str:
    order = _HEADER.split(",")
    return ",".join(cols.get(c, "") for c in order)


def test_parses_free_point_location() -> None:
    res = parse_csv(
        _csv(
            _row(
                signal_code="soilmoisture",
                observed_at="2026-06-01T10:00:00+00:00",
                value_numeric="60",
                location_mode="free_point",
                location_point_lat="30.04",
                location_point_lon="31.23",
            )
        )
    )
    assert res.errors == []
    assert len(res.rows) == 1
    r = res.rows[0]
    assert r.location_mode == "free_point"
    assert r.location_point_lat == 30.04
    assert r.location_point_lon == 31.23


def test_invalid_location_mode_errors() -> None:
    res = parse_csv(
        _csv(_row(signal_code="x", observed_at="2026-06-01T10:00:00+00:00", value_numeric="1", location_mode="bogus"))
    )
    assert any(e.field == "location_mode" for e in res.errors)


def test_latitude_out_of_range_errors() -> None:
    res = parse_csv(
        _csv(
            _row(
                signal_code="x",
                observed_at="2026-06-01T10:00:00+00:00",
                value_numeric="1",
                location_mode="free_point",
                location_point_lat="200",
                location_point_lon="31",
            )
        )
    )
    assert any(e.field == "location_point_lat" for e in res.errors)


def test_lat_without_lon_errors() -> None:
    res = parse_csv(
        _csv(
            _row(
                signal_code="x",
                observed_at="2026-06-01T10:00:00+00:00",
                value_numeric="1",
                location_mode="free_point",
                location_point_lat="30",
            )
        )
    )
    assert any("both location_point" in e.message for e in res.errors)


def test_point_in_entity_requires_coords() -> None:
    res = parse_csv(
        _csv(_row(signal_code="x", observed_at="2026-06-01T10:00:00+00:00", value_numeric="1", location_mode="point_in_entity"))
    )
    assert any(e.field == "location_mode" for e in res.errors)


def test_template_code_requires_position() -> None:
    res = parse_csv(
        _csv(_row(signal_code="x", observed_at="2026-06-01T10:00:00+00:00", value_numeric="1", template_code="soiltest"))
    )
    assert any(e.field == "template_member_position" for e in res.errors)


def test_position_requires_template_code() -> None:
    res = parse_csv(
        _csv(_row(signal_code="x", observed_at="2026-06-01T10:00:00+00:00", value_numeric="1", template_member_position="0"))
    )
    assert any(e.field == "template_code" for e in res.errors)


def test_max_rows_param_enforced() -> None:
    body = _csv(
        _row(signal_code="a", observed_at="2026-06-01T10:00:00+00:00", value_numeric="1"),
        _row(signal_code="b", observed_at="2026-06-01T10:00:00+00:00", value_numeric="2"),
    )
    res = parse_csv(body, max_rows=1)
    assert any("row limit" in e.message for e in res.errors)


def test_group_rows_splits_flat_and_templated() -> None:
    res = parse_csv(
        _csv(
            _row(signal_code="standalone", observed_at="2026-06-01T10:00:00+00:00", value_numeric="9"),
            _row(
                signal_code="ph",
                observed_at="2026-06-02T08:00:00+00:00",
                value_numeric="6.5",
                template_code="soiltest",
                template_member_position="0",
            ),
            _row(
                signal_code="moisture",
                observed_at="2026-06-02T08:00:00+00:00",
                value_numeric="40",
                template_code="soiltest",
                template_member_position="1",
            ),
        )
    )
    assert res.errors == []
    flat, groups, errors = group_rows(res.rows)
    assert errors == []
    assert len(flat) == 1
    assert flat[0].signal_code == "standalone"
    assert len(groups) == 1
    assert len(groups[0].rows) == 2
    assert groups[0].template_code == "soiltest"


def test_group_rows_flags_duplicate_member_position() -> None:
    res = parse_csv(
        _csv(
            _row(signal_code="a", observed_at="2026-06-02T08:00:00+00:00", value_numeric="1", template_code="t", template_member_position="0"),
            _row(signal_code="b", observed_at="2026-06-02T08:00:00+00:00", value_numeric="2", template_code="t", template_member_position="0"),
        )
    )
    _flat, _groups, errors = group_rows(res.rows)
    assert any("Duplicate member position" in e.message for e in errors)


def test_group_rows_distinct_observed_at_are_separate_groups() -> None:
    res = parse_csv(
        _csv(
            _row(signal_code="a", observed_at="2026-06-02T08:00:00+00:00", value_numeric="1", template_code="t", template_member_position="0"),
            _row(signal_code="a", observed_at="2026-06-03T08:00:00+00:00", value_numeric="2", template_code="t", template_member_position="0"),
        )
    )
    _flat, groups, _errors = group_rows(res.rows)
    assert len(groups) == 2


# ---- Service-level: templated-CSV dispatch ---------------------------------

_PH_ID = uuid4()
_MOIST_ID = uuid4()
_TPL_ID = uuid4()


def _numeric_def(def_id):
    return {
        "id": def_id,
        "value_kind": "numeric",
        "value_min": None,
        "value_max": None,
        "categorical_values": None,
        "attachment_allowed": False,
    }


def _impl_with_repo() -> SignalsServiceImpl:
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    repo = AsyncMock()

    async def _get_def(*, code):
        return {"ph": _numeric_def(_PH_ID), "moisture": _numeric_def(_MOIST_ID)}.get(code)

    repo.get_definition = AsyncMock(side_effect=_get_def)
    repo.list_templates = AsyncMock(return_value=({"id": _TPL_ID, "code": "soiltest"},))
    repo.get_template_members = AsyncMock(
        return_value=(
            {"signal_definition_id": _PH_ID},
            {"signal_definition_id": _MOIST_ID},
        )
    )
    repo.insert_observation = AsyncMock()
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = MagicMock()
    impl._log = None  # type: ignore[attr-defined]
    # Isolate the import dispatch from CS-4's create_template_observation
    # (tested separately) — assert the group is routed to it.
    impl.create_template_observation = AsyncMock(  # type: ignore[method-assign]
        return_value={"observation_count": 2}
    )
    return impl


@pytest.mark.asyncio
async def test_templated_csv_routes_group_to_template_observation() -> None:
    impl = _impl_with_repo()
    body = _csv(
        _row(signal_code="ph", observed_at="2026-06-02T08:00:00+00:00", value_numeric="6.5",
             template_code="soiltest", template_member_position="0"),
        _row(signal_code="moisture", observed_at="2026-06-02T08:00:00+00:00", value_numeric="40",
             template_code="soiltest", template_member_position="1"),
    )
    out = await impl.import_observations_csv(
        farm_id=uuid4(),
        csv_bytes=body.encode("utf-8"),
        recorded_by=uuid4(),
        tenant_schema="t",
        tenant_id=uuid4(),
    )
    assert out == {"rows_imported": 2}
    # The 2 rows went in as ONE template observation, not 2 flat inserts.
    impl.create_template_observation.assert_awaited_once()
    assert impl._repo.insert_observation.await_count == 0
    members = impl.create_template_observation.await_args.kwargs["members"]
    assert len(members) == 2


@pytest.mark.asyncio
async def test_templated_csv_rejects_non_member_signal() -> None:
    from app.modules.signals.errors import CsvImportFailedError

    impl = _impl_with_repo()
    # 'moisture' resolves but is dropped from the template's member set.
    impl._repo.get_template_members = AsyncMock(
        return_value=({"signal_definition_id": _PH_ID},)
    )
    body = _csv(
        _row(signal_code="ph", observed_at="2026-06-02T08:00:00+00:00", value_numeric="6.5",
             template_code="soiltest", template_member_position="0"),
        _row(signal_code="moisture", observed_at="2026-06-02T08:00:00+00:00", value_numeric="40",
             template_code="soiltest", template_member_position="1"),
    )
    with pytest.raises(CsvImportFailedError) as exc:
        await impl.import_observations_csv(
            farm_id=uuid4(),
            csv_bytes=body.encode("utf-8"),
            recorded_by=uuid4(),
            tenant_schema="t",
            tenant_id=uuid4(),
        )
    assert any("not a member" in e["message"] for e in exc.value.extras["errors"])
    impl.create_template_observation.assert_not_awaited()
