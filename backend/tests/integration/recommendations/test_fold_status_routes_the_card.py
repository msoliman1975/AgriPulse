"""A folded card's status decides the verdict colour and the work item.

    alert                -> an alert, and an `alert` verdict
    issue                -> a recommendation, and an `issue` verdict
    good / very_good     -> no work item, and a verdict in that status

Before this change every folded card was saved as a recommendation with an
`issue` verdict, whatever the fold decided, so Farm Health and block health
painted a red finding amber and a good one amber too.

The finding codes here are this file's own. The platform catalogue wins over
a tree's `findings:` block on a shared code (`dry`, `ndvi_low` are seeded as
`issue`), so a test that needs a status must use a code nobody else holds.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.recommendations.test_folding_execution import (
    _evaluate,
    _install_tree,
    _seed_farm_and_block,
    _tenant_for,
    _write_index,
)

pytestmark = [pytest.mark.integration]


def _finding(code: str, status: str, clause: str, action: str) -> dict[str, Any]:
    return {
        "clause_en": clause,
        "clause_ar": clause,
        "name_en": code,
        "name_ar": None,
        "default_status": status,
        "action_type": action,
    }


def _check(index: str, op: str, value: float, on_match: str, on_miss: str) -> dict[str, Any]:
    return {
        "label_en": f"{index} {op} {value}",
        "condition": {
            "tree": {
                "op": op,
                "left": {"source": "indices", "index_code": index, "key": "mean"},
                "right": value,
            }
        },
        "on_match": on_match,
        "on_miss": on_miss,
    }


def _tree(code: str) -> dict[str, Any]:
    """Three checks, one finding each: an alarm, a note, and a clean bill.

    NDMI below 0.30 registers `fs_alarm` (alert). NDVI below 0.40 registers
    `fs_note` (issue). NDRE above 0.50 registers `fs_fine` (good).
    """
    return {
        "code": code,
        "name_en": "Fold status demo",
        "name_ar": None,
        "root": "c_water",
        "registers": ["fs_alarm", "fs_note", "fs_fine"],
        "findings": {
            "fs_alarm": _finding("fs_alarm", "alert", "leaf water is very low", "irrigate"),
            "fs_note": _finding("fs_note", "issue", "canopy vigour dipped", "scout"),
            "fs_fine": _finding("fs_fine", "good", "nitrogen is in band", "scout"),
        },
        "nodes": {
            "c_water": _check("ndmi", "lt", 0.30, "r_alarm", "c_vigour"),
            "r_alarm": {
                "register": {"code": "fs_alarm", "severity": "critical"},
                "next": "c_vigour",
            },
            "c_vigour": _check("ndvi", "lt", 0.40, "r_note", "c_nitrogen"),
            "r_note": {
                "register": {"code": "fs_note", "severity": "warning"},
                "next": "c_nitrogen",
            },
            "c_nitrogen": _check("ndre", "gt", 0.50, "r_fine", "stop"),
            "r_fine": {"register": {"code": "fs_fine", "severity": "info"}, "next": "stop"},
            "stop": {"stop": True, "label_en": "Fold"},
        },
    }


async def _readings(
    session: AsyncSession, schema: str, block_id: UUID, *, ndmi: str, ndvi: str, ndre: str
) -> None:
    for index, mean in (("ndmi", ndmi), ("ndvi", ndvi), ("ndre", ndre)):
        await _write_index(session, schema, block_id=block_id, index_code=index, mean=Decimal(mean))


async def _rows(
    session: AsyncSession, schema: str, sql: str, **params: Any
) -> list[dict[str, Any]]:
    # Re-applied on every read: a commit drops the search_path with no error.
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    stmt = text(sql)
    for name, value in params.items():
        if isinstance(value, UUID):
            stmt = stmt.bindparams(bindparam(name, type_=PG_UUID(as_uuid=True)))
    return [dict(r) for r in (await session.execute(stmt, params)).mappings().all()]


async def _setup(admin_session: AsyncSession, slug: str) -> tuple[Any, str, UUID, UUID]:
    tenant = await _tenant_for(admin_session, slug)
    code = f"fold_status_{uuid4().hex[:6]}"
    tree_id = await _install_tree(admin_session, compiled=_tree(code))
    _farm, block_id = await _seed_farm_and_block(
        admin_session, tenant.schema_name, suffix=uuid4().hex[:4]
    )
    return tenant, code, tree_id, block_id


async def _current_verdict(
    session: AsyncSession, schema: str, block_id: UUID, tree_id: UUID
) -> dict[str, Any]:
    rows = await _rows(
        session,
        schema,
        "SELECT kind, status_code, text_en, alert_id, recommendation_id "
        "FROM decision_tree_block_verdicts "
        "WHERE block_id = :b AND tree_id = :t AND cell_id IS NULL AND valid_to IS NULL",
        b=block_id,
        t=tree_id,
    )
    assert len(rows) == 1, rows
    return rows[0]


@pytest.mark.asyncio
async def test_an_alert_card_opens_an_alert(admin_session: AsyncSession) -> None:
    tenant, code, tree_id, block_id = await _setup(admin_session, "fold-alert")
    schema = tenant.schema_name
    await _readings(admin_session, schema, block_id, ndmi="0.10", ndvi="0.70", ndre="0.30")
    await _evaluate(schema, tenant.tenant_id, block_id, only_tree_code=code)

    alerts = await _rows(
        admin_session,
        schema,
        "SELECT rule_code, status, severity FROM alerts WHERE block_id = :b",
        b=block_id,
    )
    assert alerts == [
        {"rule_code": f"tree:{code}:findings=fs_alarm", "status": "open", "severity": "critical"}
    ]
    recs = await _rows(
        admin_session, schema, "SELECT id FROM recommendations WHERE tree_id = :t", t=tree_id
    )
    assert recs == []

    verdict = await _current_verdict(admin_session, schema, block_id, tree_id)
    assert verdict["kind"] == "alert"
    assert verdict["status_code"] == "alert"
    assert verdict["alert_id"] is not None


@pytest.mark.asyncio
async def test_an_issue_card_opens_a_recommendation(admin_session: AsyncSession) -> None:
    tenant, code, tree_id, block_id = await _setup(admin_session, "fold-issue")
    schema = tenant.schema_name
    await _readings(admin_session, schema, block_id, ndmi="0.60", ndvi="0.20", ndre="0.30")
    await _evaluate(schema, tenant.tenant_id, block_id, only_tree_code=code)

    recs = await _rows(
        admin_session,
        schema,
        "SELECT state, finding_set FROM recommendations WHERE tree_id = :t",
        t=tree_id,
    )
    assert recs == [{"state": "open", "finding_set": ["fs_note"]}]
    alerts = await _rows(
        admin_session,
        schema,
        "SELECT id FROM alerts WHERE block_id = :b AND rule_code LIKE :p",
        b=block_id,
        p=f"tree:{code}:%",
    )
    assert alerts == []

    verdict = await _current_verdict(admin_session, schema, block_id, tree_id)
    assert verdict["kind"] == "recommendation"
    assert verdict["status_code"] == "issue"


@pytest.mark.asyncio
async def test_a_good_card_opens_nothing_and_says_why(admin_session: AsyncSession) -> None:
    tenant, code, tree_id, block_id = await _setup(admin_session, "fold-good")
    schema = tenant.schema_name
    await _readings(admin_session, schema, block_id, ndmi="0.60", ndvi="0.70", ndre="0.70")
    await _evaluate(schema, tenant.tenant_id, block_id, only_tree_code=code)

    recs = await _rows(
        admin_session, schema, "SELECT id FROM recommendations WHERE tree_id = :t", t=tree_id
    )
    assert recs == []
    alerts = await _rows(
        admin_session,
        schema,
        "SELECT id FROM alerts WHERE block_id = :b AND rule_code LIKE :p",
        b=block_id,
        p=f"tree:{code}:%",
    )
    assert alerts == []

    verdict = await _current_verdict(admin_session, schema, block_id, tree_id)
    assert verdict["kind"] == "status"
    assert verdict["status_code"] == "good"
    # The finding's own words, not the generic "checked; nothing found".
    assert "nitrogen is in band" in (verdict["text_en"] or "").lower()


@pytest.mark.asyncio
async def test_a_changed_finding_set_opens_a_new_alert(admin_session: AsyncSession) -> None:
    """The finding set is in the rule_code, so new findings mean a new alert.

    The old alert stays open. Closing it is lifecycle work that was left out
    on purpose (2026-09-24): open items are removed by hand for now.
    """
    tenant, code, _tree_id, block_id = await _setup(admin_session, "fold-alert-set")
    schema = tenant.schema_name
    await _readings(admin_session, schema, block_id, ndmi="0.10", ndvi="0.70", ndre="0.30")
    await _evaluate(schema, tenant.tenant_id, block_id, only_tree_code=code)
    await _readings(admin_session, schema, block_id, ndmi="0.10", ndvi="0.20", ndre="0.30")
    await _evaluate(schema, tenant.tenant_id, block_id, only_tree_code=code)

    alerts = await _rows(
        admin_session,
        schema,
        "SELECT rule_code FROM alerts WHERE block_id = :b AND status = 'open' ORDER BY rule_code",
        b=block_id,
    )
    codes = [a["rule_code"] for a in alerts]
    assert f"tree:{code}:findings=fs_alarm" in codes
    assert len(codes) == 2, codes
    assert all(c.startswith(f"tree:{code}:findings=") for c in codes)
