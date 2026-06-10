"""One-shot: enable unmanaged attributes on the agripulse realm, ensure
the bootstrap PlatformAdmin user exists with `platform_role=PlatformAdmin`,
and add the matching oidc-usermodel-attribute-mapper on the agripulse-api
client.

Run inside the api pod (it ships the scripts/dev_bootstrap module and
has cluster-local DNS for the keycloak service).

Bootstrap-admin resolution (IH-1 — the realm JSON no longer ships a
hard-coded `dev/dev` user for deployed clusters):

  * KC_BOOTSTRAP_ADMIN_EMAIL    — who to promote (default
                                  `dev@agripulse.local`).
  * KC_BOOTSTRAP_ADMIN_PASSWORD — if the user is missing, create them
                                  with this password. Empty + missing
                                  user => fail loudly (we will not invent
                                  a credential).
  * KC_BOOTSTRAP_ADMIN_NAME     — full name for a freshly-created user.
  * KC_BOOTSTRAP_ADMIN_TEMPORARY — "true" (default) marks the password
                                  temporary so the admin must reset it on
                                  first login.

On a cluster whose realm was imported before IH-1 (the dev user already
exists) the lookup just finds them and no password is needed. The local
docker-compose dev realm still seeds `dev/dev`, so the same default
resolves there too.
"""
import os
import httpx

# Use setdefault so an outer caller (e.g. the keycloak chart's PostSync
# Job in BH-2) can inject the real admin password from SM via env_from
# without us silently overriding it back to the dev fallback.
os.environ.setdefault("KEYCLOAK_BASE_URL", "http://keycloak-dev")
os.environ.setdefault("KEYCLOAK_REALM", "agripulse")
os.environ.setdefault("KEYCLOAK_ADMIN", "user")
os.environ.setdefault("KEYCLOAK_PASSWORD", "admin")

from scripts.dev_bootstrap import (  # noqa: E402
    kc_admin_token,
    kc_create_user,
    kc_enable_unmanaged_attributes,
    kc_get_user,
    kc_set_user_attributes,
    kc_get_client_uuid,
    kc_existing_mappers,
    kc_add_attribute_mapper,
)

BOOTSTRAP_EMAIL = os.environ.get("KC_BOOTSTRAP_ADMIN_EMAIL", "dev@agripulse.local")
BOOTSTRAP_PASSWORD = os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "")
BOOTSTRAP_NAME = os.environ.get("KC_BOOTSTRAP_ADMIN_NAME", "Platform Admin")
BOOTSTRAP_TEMPORARY = os.environ.get("KC_BOOTSTRAP_ADMIN_TEMPORARY", "true").lower() != "false"

with httpx.Client(timeout=30.0) as client:
    token = kc_admin_token(client)
    print("got admin token")

    kc_enable_unmanaged_attributes(client, token)
    print("realm: unmanagedAttributePolicy=ENABLED")

    user = kc_get_user(client, token, BOOTSTRAP_EMAIL)
    if user is None:
        if not BOOTSTRAP_PASSWORD:
            raise SystemExit(
                f"bootstrap admin {BOOTSTRAP_EMAIL!r} not found in realm and "
                "KC_BOOTSTRAP_ADMIN_PASSWORD is empty — set it (from a Secret) "
                "so the promote job can create the first PlatformAdmin."
            )
        user = kc_create_user(
            client,
            token,
            email=BOOTSTRAP_EMAIL,
            password=BOOTSTRAP_PASSWORD,
            full_name=BOOTSTRAP_NAME,
            temporary=BOOTSTRAP_TEMPORARY,
        )
        print(f"created bootstrap admin {BOOTSTRAP_EMAIL} (temporary={BOOTSTRAP_TEMPORARY})")
    print(f"user: {user['id']}")

    kc_set_user_attributes(
        client, token, user["id"], {"platform_role": ["PlatformAdmin"]}
    )
    print("user attr: platform_role=PlatformAdmin")

    cid = kc_get_client_uuid(client, token)
    print(f"client uuid: {cid}")

    existing = kc_existing_mappers(client, token, cid)
    if "platform_role-mapper" in existing:
        print("mapper platform_role-mapper already exists, skip")
    else:
        kc_add_attribute_mapper(
            client,
            token,
            cid,
            name="platform_role-mapper",
            user_attribute="platform_role",
            claim_name="platform_role",
        )
        print("added mapper platform_role-mapper")

print("DONE")
