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
    # `create_tenant` only flushes — it leaves the commit to the caller's
    # `session.begin()` block, and the fixture has none. Without this commit
    # the `public.tenants` row is invisible to the second connection below, so
    # the catalog's `current_schema()` tenant lookup returns NULL and every
    # tenant-authored definition is filtered out. That is a harness artifact,
    # not the behaviour under test, and it costs a CI round trip to rediscover.
    await admin_session.commit()  # type: ignore[attr-defined]
    schema = schema_name_for(tenant.tenant_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))

        # The catalog resolves the tenant by matching `current_schema()` against
        # `public.tenants`, the same predicate `signals.repository` uses. If that
        # lookup returns NULL, every tenant-authored definition is filtered out
        # and the test below fails with an empty list that says nothing about
        # why. Assert the two facts it depends on, so a harness problem names
        # itself instead of looking like a query bug.
        resolved = (
            (
                await session.execute(
                    text(
                        """
                        SELECT current_schema() AS schema_name,
                               (SELECT x.id FROM public.tenants x
                                 WHERE replace(x.id::text, '-', '')
                                       = replace(current_schema(), 'tenant_', '')
                               ) AS resolved_tenant_id
                        """
                    )
                )
            )
            .mappings()
            .one()
        )
        assert resolved["schema_name"] == schema, (
            f"search_path did not take: current_schema() is {resolved['schema_name']!r}, "
            f"expected {schema!r}"
        )
        assert resolved["resolved_tenant_id"] == tenant.tenant_id, (
            "the tenant row is not visible to this connection, so the two-tier "
            f"filter drops every tenant definition: lookup returned "
            f"{resolved['resolved_tenant_id']!r}, expected {tenant.tenant_id!r}"
        )

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
        # Deliberately NOT committed. `list_custom_fields` reads through this
        # same session, so it sees these rows inside the open transaction, and
        # they roll back when the session closes rather than leaving a platform
        # catalog row behind for every other test.
        #
        # An earlier version committed here and the test failed with an empty
        # list three runs running. `Session.commit()` ends the transaction and
        # returns the connection to the pool, so the next statement can run on a
        # connection that never received the `SET search_path` above — and the
        # catalog then resolves `current_schema()` to something that matches no
        # tenant, which drops every tenant-authored definition.

        # Re-assert the two facts the catalog depends on at the point of use,
        # not only at the top of the test. They are what a lost search_path
        # would break, and an empty list on its own does not say which.
        still = (
            (
                await session.execute(
                    text(
                        """
                        SELECT current_schema() AS schema_name,
                               (SELECT count(*) FROM public.signal_definitions d
                                 WHERE d.id = :definition_id) AS definitions,
                               (SELECT count(*) FROM signal_observations o
                                 WHERE o.farm_id = :farm_id) AS observations
                        """
                    ),
                    {"definition_id": definition_id, "farm_id": farm_id},
                )
            )
            .mappings()
            .one()
        )
        assert still["schema_name"] == schema, (
            f"search_path was lost before the read: current_schema() is "
            f"{still['schema_name']!r}, expected {schema!r}"
        )
        assert still["definitions"] == 1, "the definition row is not visible to the read"
        assert still["observations"] == 1, "the observation row is not visible to the read"

        fields = await list_custom_fields(session, farm_id=farm_id)
        assert [f.key for f in fields] == [f"signal:{code}"]

        # A different farm must not pick it up: the second arm is farm-scoped
        # on the observation, not tenant-wide.
        assert await list_custom_fields(session, farm_id=uuid4()) == []
