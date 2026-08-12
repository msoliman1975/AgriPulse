"""Integration tests for the runtime RBAC edits.

Covers the write path end to end: capability gating, the two lock-out
guardrails, the override row, the change trail a reset leaves behind, and the
cross-process propagation that makes any of it reach another pod.

`StubAuth` in conftest replaces `AuthMiddleware`, which is where
`overlay.ensure_fresh()` is normally awaited. That is convenient here rather
than a gap: it means the refresh has to be driven explicitly, which is exactly
how a *second* pod picks the change up. Sleeping out a 30s TTL would test the
clock, not the code.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.shared.auth.context import PlatformRole, TenantRole
from app.shared.rbac import overlay
from app.shared.rbac.check import get_default_registry

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]

ROLE = "Agronomist"
CAP = "plan.manage"
PATH = f"/api/v1/admin/rbac/roles/{ROLE}/capabilities/{CAP}"


def _client(context) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _admin_client() -> AsyncClient:
    return _client(
        make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    )


def _support_client() -> AsyncClient:
    """PlatformSupport: holds `platform.read`, must not hold `platform.manage_rbac`."""
    return _client(
        make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_SUPPORT)
    )


@pytest.fixture(autouse=True)
async def _clean_overrides(admin_session):
    """Leave no policy behind — these rows are global and would leak between tests."""
    yield
    await admin_session.execute(text("DELETE FROM public.rbac_role_capability_overrides"))
    await admin_session.execute(text("DELETE FROM public.rbac_change_log"))
    await admin_session.commit()
    overlay.clear_cache()


# ---------- gating --------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_support_can_read_but_not_write() -> None:
    """Support reads policy; it does not author it."""
    async with _support_client() as client:
        assert (await client.get("/api/v1/admin/rbac/matrix")).status_code == 200
        response = await client.put(PATH, json={"granted": True})
    assert response.status_code == 403
    assert "platform.manage_rbac" in response.text


@pytest.mark.asyncio
async def test_tenant_role_cannot_write() -> None:
    context = make_context(user_id=uuid4(), tenant_id=uuid4(), tenant_role=TenantRole.TENANT_OWNER)
    async with _client(context) as client:
        response = await client.put(PATH, json={"granted": True})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_matrix_tells_the_caller_whether_they_may_edit() -> None:
    async with _admin_client() as client:
        assert (await client.get("/api/v1/admin/rbac/matrix")).json()["can_manage"] is True
    async with _support_client() as client:
        assert (await client.get("/api/v1/admin/rbac/matrix")).json()["can_manage"] is False


# ---------- the guardrails ------------------------------------------------


@pytest.mark.parametrize(
    "capability", ["platform.manage_rbac", "platform.manage_tenants"]
)
@pytest.mark.asyncio
async def test_platform_admin_cannot_be_edited(capability: str) -> None:
    """Refused server-side, not merely hidden in the UI."""
    async with _admin_client() as client:
        response = await client.put(
            f"/api/v1/admin/rbac/roles/PlatformAdmin/capabilities/{capability}",
            json={"granted": False},
        )
    assert response.status_code == 422
    assert "PlatformAdmin" in response.text


@pytest.mark.asyncio
async def test_unknown_role_and_capability_are_named_in_the_422() -> None:
    async with _admin_client() as client:
        bad_role = await client.put(
            "/api/v1/admin/rbac/roles/Wizard/capabilities/plan.manage", json={"granted": True}
        )
        bad_cap = await client.put(
            "/api/v1/admin/rbac/roles/Scout/capabilities/plan.raed", json={"granted": True}
        )
    assert bad_role.status_code == 422
    assert "Wizard" in bad_role.text
    assert bad_cap.status_code == 422
    assert "plan.raed" in bad_cap.text


@pytest.mark.asyncio
async def test_a_platform_admin_row_inserted_by_hand_is_ignored(admin_session) -> None:
    """The second guard, exercised: the loader drops what the API refused.

    Someone with psql can write the row the endpoint rejects. It must still not
    reach the resolver, or the guard is only a UI convention.
    """
    await admin_session.execute(
        text(
            "INSERT INTO public.rbac_role_capability_overrides (role, capability, granted) "
            "VALUES ('PlatformAdmin', 'platform.manage_rbac', false)"
        )
    )
    await admin_session.commit()

    overlay.clear_cache()
    await overlay.ensure_fresh()
    assert "PlatformAdmin" not in overlay.current()
    assert get_default_registry().role_grants("PlatformAdmin", "platform.manage_rbac") is True


# ---------- the write path ------------------------------------------------


@pytest.mark.asyncio
async def test_granting_writes_a_row_and_reaches_another_pod(admin_session) -> None:
    registry = get_default_registry()
    assert registry.baseline_grants(ROLE, CAP) is False

    async with _admin_client() as client:
        response = await client.put(PATH, json={"granted": True, "note": "agreed with agronomy"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "role": ROLE,
        "capability": CAP,
        "baseline": False,
        "effective": True,
        "overridden": True,
        "action": "grant",
        "unchanged": False,
    }

    row = (
        await admin_session.execute(
            text(
                "SELECT granted, note FROM public.rbac_role_capability_overrides "
                "WHERE role = :r AND capability = :c"
            ),
            {"r": ROLE, "c": CAP},
        )
    ).one()
    assert row.granted is True
    assert row.note == "agreed with agronomy"

    # A pod that did not serve the write still answers from the baseline until
    # its snapshot ages out — this is the documented staleness, not a bug.
    overlay.clear_cache()
    assert registry.role_grants(ROLE, CAP) is False
    # ...and picks the change up on its next refresh.
    await overlay.ensure_fresh()
    assert registry.role_grants(ROLE, CAP) is True


@pytest.mark.asyncio
async def test_revoking_a_baseline_grant_takes_effect(admin_session) -> None:
    registry = get_default_registry()
    assert registry.baseline_grants("Scout", "alert.read") is True

    async with _admin_client() as client:
        response = await client.put(
            "/api/v1/admin/rbac/roles/Scout/capabilities/alert.read",
            json={"granted": False},
        )
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "revoke"

    overlay.clear_cache()
    await overlay.ensure_fresh()
    assert registry.role_grants("Scout", "alert.read") is False


@pytest.mark.asyncio
async def test_setting_a_value_that_matches_the_baseline_stores_no_row(admin_session) -> None:
    """Toggling back by hand must land in the same state as pressing Reset.

    Otherwise "has an override" stops meaning "differs from the default" and
    the modified-marker in the UI lies.
    """
    async with _admin_client() as client:
        await client.put(PATH, json={"granted": True})
        response = await client.put(PATH, json={"granted": False})

    assert response.status_code == 200, response.text
    assert response.json()["overridden"] is False
    count = (
        await admin_session.execute(
            text(
                "SELECT count(*) AS n FROM public.rbac_role_capability_overrides "
                "WHERE role = :r AND capability = :c"
            ),
            {"r": ROLE, "c": CAP},
        )
    ).one()
    assert count.n == 0


@pytest.mark.asyncio
async def test_reset_deletes_the_row_and_leaves_a_trail(admin_session) -> None:
    """The reason `rbac_change_log` exists: reset destroys its own evidence."""
    async with _admin_client() as client:
        await client.put(PATH, json={"granted": True, "note": "trial"})
        response = await client.delete(f"{PATH}?note=reverted")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "role": ROLE,
        "capability": CAP,
        "baseline": False,
        "effective": False,
        "overridden": False,
        "action": "reset",
        "unchanged": False,
    }

    remaining = (
        await admin_session.execute(
            text("SELECT count(*) AS n FROM public.rbac_role_capability_overrides")
        )
    ).one()
    assert remaining.n == 0

    trail = (
        await admin_session.execute(
            text(
                "SELECT action, previous_effective, new_effective, note "
                "FROM public.rbac_change_log ORDER BY id"
            )
        )
    ).all()
    assert [r.action for r in trail] == ["grant", "reset"]
    assert trail[0].note == "trial"
    assert (trail[1].previous_effective, trail[1].new_effective) == (True, False)

    overlay.clear_cache()
    await overlay.ensure_fresh()
    assert get_default_registry().role_grants(ROLE, CAP) is False


@pytest.mark.asyncio
async def test_resetting_something_never_overridden_is_a_quiet_noop(admin_session) -> None:
    """An idempotent retry must not bury the real entries in the trail."""
    async with _admin_client() as client:
        response = await client.delete(PATH)
    assert response.status_code == 200
    assert response.json()["unchanged"] is True

    count = (
        await admin_session.execute(text("SELECT count(*) AS n FROM public.rbac_change_log"))
    ).one()
    assert count.n == 0


# ---------- what the screen shows -----------------------------------------


@pytest.mark.asyncio
async def test_matrix_reports_the_override_and_the_effective_grant() -> None:
    """The screen must never contradict itself.

    Deliberately no `ensure_fresh()` here: the matrix resolves grants against
    the rows it just read, not the cached snapshot, so a freshly written
    override shows as both granted *and* modified even on a pod whose cache is
    still cold. Mixing the two sources would flag a row "modified" while its
    marker still read the old value.
    """
    overlay.clear_cache()
    async with _admin_client() as client:
        await client.put(PATH, json={"granted": True, "note": "why"})
        body = (await client.get("/api/v1/admin/rbac/matrix")).json()

    role = {r["name"]: r for r in body["roles"]}[ROLE]
    assert CAP in role["capabilities"], "effective grants must include the override"
    assert [o["capability"] for o in role["overrides"]] == [CAP]
    assert role["overrides"][0]["granted"] is True
    assert role["overrides"][0]["note"] == "why"
    assert body["propagation_seconds"] == 30

    admin = {r["name"]: r for r in body["roles"]}["PlatformAdmin"]
    assert admin["immutable"] is True
    assert role["immutable"] is False


@pytest.mark.asyncio
async def test_change_log_endpoint_returns_newest_first() -> None:
    async with _admin_client() as client:
        await client.put(PATH, json={"granted": True})
        await client.delete(PATH)
        changes = (await client.get("/api/v1/admin/rbac/changes")).json()

    assert [c["action"] for c in changes] == ["reset", "grant"]
    assert changes[0]["role"] == ROLE
    assert changes[0]["capability"] == CAP
    # The actor is recorded, or the trail answers "what" without "who".
    assert changes[0]["changed_by"] is not None
