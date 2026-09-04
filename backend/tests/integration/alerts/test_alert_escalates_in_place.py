"""An alert that re-fires at a higher severity must say so.

The dedup index `uq_alerts_block_rule_open` is `(block_id, rule_code)`, and
`rule_code` is `tree:<tree_code>:<leaf_node_id>`. Neither carries severity.
So when a tree author republishes a leaf at a higher severity, the next
sweep's INSERT is refused, the row is bumped, and — before this fix — it kept
the OLD severity until somebody resolved it by hand.

Block health reads severity. A block that should have escalated to Critical
stayed on Watch, silently, for as long as the alert stayed open. Nothing
failed and nothing logged.

This is the one thing about the fix that cannot be checked anywhere but here:
the behaviour is a consequence of a partial UNIQUE index, and a mocked
session would simply do whatever the mock was told to.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.alerts.repository import AlertsRepository
from app.modules.tenancy.service import get_tenant_service
from app.shared.action_items import build_group_key

pytestmark = [pytest.mark.integration]

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"


async def _seed(admin_session: Any) -> dict[str, Any]:
    slug = f"esc-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    schema = f"tenant_{tenant.tenant_id.hex}"
    farm_id, block_id = uuid4(), uuid4()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'F1', 'Farm', ST_GeomFromText(:poly, 4326))"
        ),
        {"id": farm_id, "poly": _POLY},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, name, boundary, active_from) "
            "VALUES (:id, :farm, 'B1', 'Block', ST_GeomFromText(:poly, 4326), current_date)"
        ),
        {"id": block_id, "farm": farm_id, "poly": _POLY},
    )
    await admin_session.commit()
    return {"schema": schema, "farm_id": farm_id, "block_id": block_id}


async def _row(session: Any, alert_id: UUID) -> dict[str, Any]:
    got = (
        await session.execute(
            text("SELECT severity, group_key, action_type FROM alerts WHERE id = :id"),
            {"id": alert_id},
        )
    ).mappings()
    return dict(got.one())


@pytest.mark.asyncio
async def test_a_leaf_republished_at_a_higher_severity_escalates_the_open_row(
    admin_session: Any,
) -> None:
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    today = date(2026, 9, 3)
    rule_code = "tree:t_canopy:leaf_a"
    alert_id = uuid4()

    warn_key = build_group_key(
        tree_code="t_canopy", leaf_node_id="leaf_a", action_type="scout", severity="warning"
    )
    created = await repo.insert_alert(
        alert_id=alert_id,
        block_id=seed["block_id"],
        cell_id=None,
        rule_code=rule_code,
        severity="warning",
        action_type="scout",
        diagnosis_en="Canopy thinning",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot={},
        actor_user_id=None,
        group_key=warn_key,
        group_parent_id=None,
        is_group=False,
        today=today,
    )
    assert created is True

    # The sweep runs again after the leaf was republished as critical. The
    # INSERT is refused by the partial UNIQUE — no severity in it — which is
    # the whole shape of the bug.
    crit_key = build_group_key(
        tree_code="t_canopy", leaf_node_id="leaf_a", action_type="spray", severity="critical"
    )
    refused = await repo.insert_alert(
        alert_id=uuid4(),
        block_id=seed["block_id"],
        cell_id=None,
        rule_code=rule_code,
        severity="critical",
        action_type="spray",
        diagnosis_en="Canopy collapse",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot={},
        actor_user_id=None,
        group_key=crit_key,
        group_parent_id=None,
        is_group=False,
        today=today,
    )
    assert refused is False

    found = await repo.find_open_alert(block_id=seed["block_id"], rule_code=rule_code)
    assert found == alert_id
    await repo.bump_recurrence(row_id=alert_id, today=today, actor_user_id=None)

    # Bumping alone leaves the row saying "warning" — that is the defect.
    assert (await _row(admin_session, alert_id))["severity"] == "warning"

    await repo.restate_from_leaf(
        row_id=alert_id, severity="critical", group_key=crit_key, action_type="spray"
    )
    await admin_session.commit()

    row = await _row(admin_session, alert_id)
    assert row["severity"] == "critical"
    # The key moves with it, or the row sits under the old severity's card in
    # the Action Center while reading critical everywhere else.
    assert row["group_key"] == crit_key
    assert row["action_type"] == "spray"


@pytest.mark.asyncio
async def test_de_escalation_is_written_too(admin_session: Any) -> None:
    """The row states what the tree says NOW, in both directions. A leaf
    relaxed from critical to warning must stop colouring the block red."""
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    today = date(2026, 9, 3)
    rule_code = "tree:t_water:leaf_b"
    alert_id = uuid4()
    crit_key = build_group_key(
        tree_code="t_water", leaf_node_id="leaf_b", action_type="irrigate", severity="critical"
    )
    warn_key = build_group_key(
        tree_code="t_water", leaf_node_id="leaf_b", action_type="irrigate", severity="warning"
    )

    assert await repo.insert_alert(
        alert_id=alert_id,
        block_id=seed["block_id"],
        cell_id=None,
        rule_code=rule_code,
        severity="critical",
        action_type="irrigate",
        diagnosis_en="Water stress",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot={},
        actor_user_id=None,
        group_key=crit_key,
        group_parent_id=None,
        is_group=False,
        today=today,
    )

    await repo.restate_from_leaf(
        row_id=alert_id, severity="warning", group_key=warn_key, action_type="irrigate"
    )
    await admin_session.commit()

    assert (await _row(admin_session, alert_id))["severity"] == "warning"


@pytest.mark.asyncio
async def test_an_unchanged_leaf_writes_nothing(admin_session: Any) -> None:
    """The statement is guarded, so the ordinary case — the same leaf firing
    again at the same severity, which is nearly every firing — does not touch
    `updated_at` and does not look like an edit in the audit trail."""
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    today = date(2026, 9, 3)
    rule_code = "tree:t_same:leaf_c"
    alert_id = uuid4()
    key = build_group_key(
        tree_code="t_same", leaf_node_id="leaf_c", action_type="scout", severity="warning"
    )
    assert await repo.insert_alert(
        alert_id=alert_id,
        block_id=seed["block_id"],
        cell_id=None,
        rule_code=rule_code,
        severity="warning",
        action_type="scout",
        diagnosis_en="Same",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot={},
        actor_user_id=None,
        group_key=key,
        group_parent_id=None,
        is_group=False,
        today=today,
    )
    await admin_session.commit()
    before = (
        await admin_session.execute(
            text("SELECT updated_at FROM alerts WHERE id = :id"), {"id": alert_id}
        )
    ).scalar_one()

    await repo.restate_from_leaf(
        row_id=alert_id, severity="warning", group_key=key, action_type="scout"
    )
    await admin_session.commit()

    after = (
        await admin_session.execute(
            text("SELECT updated_at FROM alerts WHERE id = :id"), {"id": alert_id}
        )
    ).scalar_one()
    assert after == before
