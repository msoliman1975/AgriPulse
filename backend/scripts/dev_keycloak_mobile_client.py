"""Provision the `agripulse-mobile` Keycloak client (scout app, S-1).

The field app cannot use `agripulse-api`: that is a confidential client, and a
mobile binary cannot keep a secret. This creates the **public** client the
Android app signs in through.

    python -m scripts.dev_keycloak_mobile_client          # create / update
    python -m scripts.dev_keycloak_mobile_client --show   # print, change nothing

Shape, and why each part:

* **public + PKCE (S256).** A public client with no PKCE is an authorization-code
  interception waiting to happen on a device where any app can claim a custom
  scheme. `standardFlowEnabled` with PKCE required is the modern default.
* **`agripulse://auth/callback`.** A custom scheme, because the app is not a web
  page. The same scheme carries push deep links (`agripulse://scout/visits/…`).
* **Direct grant enabled.** Deliberate: sign-in is a phone number and a 6-digit
  PIN typed into a number pad, not a browser form. Pushing this persona through
  a Custom Tab to type a PIN into a web page is worse UX and worse for
  low-literacy users than owning the screen ourselves. PKCE stays enabled so the
  browser flow remains available.
* **`offline_access` in the default scopes.** A scout in a field with no signal
  must not be logged out. Offline tokens are the supported way to hold a
  ~90-day session **without** stretching realm SSO lifetimes, which would weaken
  every web session in the same realm.

Idempotent: re-running updates the existing client rather than 409-ing. Uses
PUT for updates, never POST — a POST against an existing client is the shape
that caused the admin-client secret drift incident.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

from app.core.settings import get_settings

CLIENT_ID = "agripulse-mobile"

# Kept in one place so the realm JSON and this script cannot drift apart.
CLIENT_DEFINITION: dict[str, Any] = {
    "clientId": CLIENT_ID,
    "name": "AgriPulse Scout (mobile)",
    "description": "Public PKCE client for the Android field-scouting app.",
    "enabled": True,
    "protocol": "openid-connect",
    # Public: a mobile binary cannot hold a secret.
    "publicClient": True,
    "standardFlowEnabled": True,
    # Phone + PIN on a number pad, not a browser form — see module docstring.
    "directAccessGrantsEnabled": True,
    "serviceAccountsEnabled": False,
    "implicitFlowEnabled": False,
    "redirectUris": ["agripulse://auth/callback", "agripulse://auth/logout"],
    # The app is a WebView, so its token request is a browser `fetch` and is
    # subject to CORS — the custom-scheme redirect URIs above do not exempt it.
    # Capacitor serves the bundle from `http://localhost` on Android (the config
    # pins androidScheme to http; the default https would make the dev api mixed
    # content), and `https://localhost` is what a release build against an https
    # api will use. Empty webOrigins meant Keycloak returned no
    # Access-Control-Allow-Origin and sign-in failed on the handset while every
    # server-side direct grant kept working — the two paths differ only here.
    "webOrigins": ["http://localhost", "https://localhost"],
    "attributes": {
        "pkce.code.challenge.method": "S256",
        # Refresh tokens are the session; without this an offline token is
        # useless after the first access token expires.
        "client_offline_session_idle_timeout": "7776000",  # 90 days
        "client_offline_session_max_lifespan": "7776000",
    },
    "defaultClientScopes": [
        # `basic` carries `sub` and `auth_time`. Keycloak 24+ moved them out
        # of the always-on set into this scope, so listing defaultClientScopes
        # without it produces a token with **no subject** — which the api's
        # context builder rejects outright. Found the hard way: sign-in
        # succeeded and every request would then have failed.
        "basic",
        "web-origins",
        "acr",
        "profile",
        "roles",
        "email",
        # The long field session.
        "offline_access",
    ],
    "optionalClientScopes": ["address", "phone", "microprofile-jwt"],
}


def _attribute_mapper(name: str, attr: str, claim: str, *, multivalued: bool) -> dict[str, Any]:
    return {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": attr,
            "claim.name": claim,
            "jsonType.label": "String",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
            "multivalued": "true" if multivalued else "false",
        },
    }


# Without these the scout signs in perfectly and is then 403 on every endpoint:
# the middleware builds its RequestContext from these claims, and a token that
# carries none of them is an authenticated user with no tenant and no farms.
#
# They are duplicated from `agripulse-api` rather than shared through a client
# scope, deliberately for now: moving the api client's mappers is a change to a
# working auth path, and this needs to be provable on its own first. If a third
# client ever needs them, promote all three to a shared scope in one go.
CLAIM_MAPPERS: list[dict[str, Any]] = [
    _attribute_mapper("tenant_id-mapper", "tenant_id", "tenant_id", multivalued=False),
    _attribute_mapper("tenant_role-mapper", "tenant_role", "tenant_role", multivalued=False),
    # Multivalued String: the middleware's `_iter_farm_scopes` json.loads each
    # item, which is why the existing String mapper works unchanged.
    _attribute_mapper("farm_scopes-mapper", "farm_scopes", "farm_scopes", multivalued=True),
    {
        # The api validates `audience=agripulse-api`. A token minted for the
        # mobile client carries azp=agripulse-mobile and would be rejected
        # outright without this.
        "name": "agripulse-api-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.client.audience": "agripulse-api",
            "id.token.claim": "false",
            "access.token.claim": "true",
        },
    },
]


def _admin_token(client: httpx.Client, settings: Any) -> str:
    resp = client.post(
        f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_admin_client_id,
            "client_secret": settings.keycloak_admin_client_secret,
        },
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def _find(client: httpx.Client, settings: Any, token: str) -> dict[str, Any] | None:
    resp = client.get(
        f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}/clients",
        headers={"Authorization": f"Bearer {token}"},
        params={"clientId": CLIENT_ID},
    )
    resp.raise_for_status()
    rows = resp.json()
    return dict(rows[0]) if rows else None


def _assign_default_scopes(
    client: httpx.Client, settings: Any, token: str, client_uuid: str
) -> list[str]:
    """Attach the default client scopes explicitly.

    Keycloak ignores ``defaultClientScopes`` on a client **update** — the field
    is honoured on create and then only ever changed through
    ``/default-client-scopes/{id}``. Setting it in the representation and
    assuming it stuck is how this client ended up issuing tokens with no
    ``sub``: `basic` (which carries sub + auth_time since KC 24) was listed but
    never actually assigned.
    """
    headers = {"Authorization": f"Bearer {token}"}
    base = f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}"
    available = {
        row["name"]: row["id"]
        for row in client.get(f"{base}/client-scopes", headers=headers).json()
    }
    assigned = {
        row["name"]
        for row in client.get(
            f"{base}/clients/{client_uuid}/default-client-scopes", headers=headers
        ).json()
    }
    added: list[str] = []
    for name in CLIENT_DEFINITION["defaultClientScopes"]:
        if name in assigned or name not in available:
            continue
        resp = client.put(
            f"{base}/clients/{client_uuid}/default-client-scopes/{available[name]}",
            headers=headers,
        )
        if resp.status_code in (204, 200):
            added.append(name)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the client, change nothing")
    args = parser.parse_args(argv)

    settings = get_settings()
    with httpx.Client(timeout=15.0) as http:
        token = _admin_token(http, settings)
        existing = _find(http, settings, token)

        if args.show:
            print(existing or f"{CLIENT_ID}: not provisioned")
            return 0

        headers = {"Authorization": f"Bearer {token}"}
        base = f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}/clients"
        if existing is None:
            resp = http.post(
                base, headers=headers, json={**CLIENT_DEFINITION, "protocolMappers": CLAIM_MAPPERS}
            )
            if resp.status_code not in (201, 409):
                print(f"create failed: {resp.status_code} {resp.text[:400]}", file=sys.stderr)
                return 1
            print(f"{CLIENT_ID}: created")
            existing = _find(http, settings, token)
        else:
            # PUT, not POST. Keycloak's PUT is a full replace, so the body must
            # carry the id — and a POST against an existing client is what
            # caused the admin-client secret drift incident.
            # Carry the existing mappers so a full-replace PUT does not strip
            # them, then add any that are missing by name.
            have = {m["name"] for m in existing.get("protocolMappers") or []}
            body = {
                **CLIENT_DEFINITION,
                "id": existing["id"],
                "protocolMappers": (existing.get("protocolMappers") or [])
                + [m for m in CLAIM_MAPPERS if m["name"] not in have],
            }
            resp = http.put(f"{base}/{existing['id']}", headers=headers, json=body)
            if resp.status_code not in (204, 200):
                print(f"update failed: {resp.status_code} {resp.text[:400]}", file=sys.stderr)
                return 1
            print(f"{CLIENT_ID}: updated")

            # Scope assignment is a separate endpoint — see _assign_default_scopes.
            target_id = (existing or _find(http, settings, token) or {}).get("id")
            if target_id:
                added = _assign_default_scopes(http, settings, token, str(target_id))
                if added:
                    print(f"  scopes assigned: {', '.join(added)}")

    print("\nApp config:")
    print(f"  issuer       {settings.keycloak_base_url}/realms/{settings.keycloak_realm}")
    print(f"  client_id    {CLIENT_ID}")
    print("  redirect     agripulse://auth/callback")
    print("  scopes       openid profile email offline_access")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
