"""Add the missing tenant_id + tenant_role + farm_scopes attribute
mappers to the `agripulse-api` client so attributes set on KC users
(by invite_user / add_existing_user_to_group) actually project into
the JWT and the api middleware sees them.

Idempotent — skips any mapper that already exists by name.
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
    kc_get_client_uuid,
    kc_existing_mappers,
    kc_add_attribute_mapper,
)

WANTED = [
    # (mapper name, user attribute, JWT claim, jsonType, multivalued)
    ("tenant_id-mapper", "tenant_id", "tenant_id", "String", False),
    ("tenant_role-mapper", "tenant_role", "tenant_role", "String", False),
    ("farm_scopes-mapper", "farm_scopes", "farm_scopes", "String", True),
]

with httpx.Client(timeout=30.0) as c:
    tok = kc_admin_token(c)
    cid = kc_get_client_uuid(c, tok)
    existing = kc_existing_mappers(c, tok, cid)
    print(f"client uuid: {cid}")
    print(f"existing mappers: {sorted(existing)}")
    for name, attr, claim, jtype, multi in WANTED:
        if name in existing:
            print(f"  skip (exists): {name}")
            continue
        kc_add_attribute_mapper(
            c, tok, cid,
            name=name,
            user_attribute=attr,
            claim_name=claim,
            json_type=jtype,
            multivalued=multi,
        )
        print(f"  added: {name} ({attr} -> {claim})")
print("DONE")
