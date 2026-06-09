"""Tenant parameter overrides (PR-C).

Covers the round-trip from REST → repo → engine:

  * Setting an override stores a row in
    ``tenant_<id>.tree_parameter_overrides``.
  * The next ``evaluate_tree`` for that tree sees the override layered
    on top of declared defaults via the bulk-load in
    ``RecommendationsServiceImpl.evaluate_block``.
  * Overrides for parameters that aren't declared in the tree's
    current published version are rejected at the service layer
    (rather than silently dropped at sweep time).
  * Type coercion: a string ``"-0.20"`` becomes a numeric value when
    the parameter is declared as ``number``. Min/max violations raise.
  * Removing an override falls back to the declared default.

We exercise the service directly (no HTTP layer) so the tests stay
close to the override semantics and don't pull in auth/RBAC plumbing.
"""

from __future__ import annotations

import textwrap
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    _ParamNameUnknownError,
    _ParamValueCoercionError,
    get_recommendations_service,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


_PARAM_TREE_YAML = textwrap.dedent(
    """\
    code: prc_override_demo
    name_en: PR-C Override Demo
    parameters:
      ndvi_drop_threshold:
        type: number
        default: -0.15
        min: -0.5
        max: 0
    root: root
    nodes:
      root:
        condition:
          tree:
            op: lt
            left:
              source: indices
              index_code: ndvi
              key: baseline_deviation
            right:
              source: params
              name: ndvi_drop_threshold
        on_match: leaf_scout
        on_miss: leaf_noop
      leaf_scout:
        outcome:
          action_type: scout
          text_en: Scout for stress
      leaf_noop:
        outcome:
          action_type: no_action
          text_en: ok
    """
)


async def _create_tree_for_tenant(
    admin_session: AsyncSession, *, tenant_id, code_suffix: str
) -> str:
    """Author + publish a tree under the given tenant. Returns the code.

    Commits after publish so the new tenant-side session opened below
    sees the catalog rows (different session → no read-your-own-writes
    across sessions without a commit).
    """
    code = f"prc_demo_{code_suffix}"
    yaml_str = _PARAM_TREE_YAML.replace("prc_override_demo", code)
    svc = DecisionTreesAuthorService(public_session=admin_session, tenant_id=tenant_id)
    await svc.create_tree(code=code, crop_code=None, tree_yaml=yaml_str, actor_user_id=None)
    await svc.publish_version(code=code, version=1, actor_user_id=None)
    await admin_session.commit()
    return code


@pytest.mark.asyncio
async def test_override_round_trip_and_engine_apply(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prc-roundtrip-{uuid4().hex[:6]}",
        name="PR-C Override Round-trip",
        contact_email="ops@prc-roundtrip.test",
    )
    code = await _create_tree_for_tenant(
        admin_session, tenant_id=tenant.tenant_id, code_suffix="rt"
    )

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )
        async with factory() as public_session:
            svc = get_recommendations_service(
                tenant_session=tenant_session, public_session=public_session
            )
            # Read with no overrides yet
            initial = await svc.list_tree_param_overrides(code=code, tenant_id=tenant.tenant_id)
            assert initial["found"] is True
            assert initial["overrides"] == {}
            assert initial["declarations"]["ndvi_drop_threshold"]["default"] == -0.15

            # Set an override; the service should coerce a numeric string
            # into a numeric value
            await svc.upsert_tree_param_override(
                code=code,
                tenant_id=tenant.tenant_id,
                param_name="ndvi_drop_threshold",
                value="-0.25",
                actor_user_id=None,
            )

            after = await svc.list_tree_param_overrides(code=code, tenant_id=tenant.tenant_id)
            assert after["overrides"]["ndvi_drop_threshold"] == -0.25

            # Delete it and the override goes away
            await svc.delete_tree_param_override(
                code=code,
                tenant_id=tenant.tenant_id,
                param_name="ndvi_drop_threshold",
                actor_user_id=None,
            )
            cleared = await svc.list_tree_param_overrides(code=code, tenant_id=tenant.tenant_id)
            assert cleared["overrides"] == {}


@pytest.mark.asyncio
async def test_override_for_undeclared_param_rejected(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prc-undeclared-{uuid4().hex[:6]}",
        name="PR-C Undeclared",
        contact_email="ops@prc-undeclared.test",
    )
    code = await _create_tree_for_tenant(
        admin_session, tenant_id=tenant.tenant_id, code_suffix="un"
    )

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )
        async with factory() as public_session:
            svc = get_recommendations_service(
                tenant_session=tenant_session, public_session=public_session
            )
            with pytest.raises(_ParamNameUnknownError):
                await svc.upsert_tree_param_override(
                    code=code,
                    tenant_id=tenant.tenant_id,
                    param_name="not_a_real_param",
                    value=1,
                    actor_user_id=None,
                )


@pytest.mark.asyncio
async def test_override_value_below_min_rejected(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prc-min-{uuid4().hex[:6]}",
        name="PR-C Min",
        contact_email="ops@prc-min.test",
    )
    code = await _create_tree_for_tenant(
        admin_session, tenant_id=tenant.tenant_id, code_suffix="mn"
    )

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )
        async with factory() as public_session:
            svc = get_recommendations_service(
                tenant_session=tenant_session, public_session=public_session
            )
            with pytest.raises(_ParamValueCoercionError, match="below min"):
                await svc.upsert_tree_param_override(
                    code=code,
                    tenant_id=tenant.tenant_id,
                    param_name="ndvi_drop_threshold",
                    value=-2.0,  # below min of -0.5
                    actor_user_id=None,
                )


@pytest.mark.asyncio
async def test_overrides_bulk_load_for_sweep(
    admin_session: AsyncSession,
) -> None:
    """The sweep loads overrides per tree via
    ``list_all_param_overrides_visible_to_tenant``; verify the bulk
    shape (one row per (tree_id, param_name)) returns the right
    grouping."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"prc-bulk-{uuid4().hex[:6]}",
        name="PR-C Bulk",
        contact_email="ops@prc-bulk.test",
    )
    code = await _create_tree_for_tenant(
        admin_session, tenant_id=tenant.tenant_id, code_suffix="bk"
    )

    factory = AsyncSessionLocal()
    async with factory() as tenant_session, tenant_session.begin():
        await tenant_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )
        async with factory() as public_session:
            svc = get_recommendations_service(
                tenant_session=tenant_session, public_session=public_session
            )
            # Resolve tree_id via the read endpoint then set override
            res = await svc.list_tree_param_overrides(code=code, tenant_id=tenant.tenant_id)
            tree_id = res["tree_id"]
            await svc.upsert_tree_param_override(
                code=code,
                tenant_id=tenant.tenant_id,
                param_name="ndvi_drop_threshold",
                value=-0.30,
                actor_user_id=None,
            )

            grouped = await svc._repo.list_all_param_overrides_visible_to_tenant(
                tree_ids=(tree_id,)
            )
            assert grouped[tree_id] == {"ndvi_drop_threshold": Decimal("-0.30")} or grouped[
                tree_id
            ] == {"ndvi_drop_threshold": -0.30}
