"""Integration test: a tenant override switches a rule body to the new
``condition_tree`` predicate and the engine fires it correctly.

Reuses the seeding helper from ``test_alerts_pipeline`` so the only new
surface here is the tree-shaped conditions JSONB and the snapshot
assertion.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.service import get_alerts_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from tests.integration.alerts.test_alerts_pipeline import _seed_block_with_ndvi_row

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_condition_tree_override_fires_and_snapshots_values(
    admin_session: AsyncSession,
) -> None:
    """Override the seed rule with a ``condition_tree`` body and verify
    the engine evaluates it and persists the resolved-values snapshot.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4a-cond-tree",
        name="PR-S4-A condition_tree",
        contact_email="ops@pr-s4a.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            # Replace the seed rule's conditions with an equivalent tree.
            await svc.upsert_override(
                rule_code="ndvi_severe_drop",
                modified_conditions={
                    "type": "condition_tree",
                    "tree": {
                        "all_of": [
                            {
                                "op": "lt",
                                "left": {"source": "indices", "index_code": "ndvi"},
                                "right": -1.5,
                            }
                        ]
                    },
                },
                modified_actions=None,
                modified_severity=None,
                is_disabled=False,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
            summary = await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )

    assert summary["alerts_opened"] == 1

    # Snapshot should record the resolved value-ref.
    snap_row = (
        await admin_session.execute(
            text(
                f'SELECT signal_snapshot FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id},
        )
    ).scalar_one()
    assert snap_row["tree_match"] is True
    # Postgres NUMERIC may roundtrip "-2.0" as "-2.0000" (column scale); compare numerically.
    resolved = Decimal(snap_row["values"]["indices.ndvi.baseline_deviation"])
    assert resolved == Decimal("-2.0")


@pytest.mark.asyncio
async def test_condition_tree_does_not_fire_when_signal_above_threshold(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4a-cond-tree-skip",
        name="PR-S4-A condition_tree skip",
        contact_email="ops@pr-s4a-skip.test",
    )
    # Deviation -0.5 is above both seed thresholds (severe < -1.5 and
    # warning between [-1.5,-0.75]) so neither legacy rule fires; the
    # condition_tree override should also miss.
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-0.5")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.upsert_override(
                rule_code="ndvi_severe_drop",
                modified_conditions={
                    "type": "condition_tree",
                    "tree": {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndvi"},
                        "right": -1.5,
                    },
                },
                modified_actions=None,
                modified_severity=None,
                is_disabled=False,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
            summary = await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )

    assert summary["alerts_opened"] == 0
