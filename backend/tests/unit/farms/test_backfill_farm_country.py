"""Backfilling a country on farms that have none (platform admin, audited).

Decision trees target farms by country, and farms created after the country
column landed were left without one, so country-restricted trees skipped
them. The platform backfill sets a code on every such farm in one tenant,
through the same update path (and audit row) as an edit in the UI.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.farms.errors import UnknownCountryCodeError
from app.modules.farms.service import FarmServiceImpl

FARMS = [
    {"id": uuid4(), "code": "F-01", "name": "North"},
    {"id": uuid4(), "code": "F-02", "name": "South"},
]


class _Repo:
    def __init__(self, farms: list[dict[str, Any]], known: set[str]) -> None:
        self.farms = farms
        self.known = known

    async def list_farms_without_country(self) -> list[dict[str, Any]]:
        return [dict(f) for f in self.farms]

    async def country_code_exists(self, *, code: str, active_only: bool = False) -> bool:
        return code in self.known


class _Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)


def _service(farms: list[dict[str, Any]] = FARMS) -> tuple[FarmServiceImpl, list[dict], _Audit]:
    service = FarmServiceImpl.__new__(FarmServiceImpl)
    service._repo = _Repo(farms, {"EG", "SA"})  # type: ignore[assignment]
    audit = _Audit()
    service._audit = audit  # type: ignore[assignment]
    updates: list[dict[str, Any]] = []

    async def update_farm(**kwargs: Any) -> dict[str, Any]:
        updates.append(kwargs)
        return {}

    service.update_farm = update_farm  # type: ignore[method-assign]
    return service, updates, audit


async def test_a_dry_run_lists_the_farms_and_writes_nothing() -> None:
    service, updates, audit = _service()
    result = await service.backfill_farm_country(
        country_code="eg", dry_run=True, actor_user_id=uuid4(), tenant_schema="tenant_x"
    )
    assert result["country_code"] == "EG"
    assert result["dry_run"] is True
    assert result["count"] == 2
    assert [f["code"] for f in result["farms"]] == ["F-01", "F-02"]
    assert updates == []
    assert audit.rows == []


async def test_a_real_run_updates_each_farm_and_audits_the_run() -> None:
    service, updates, audit = _service()
    actor = uuid4()
    result = await service.backfill_farm_country(
        country_code="EG", dry_run=False, actor_user_id=actor, tenant_schema="tenant_x"
    )
    assert result["count"] == 2
    assert result["dry_run"] is False
    # Each farm goes through update_farm: the UI's audit row and event.
    assert [u["farm_id"] for u in updates] == [f["id"] for f in FARMS]
    assert all(u["changes"] == {"country_code": "EG"} for u in updates)
    assert all(u["actor_user_id"] == actor and u["tenant_schema"] == "tenant_x" for u in updates)
    # Plus one row for the run itself.
    assert len(audit.rows) == 1
    row = audit.rows[0]
    assert row["event_type"] == "farms.country_backfilled"
    assert row["actor_user_id"] == actor
    assert row["details"]["count"] == 2
    assert row["details"]["farm_ids"] == [str(f["id"]) for f in FARMS]


async def test_an_unknown_code_is_refused_before_anything_is_read() -> None:
    service, updates, audit = _service()
    with pytest.raises(UnknownCountryCodeError):
        await service.backfill_farm_country(
            country_code="ZZ", dry_run=False, actor_user_id=None, tenant_schema="tenant_x"
        )
    assert updates == []
    assert audit.rows == []


async def test_a_tenant_with_nothing_to_set_writes_no_audit_row() -> None:
    service, updates, audit = _service(farms=[])
    result = await service.backfill_farm_country(
        country_code="EG", dry_run=False, actor_user_id=None, tenant_schema="tenant_x"
    )
    assert result["count"] == 0
    assert updates == []
    assert audit.rows == []
