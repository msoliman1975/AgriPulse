"""The Scout client exists in two places, and they have to agree.

`dev_keycloak_mobile_client.py` builds it on a dev realm, and the Helm realm
file carries it for a fresh production realm. A difference would only show up
the day a realm is rebuilt, as scouts who cannot sign in.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.dev_keycloak_mobile_client import CLAIM_MAPPERS, CLIENT_DEFINITION

REALM_FILE = Path(__file__).parents[3] / "infra/helm/keycloak/files/agripulse-realm.json"


def _mobile_client() -> dict:
    realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    return next(c for c in realm["clients"] if c["clientId"] == "agripulse-mobile")


def test_realm_file_carries_the_scout_client_as_the_script_defines_it() -> None:
    client = _mobile_client()
    for key, value in CLIENT_DEFINITION.items():
        assert client[key] == value, key


def test_realm_file_carries_the_claims_a_scout_token_needs() -> None:
    assert _mobile_client()["protocolMappers"] == CLAIM_MAPPERS


def test_the_scout_client_cannot_hold_a_secret() -> None:
    client = _mobile_client()
    assert client["publicClient"] is True
    assert "secret" not in client
