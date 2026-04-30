"""Unit tests for the farm_scopes cross-schema consistency check.

We mock both the public-schema scope query and the per-tenant farm
existence query. The check is pure plumbing on top of those two queries
plus an audit emitter, so the assertions focus on:

  * happy path: every scope has a matching farm → zero audit calls
  * single orphan in one tenant → exactly one audit call with the right
    subject + details
  * orphans across multiple tenants → one audit call per orphan
  * malformed schema name → scope is skipped (and counted) without
    raising
  * empty scope list → no DB calls beyond the initial scan
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.modules.farms import consistency_check as cc


def _scope(
    *,
    farm_id: UUID,
    schema: str = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    tenant_id: UUID | None = None,
    membership_id: UUID | None = None,
    role: str = "FarmManager",
) -> dict[str, Any]:
    return {
        "farm_scope_id": uuid4(),
        "farm_id": farm_id,
        "membership_id": membership_id or uuid4(),
        "role": role,
        "tenant_id": tenant_id or uuid4(),
        "schema_name": schema,
    }


@pytest.fixture
def audit_mock() -> MagicMock:
    audit = MagicMock()
    audit.record = AsyncMock(return_value=uuid4())
    return audit


def _patch_db(scopes: list[dict[str, Any]], existing_per_schema: dict[str, set[UUID]]):
    """Patch the two DB-touching helpers with deterministic fakes."""
    load = AsyncMock(return_value=scopes)

    async def _existing(_session: Any, *, schema: str, farm_ids: list[UUID]) -> set[UUID]:
        return existing_per_schema.get(schema, set()) & set(farm_ids)

    return (
        patch.object(cc, "_load_active_scopes", load),
        patch.object(cc, "_existing_farms_in_schema", AsyncMock(side_effect=_existing)),
        patch.object(cc, "AsyncSessionLocal", _fake_session_local()),
    )


def _fake_session_local():
    """Sessionmaker stub that yields a context-managing AsyncMock."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    factory_cm = MagicMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=factory_cm)
    sessionmaker_call = MagicMock(return_value=factory)
    return sessionmaker_call


@pytest.mark.asyncio
async def test_no_scopes_yields_zero_summary(audit_mock: MagicMock) -> None:
    p1, p2, p3 = _patch_db(scopes=[], existing_per_schema={})
    with p1, p2, p3:
        summary = await cc.run_farm_scope_consistency_check(audit_service=audit_mock)
    assert summary == {"scopes_checked": 0, "orphans_detected": 0, "schemas_skipped": 0}
    audit_mock.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_scopes_match_no_orphans(audit_mock: MagicMock) -> None:
    farm = uuid4()
    schema = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    scopes = [_scope(farm_id=farm, schema=schema)]
    p1, p2, p3 = _patch_db(scopes=scopes, existing_per_schema={schema: {farm}})
    with p1, p2, p3:
        summary = await cc.run_farm_scope_consistency_check(audit_service=audit_mock)
    assert summary == {"scopes_checked": 1, "orphans_detected": 0, "schemas_skipped": 0}
    audit_mock.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_orphan_emits_one_audit_row(audit_mock: MagicMock) -> None:
    orphan_farm = uuid4()
    schema = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    scope = _scope(farm_id=orphan_farm, schema=schema)
    p1, p2, p3 = _patch_db(scopes=[scope], existing_per_schema={schema: set()})
    with p1, p2, p3:
        summary = await cc.run_farm_scope_consistency_check(audit_service=audit_mock)

    assert summary == {"scopes_checked": 1, "orphans_detected": 1, "schemas_skipped": 0}
    audit_mock.record.assert_awaited_once()
    kwargs = audit_mock.record.await_args.kwargs
    assert kwargs["event_type"] == "farms.farm_scope_orphan_detected"
    assert kwargs["actor_kind"] == "system"
    assert kwargs["actor_user_id"] is None
    assert kwargs["subject_kind"] == "farm_scope_orphan"
    assert kwargs["subject_id"] == scope["farm_scope_id"]
    assert kwargs["farm_id"] == orphan_farm
    assert kwargs["details"]["role"] == "FarmManager"
    assert kwargs["details"]["schema_name"] == schema


@pytest.mark.asyncio
async def test_mixed_orphans_and_valid_across_two_tenants(audit_mock: MagicMock) -> None:
    schema_a = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    schema_b = "tenant_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    valid_a = uuid4()
    orphan_a = uuid4()
    orphan_b = uuid4()
    scopes = [
        _scope(farm_id=valid_a, schema=schema_a),
        _scope(farm_id=orphan_a, schema=schema_a),
        _scope(farm_id=orphan_b, schema=schema_b),
    ]
    p1, p2, p3 = _patch_db(
        scopes=scopes,
        existing_per_schema={schema_a: {valid_a}, schema_b: set()},
    )
    with p1, p2, p3:
        summary = await cc.run_farm_scope_consistency_check(audit_service=audit_mock)

    assert summary == {"scopes_checked": 3, "orphans_detected": 2, "schemas_skipped": 0}
    assert audit_mock.record.await_count == 2
    audited_farm_ids = {call.kwargs["farm_id"] for call in audit_mock.record.await_args_list}
    assert audited_farm_ids == {orphan_a, orphan_b}


@pytest.mark.asyncio
async def test_malformed_schema_is_skipped_not_raised(audit_mock: MagicMock) -> None:
    bad_scope = _scope(farm_id=uuid4(), schema="not-a-tenant-schema")
    good_schema = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    good_farm = uuid4()
    good_scope = _scope(farm_id=good_farm, schema=good_schema)
    p1, p2, p3 = _patch_db(
        scopes=[bad_scope, good_scope],
        existing_per_schema={good_schema: {good_farm}},
    )
    with p1, p2, p3:
        summary = await cc.run_farm_scope_consistency_check(audit_service=audit_mock)

    assert summary == {"scopes_checked": 2, "orphans_detected": 0, "schemas_skipped": 1}
    audit_mock.record.assert_not_awaited()
