"""The demo farm must not count towards what a trial is using.

`trial_usage` feeds the platform's capacity numbers: farms and feddan
under trial. The demo farm is our land, seeded into the tenant so the
product is not empty on day one. Counting it would overstate every trial
and push the platform against its own caps for nothing.

The test builds one trial tenant with three farms: the customer's own, the
seeded demo farm, and one whose active window has ended. Only the first
should be counted.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

SCHEMA = "tenant_zzdemousage"

FARMS_TABLE = f"""
CREATE TABLE {SCHEMA}.farms (
    id uuid PRIMARY KEY,
    area_m2 numeric(14, 2) NOT NULL,
    active_to date,
    is_demo boolean NOT NULL DEFAULT FALSE
)
"""

# farms.area_m2 is square metres; the screen reports feddan. Imported
# rather than repeated so the expected numbers cannot drift from the code.
from app.modules.billing.repository import _M2_PER_FEDDAN as FEDDAN_M2


@pytest.fixture
async def trial_tenant(admin_session):  # type: ignore[no-untyped-def]
    """One active tenant on a live free trial, with three farms."""
    tenant_id = uuid4()
    await admin_session.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    await admin_session.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    await admin_session.execute(text(FARMS_TABLE))
    await admin_session.execute(
        text(
            """
            INSERT INTO public.tenants (id, slug, name, contact_email, schema_name, status)
            VALUES (:id, :slug, 'Demo usage probe', 'probe@example.com', :schema, 'active')
            """
        ),
        {"id": tenant_id, "slug": f"zz-demo-usage-{tenant_id.hex[:8]}", "schema": SCHEMA},
    )
    await admin_session.execute(
        text(
            """
            INSERT INTO public.tenant_subscriptions
                   (tenant_id, tier, started_at, trial_end, is_current)
            VALUES (:id, 'free', CURRENT_DATE - 5, CURRENT_DATE + 20, TRUE)
            """
        ),
        {"id": tenant_id},
    )
    await admin_session.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.farms (id, area_m2, active_to, is_demo) VALUES
                (:own,     :own_area,  NULL,               FALSE),
                (:demo,    :demo_area, NULL,               TRUE),
                (:expired, :own_area,  CURRENT_DATE - 1,   FALSE)
            """
        ),
        {
            "own": uuid4(),
            "demo": uuid4(),
            "expired": uuid4(),
            "own_area": 10 * FEDDAN_M2,
            "demo_area": 100 * FEDDAN_M2,
        },
    )
    await admin_session.commit()
    try:
        yield tenant_id
    finally:
        await admin_session.rollback()
        await admin_session.execute(
            text("DELETE FROM public.tenant_subscriptions WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
        await admin_session.execute(
            text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id}
        )
        await admin_session.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await admin_session.commit()


async def test_trial_usage_leaves_the_demo_farm_out(admin_session, trial_tenant) -> None:  # type: ignore[no-untyped-def]
    from app.modules.billing.repository import TrialRepository

    usage = await TrialRepository(public_session=admin_session).trial_usage()

    # One farm of 10 feddan. Without the exclusion this reads 2 farms and
    # 110 feddan, because the demo farm is the larger of the two.
    assert usage["trial_farms"] == 1
    assert usage["trial_area_feddan"] == 10
