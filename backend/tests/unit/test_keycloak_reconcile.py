"""IH-6: DB -> Keycloak reconcile logic (DB-free, against the fake)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.iam.reconcile import DesiredUserState, reconcile_users
from app.shared.keycloak.fakes import FakeKeycloakClient, FakeUser


class _StubAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record_archive(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _desired(subject: str, *, enabled: bool, tid: str | None, role: str | None) -> DesiredUserState:
    return DesiredUserState(
        user_id=uuid4(),
        keycloak_subject=subject,
        enabled=enabled,
        tenant_id=tid,
        tenant_role=role,
    )


@pytest.mark.asyncio
async def test_enables_user_active_in_db_but_disabled_in_kc() -> None:
    fake = FakeKeycloakClient()
    fake.users["u1"] = FakeUser(
        id="u1", email="a@b.c", full_name="A", enabled=False, tenant_id="t1", tenant_role="Viewer"
    )
    audit = _StubAudit()

    summary = await reconcile_users(
        [_desired("u1", enabled=True, tid="t1", role="Viewer")], fake, audit=audit
    )

    assert fake.users["u1"].enabled is True
    assert summary == {"checked": 1, "corrected": 1, "skipped": 0}
    assert audit.events[0]["details"]["changes"] == ["enabled"]


@pytest.mark.asyncio
async def test_disables_user_inactive_in_db_but_enabled_in_kc() -> None:
    fake = FakeKeycloakClient()
    fake.users["u1"] = FakeUser(id="u1", email="a@b.c", full_name="A", enabled=True)
    audit = _StubAudit()

    summary = await reconcile_users(
        [_desired("u1", enabled=False, tid=None, role=None)], fake, audit=audit
    )

    assert fake.users["u1"].enabled is False
    assert summary["corrected"] == 1


@pytest.mark.asyncio
async def test_corrects_tenant_role_drift() -> None:
    fake = FakeKeycloakClient()
    fake.users["u1"] = FakeUser(
        id="u1", email="a@b.c", full_name="A", enabled=True, tenant_id="t1", tenant_role="Viewer"
    )
    audit = _StubAudit()

    await reconcile_users(
        [_desired("u1", enabled=True, tid="t1", role="TenantAdmin")], fake, audit=audit
    )

    assert fake.users["u1"].tenant_role == "TenantAdmin"
    assert audit.events[0]["details"]["changes"] == ["tenant_attrs"]


@pytest.mark.asyncio
async def test_no_correction_when_consistent() -> None:
    fake = FakeKeycloakClient()
    fake.users["u1"] = FakeUser(
        id="u1", email="a@b.c", full_name="A", enabled=True, tenant_id="t1", tenant_role="Viewer"
    )
    audit = _StubAudit()

    summary = await reconcile_users(
        [_desired("u1", enabled=True, tid="t1", role="Viewer")], fake, audit=audit
    )

    assert summary == {"checked": 1, "corrected": 0, "skipped": 0}
    assert audit.events == []


@pytest.mark.asyncio
async def test_pending_subject_is_skipped() -> None:
    fake = FakeKeycloakClient()
    audit = _StubAudit()

    summary = await reconcile_users(
        [_desired("pending::a@b.c", enabled=True, tid="t1", role="Viewer")], fake, audit=audit
    )

    assert summary == {"checked": 0, "corrected": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_unknown_kc_user_is_skipped() -> None:
    fake = FakeKeycloakClient()
    audit = _StubAudit()

    summary = await reconcile_users(
        [_desired("ghost", enabled=True, tid="t1", role="Viewer")], fake, audit=audit
    )

    assert summary == {"checked": 0, "corrected": 0, "skipped": 1}
