"""Farm-scope JWT round-trip: the write format (Keycloak `farm_scopes`
attribute) must parse back through the auth-middleware read-side.

Regression guard for SMK-RBAC-BUG-01 — farm-scoped users 403'd on every
farm endpoint because the `farm_scopes` claim never reached the JWT and the
middleware only accepted dict items (never the String-mapper's JSON strings).
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.shared.auth.context import FarmRole, FarmScope
from app.shared.auth.middleware import _iter_farm_scopes
from app.shared.keycloak.fakes import FakeKeycloakClient, FakeUser

FARM_A = "019ecd33-96ce-7eaa-8654-1772c1554200"
FARM_B = "019ecd34-635c-7f8b-a3eb-9e438bcdfefc"


def test_iter_farm_scopes_parses_json_string_items() -> None:
    """The `farm_scopes-mapper` is a multivalued String mapper, so each scope
    arrives as a JSON object *string* — these must parse into FarmScopes."""
    claim = [
        json.dumps({"farm_id": FARM_A, "role": "FarmManager"}),
        json.dumps({"farm_id": FARM_B, "role": "Viewer"}),
    ]
    scopes = list(_iter_farm_scopes(claim))
    assert scopes == [
        FarmScope(farm_id=UUID(FARM_A), role=FarmRole.FARM_MANAGER),
        FarmScope(farm_id=UUID(FARM_B), role=FarmRole.VIEWER),
    ]


def test_iter_farm_scopes_still_accepts_dict_items() -> None:
    """Back-compat: already-decoded dict items keep working."""
    claim = [{"farm_id": FARM_A, "role": "Viewer"}]
    assert list(_iter_farm_scopes(claim)) == [FarmScope(farm_id=UUID(FARM_A), role=FarmRole.VIEWER)]


def test_iter_farm_scopes_skips_garbage() -> None:
    claim = ["not-json", "{}", json.dumps({"farm_id": FARM_A, "role": "NopeRole"}), 42]
    assert list(_iter_farm_scopes(claim)) == []


@pytest.mark.anyio
async def test_set_farm_scopes_write_round_trips_through_reader() -> None:
    """End-to-end format contract: what set_farm_scopes stores on the KC user
    must parse back through the middleware reader into the same scopes."""
    kc = FakeKeycloakClient()
    kc.users["u1"] = FakeUser(id="u1", email="a@b.c", full_name="A")
    scopes_in = [
        {"farm_id": FARM_A, "role": "Agronomist"},
        {"farm_id": FARM_B, "role": "Scout"},
    ]
    await kc.set_farm_scopes(keycloak_user_id="u1", scopes=scopes_in)

    # The real client stores each scope as a JSON string in the attribute;
    # emulate the mapper emitting them and read them back.
    claim = [json.dumps(s) for s in kc.users["u1"].farm_scopes]
    parsed = list(_iter_farm_scopes(claim))
    assert parsed == [
        FarmScope(farm_id=UUID(FARM_A), role=FarmRole.AGRONOMIST),
        FarmScope(farm_id=UUID(FARM_B), role=FarmRole.SCOUT),
    ]


@pytest.mark.anyio
async def test_set_farm_scopes_empty_clears() -> None:
    kc = FakeKeycloakClient()
    kc.users["u1"] = FakeUser(id="u1", email="a@b.c", full_name="A")
    await kc.set_farm_scopes(keycloak_user_id="u1", scopes=[])
    assert kc.users["u1"].farm_scopes == ()
