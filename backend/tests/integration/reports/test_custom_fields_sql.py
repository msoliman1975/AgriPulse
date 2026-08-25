"""DB-backed smoke test for the custom-column and signal-details SQL.

Same reasoning as ``test_weather_crop_context``: the unit tests mock these
helpers, so only a real asyncpg session catches a bind whose type the driver
cannot infer (``AmbiguousParameterError``). Both new query families are full of
the shapes that trigger it — ``= ANY(:codes)`` over a text array, a UUID array,
a NUMERIC comparison, and a text-typed empty-string bind — and every one of
them fails on *every* call rather than only on the filtered path.

The tenant is seeded empty on purpose: what is under test is that each
statement plans and executes, not what it returns. Row-level behaviour is
covered by the unit tests.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.reports.custom_fields import (
    CustomFieldRef,
    list_custom_fields,
    load_custom_values,
)
from app.modules.reports.service import resolve_period
from app.modules.reports.signal_details import select_signal_details
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.ids import schema_name_for

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_custom_field_and_signal_detail_sql_runs_against_asyncpg(
    admin_session: object,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"rep-cf-{uuid4().hex[:8]}",
        name="Reports Custom Fields",
        contact_email="ops@rep-cf.test",
    )
    schema = schema_name_for(tenant.tenant_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))
        farm_id = uuid4()
        period = resolve_period(None, None)

        # Catalog: two statements, one per source.
        assert await list_custom_fields(session, farm_id=farm_id) == []

        # Values: the text-array bind on both sources, plus the timestamp
        # bounds on the signal side.
        assert (
            await load_custom_values(
                session,
                farm_id=farm_id,
                refs=[
                    CustomFieldRef(source="crop_attribute", code="brix"),
                    CustomFieldRef(source="signal", code="trap_count"),
                ],
                since=period.since,
                until=period.until,
            )
            == {}
        )

        # No refs must not reach the database at all.
        assert (
            await load_custom_values(
                session, farm_id=farm_id, refs=[], since=period.since, until=period.until
            )
            == {}
        )

        # Signal details with every optional predicate switched on at once, so
        # each bind is type-checked by the driver in one pass.
        assert (
            await select_signal_details(
                session,
                farm_id=farm_id,
                since=period.since,
                until=period.until,
                signal_codes=["trap_count"],
                block_ids=[uuid4()],
                categorical_values=["aphid"],
                min_value=Decimal("1.5"),
                max_value=Decimal("99.5"),
                recorded_by=uuid4(),
                location_mode="entity",
                with_notes_only=True,
                with_attachment_only=True,
                limit=10,
            )
            == []
        )

        # And with none of them, which is the shape almost every call takes.
        assert (
            await select_signal_details(
                session,
                farm_id=farm_id,
                since=period.since,
                until=period.until,
                signal_codes=[],
                block_ids=[],
                categorical_values=[],
                min_value=None,
                max_value=None,
                recorded_by=None,
                location_mode=None,
                with_notes_only=False,
                with_attachment_only=False,
                limit=10,
            )
            == []
        )


@pytest.mark.asyncio
async def test_a_signal_with_observations_but_no_assignment_is_offered(
    admin_session: object,
) -> None:
    """A recorded signal must reach the column picker without an assignment.

    `signal_observations` has no foreign key to `signal_assignments`, and no
    write path checks for one, so a signal can be recorded against a definition
    that was never assigned or whose assignment was later retired.

    This is not hypothetical. On the day the feature shipped, `fruit_tss_brix`
    on the Bashier Elkhier farm had 145 observations across 36 blocks and no
    assignment row, so the picker offered eight crop attributes and none of the
    one signal the farm actually used. An assignment-only catalog reports that
    a farm has no signals while its observations sit in the next table.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"rep-sig-{uuid4().hex[:8]}",
        name="Reports Signal Columns",
        contact_email="ops@rep-sig.test",
    )
    schema = schema_name_for(tenant.tenant_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))
        farm_id = uuid4()
        definition_id = uuid4()
        code = f"brix_{uuid4().hex[:8]}"

        await session.execute(
            text(
                """
                INSERT INTO public.signal_definitions
                    (id, tenant_id, code, name, value_kind, unit, is_active)
                VALUES (:id, :tenant_id, :code, 'Fruit Brix', 'numeric', NULL, TRUE)
                """
            ),
            {"id": definition_id, "tenant_id": tenant.tenant_id, "code": code},
        )
        # Deliberately no signal_assignments row.
        await session.execute(
            text(
                """
                INSERT INTO signal_observations
                    (time, id, signal_definition_id, block_id, farm_id,
                     value_numeric, recorded_by, location_mode)
                VALUES (now(), :id, :definition_id, :block_id, :farm_id,
                        7.9, :recorded_by, 'entity')
                """
            ),
            {
                "id": uuid4(),
                "definition_id": definition_id,
                "block_id": uuid4(),
                "farm_id": farm_id,
                "recorded_by": uuid4(),
            },
        )
        await session.commit()

        fields = await list_custom_fields(session, farm_id=farm_id)
        assert [f.key for f in fields] == [f"signal:{code}"]

        # A different farm must not pick it up: the second arm is farm-scoped
        # on the observation, not tenant-wide.
        assert await list_custom_fields(session, farm_id=uuid4()) == []
