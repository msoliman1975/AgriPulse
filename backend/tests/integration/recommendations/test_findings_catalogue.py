"""The finding catalogues against a real database.

Covers the two tables public migration 0090 and tenant migration 0094
create, the service that writes them, and the one refusal that matters:
a tenant may not write a platform row.

Exercises the service layer directly, like `test_metadata_and_archive` and
`test_tenant_isolation`, so the tests sit next to the scoping rule rather
than behind a router and a JWT.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.findings import PLATFORM_SOURCE, TENANT_SOURCE
from app.modules.recommendations.repository import FindingsRepository
from app.modules.recommendations.service import (
    FindingsCatalogueService,
    _FindingCodeAlreadyExistsError,
    _FindingNotFoundError,
    _PlatformFindingNotEditableError,
)
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

# The eight codes public migration 0090 seeds. Read back from the live
# table below: the unit test checks the literal in the migration, this one
# checks the rows actually landed.
_SEEDED = {
    "ndvi_low",
    "dry",
    "nutrient_low",
    "cover_open",
    "pest_high",
    "pest_med",
    "mildew_high",
    "fly_high",
}

# One tenant schema for the whole module. Creating a tenant replays every
# tenant migration, and a schema per test is what pushed the integration
# job past its budget before. Each test uses its own finding codes, so the
# shared rows never meet.
_SHARED: dict[str, Any] = {}


async def _tenant_schema(admin_session: AsyncSession) -> str:
    if not _SHARED:
        slug = f"fc-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        _SHARED["schema"] = str(tenant.schema_name)
    # Re-applied every time. `admin_session` is function-scoped and a commit
    # anywhere drops the search_path with no error to say so — the symptom
    # is an empty list, not a failure.
    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return str(_SHARED["schema"])


async def _tenant_service(admin_session: AsyncSession) -> FindingsCatalogueService:
    schema = await _tenant_schema(admin_session)
    return FindingsCatalogueService(
        repo=FindingsRepository(tenant_session=admin_session, public_session=admin_session),
        tenant_schema=schema,
    )


def _platform_service(admin_session: AsyncSession) -> FindingsCatalogueService:
    return FindingsCatalogueService(
        repo=FindingsRepository(tenant_session=None, public_session=admin_session),
        tenant_schema=None,
    )


def _payload(code: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": code,
        "clause_en": f"{code} is out of band",
        "clause_ar": f"{code} خارج النطاق",
        "name_en": code.title(),
        "name_ar": "اسم",
        "default_status": "issue",
        "description_en": None,
        "description_ar": None,
    }
    base.update(overrides)
    return base


# ---- The seed -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_eight_codes_are_in_the_live_platform_table(
    admin_session: AsyncSession,
) -> None:
    findings = await _platform_service(admin_session).list_platform(include_inactive=True)

    assert {f["code"] for f in findings} >= _SEEDED
    assert all(f["source"] == PLATFORM_SOURCE for f in findings)
    assert all(f["shadowed"] is False for f in findings)


@pytest.mark.asyncio
async def test_every_seeded_row_carries_both_clauses_and_a_valid_status(
    admin_session: AsyncSession,
) -> None:
    findings = await _platform_service(admin_session).list_platform(include_inactive=True)
    seeded = {f["code"]: f for f in findings if f["code"] in _SEEDED}

    assert set(seeded) == _SEEDED
    for code, row in seeded.items():
        assert row["clause_en"].strip(), code
        assert row["clause_ar"].strip(), code
        assert row["default_status"] in {"na", "very_good", "good", "issue", "alert"}, code


# ---- The CHECK constraints ------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_refuses_a_status_outside_the_platform_list(
    admin_session: AsyncSession,
) -> None:
    """The reports vocabulary, specifically.

    `stressed` is a real status value elsewhere in this codebase — it is
    what `reports.service._status_from_z` returns — so it is the wrong
    value most likely to be written here by someone who found the wrong
    list. The CHECK is what stops it.
    """
    with pytest.raises((IntegrityError, DBAPIError)):
        await admin_session.execute(
            text(
                "INSERT INTO public.decision_tree_findings "
                "(code, clause_en, clause_ar, name_en, name_ar, default_status) "
                "VALUES ('bad_status_probe', 'x is low', 'س منخفض', 'X', 'س', 'stressed')"
            )
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_the_database_refuses_a_clause_with_a_comma(
    admin_session: AsyncSession,
) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        await admin_session.execute(
            text(
                "INSERT INTO public.decision_tree_findings "
                "(code, clause_en, clause_ar, name_en, name_ar, default_status) "
                "VALUES ('comma_probe', 'x is low, and falling', 'س منخفض', "
                "'X', 'س', 'issue')"
            )
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_the_database_refuses_a_code_that_is_not_lower_snake_case(
    admin_session: AsyncSession,
) -> None:
    with pytest.raises((IntegrityError, DBAPIError)):
        await admin_session.execute(
            text(
                "INSERT INTO public.decision_tree_findings "
                "(code, clause_en, clause_ar, name_en, name_ar, default_status) "
                "VALUES ('Bad Code', 'x is low', 'س منخفض', 'X', 'س', 'issue')"
            )
        )
    await admin_session.rollback()


# ---- Platform writes ------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_create_update_and_deactivate(admin_session: AsyncSession) -> None:
    service = _platform_service(admin_session)
    code = f"p_{uuid4().hex[:8]}"

    created = await service.create(payload=_payload(code), actor_user_id=None)
    assert created["code"] == code
    assert created["source"] == PLATFORM_SOURCE
    assert created["is_active"] is True

    updated = await service.update(
        code=code,
        payload={k: v for k, v in _payload(code, clause_en="x has changed").items() if k != "code"},
        actor_user_id=None,
    )
    assert updated["clause_en"] == "x has changed"

    await service.deactivate(code=code, actor_user_id=None)
    active = {f["code"] for f in await service.list_platform(include_inactive=False)}
    retired = {f["code"] for f in await service.list_platform(include_inactive=True)}
    assert code not in active
    assert code in retired


@pytest.mark.asyncio
async def test_a_duplicate_platform_code_is_a_conflict(admin_session: AsyncSession) -> None:
    service = _platform_service(admin_session)
    code = f"p_{uuid4().hex[:8]}"
    await service.create(payload=_payload(code), actor_user_id=None)

    with pytest.raises(_FindingCodeAlreadyExistsError):
        await service.create(payload=_payload(code), actor_user_id=None)


@pytest.mark.asyncio
async def test_updating_an_absent_platform_code_is_not_found(
    admin_session: AsyncSession,
) -> None:
    service = _platform_service(admin_session)
    payload = {k: v for k, v in _payload("x").items() if k != "code"}

    with pytest.raises(_FindingNotFoundError):
        await service.update(code=f"missing_{uuid4().hex[:8]}", payload=payload, actor_user_id=None)


@pytest.mark.asyncio
async def test_deactivate_is_idempotent(admin_session: AsyncSession) -> None:
    """A second deactivate reports success and changes nothing.

    The repository's predicate is `AND is_active`, so the second call
    touches zero rows. That must not read as "no such code".
    """
    service = _platform_service(admin_session)
    code = f"p_{uuid4().hex[:8]}"
    await service.create(payload=_payload(code), actor_user_id=None)

    await service.deactivate(code=code, actor_user_id=None)
    await service.deactivate(code=code, actor_user_id=None)


# ---- Tenant writes, and the refusal ---------------------------------------


@pytest.mark.asyncio
async def test_a_tenant_writes_its_own_catalogue(admin_session: AsyncSession) -> None:
    service = await _tenant_service(admin_session)
    code = f"t_{uuid4().hex[:8]}"

    created = await service.create(payload=_payload(code), actor_user_id=None)
    assert created["source"] == TENANT_SOURCE
    assert created["shadowed"] is False

    listed = {f["code"]: f for f in await service.list_tenant(include_inactive=False)}
    assert code in listed
    assert listed[code]["source"] == TENANT_SOURCE


@pytest.mark.asyncio
async def test_a_tenant_may_not_update_a_platform_row(admin_session: AsyncSession) -> None:
    """The refusal this whole scope split exists for.

    403, not 404. `dry` is right there in the list the tenant just read, so
    reporting it as missing would send an author looking for a data problem
    that does not exist. The message names the tenant route instead.
    """
    service = await _tenant_service(admin_session)
    payload = {k: v for k, v in _payload("dry", clause_en="my own wording").items() if k != "code"}

    with pytest.raises(_PlatformFindingNotEditableError) as caught:
        await service.update(code="dry", payload=payload, actor_user_id=None)

    assert caught.value.code == "dry"
    assert "read-only" in str(caught.value)


@pytest.mark.asyncio
async def test_a_tenant_may_not_deactivate_a_platform_row(
    admin_session: AsyncSession,
) -> None:
    service = await _tenant_service(admin_session)

    with pytest.raises(_PlatformFindingNotEditableError):
        await service.deactivate(code="pest_high", actor_user_id=None)

    # And the platform row is untouched.
    platform = {
        f["code"]
        for f in await _platform_service(admin_session).list_platform(include_inactive=False)
    }
    assert "pest_high" in platform


@pytest.mark.asyncio
async def test_a_tenant_row_shadowed_by_a_platform_code_is_flagged(
    admin_session: AsyncSession,
) -> None:
    """Allowed to exist, marked, and never resolved.

    Refusing the write would be wrong: the platform can add a code
    tomorrow and shadow a row that was legal when it was written, so the
    same situation would still arise with no way to report it.
    """
    # Its own code rather than a seeded one, so this test does not depend
    # on running after `test_a_tenant_may_not_update_a_platform_row`: that
    # test needs the tenant NOT to hold a row for the code it names.
    code = f"s_{uuid4().hex[:8]}"
    await _platform_service(admin_session).create(
        payload=_payload(code, clause_en="the platform wording"), actor_user_id=None
    )

    service = await _tenant_service(admin_session)
    created = await service.create(
        payload=_payload(code, clause_en="the tenant's own wording"), actor_user_id=None
    )
    assert created["shadowed"] is True

    listed = {f["code"]: f for f in await service.list_tenant(include_inactive=False)}
    assert listed[code]["shadowed"] is True

    # The fold reads the platform clause, not this one.
    resolved = await service.resolved()
    assert resolved[code].source == PLATFORM_SOURCE
    assert resolved[code].clause_en == "the platform wording"


@pytest.mark.asyncio
async def test_resolved_merges_both_catalogues(admin_session: AsyncSession) -> None:
    service = await _tenant_service(admin_session)
    own = f"t_{uuid4().hex[:8]}"
    await service.create(payload=_payload(own), actor_user_id=None)

    resolved = await service.resolved()

    assert resolved[own].source == TENANT_SOURCE
    assert set(resolved) >= _SEEDED
    assert all(resolved[code].source == PLATFORM_SOURCE for code in _SEEDED)


@pytest.mark.asyncio
async def test_a_retired_code_drops_out_of_the_resolved_catalogue(
    admin_session: AsyncSession,
) -> None:
    service = await _tenant_service(admin_session)
    code = f"t_{uuid4().hex[:8]}"
    await service.create(payload=_payload(code), actor_user_id=None)
    assert code in await service.resolved()

    await service.deactivate(code=code, actor_user_id=None)

    assert code not in await service.resolved()
    # Still listed for the admin screen, which is what "retire, never
    # delete" is for: every card that carried the code still names it.
    retired = {f["code"] for f in await service.list_tenant(include_inactive=True)}
    assert code in retired


@pytest.mark.asyncio
async def test_a_tenant_row_does_not_reach_the_platform_catalogue(
    admin_session: AsyncSession,
) -> None:
    tenant = await _tenant_service(admin_session)
    code = f"t_{uuid4().hex[:8]}"
    await tenant.create(payload=_payload(code), actor_user_id=None)

    platform = await _platform_service(admin_session).list_platform(include_inactive=True)

    assert code not in {f["code"] for f in platform}
