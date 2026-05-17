"""One-shot: enable unmanaged attributes on the agripulse realm, set
`platform_role=PlatformAdmin` on the dev user, and add the matching
oidc-usermodel-attribute-mapper on the agripulse-api client.

Run inside the api pod (it ships the scripts/dev_bootstrap module and
has cluster-local DNS for the keycloak service).
"""
import os
import httpx

os.environ["KEYCLOAK_BASE_URL"] = "http://keycloak-dev"
os.environ["KEYCLOAK_REALM"] = "agripulse"
os.environ["KEYCLOAK_ADMIN"] = "user"
os.environ["KEYCLOAK_PASSWORD"] = "admin"

from scripts.dev_bootstrap import (  # noqa: E402
    kc_admin_token,
    kc_enable_unmanaged_attributes,
    kc_get_user,
    kc_set_user_attributes,
    kc_get_client_uuid,
    kc_existing_mappers,
    kc_add_attribute_mapper,
)

with httpx.Client(timeout=30.0) as client:
    token = kc_admin_token(client)
    print("got admin token")

    kc_enable_unmanaged_attributes(client, token)
    print("realm: unmanagedAttributePolicy=ENABLED")

    user = kc_get_user(client, token, "dev@agripulse.local")
    if user is None:
        raise SystemExit("user dev@agripulse.local not found in realm")
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
