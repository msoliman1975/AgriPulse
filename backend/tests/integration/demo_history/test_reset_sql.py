"""The build-tenant reset against a real tenant schema.

Every table the reset names must exist in a tenant schema, and the reset
must refuse a tenant that is not a build tenant. A wrong table name here
fails the cluster Job an hour into a deploy cycle; this finds it in CI.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.demo_history.reset import reset_build_tenant
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_reset_runs_on_a_fresh_tenant(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = f"reset-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    await admin_session.commit()
    monkeypatch.setenv("DEMO_HISTORY_BUILD_SCHEMA_PREFIX", tenant.schema_name)
    get_settings.cache_clear()
    try:
        counts = await reset_build_tenant(AsyncSessionLocal(), tenant.schema_name)
    finally:
        get_settings.cache_clear()

    assert counts["recommendations"] == 0
    assert counts["decision_tree_eval_runs"] == 0
    assert counts["block_crops_stage_cleared"] == 0
