"""Promote a Keycloak user to PlatformAdmin for local dev.

`dev_bootstrap.py` only wires `tenant_id` + `tenant_role` claim mappers,
which is enough for tenant-scoped roles. The admin portal needs
`platform_role` in the access token — this script sets the attribute on
the user and adds the missing protocol mapper. Idempotent.

    python -m scripts.dev_promote_platform_admin
    python -m scripts.dev_promote_platform_admin --user-email someone@local

Sign out + back in afterwards so the new claim lands in the token.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

from scripts.dev_bootstrap import (
    CLIENT_ID,
    KEYCLOAK_BASE_URL,
    KEYCLOAK_REALM,
    kc_add_attribute_mapper,
    kc_admin_token,
    kc_existing_mappers,
    kc_get_client_uuid,
    kc_get_user,
    kc_set_user_attributes,
)

DEFAULT_USER = os.getenv("DEV_USER_EMAIL", "dev@missionagre.local")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", default=DEFAULT_USER)
    parser.add_argument(
        "--platform-role",
        default="PlatformAdmin",
        choices=("PlatformAdmin", "PlatformSupport"),
    )
    args = parser.parse_args()

    print(f"Promoting {args.user_email} -> platform_role={args.platform_role}")
    print(f"  realm:  {KEYCLOAK_REALM} ({KEYCLOAK_BASE_URL})")

    with httpx.Client(timeout=30.0) as client:
        token = kc_admin_token(client)
        user = kc_get_user(client, token, args.user_email)
        if user is None:
            print(
                f"  user not found in realm — run dev_bootstrap.py first",
                file=sys.stderr,
            )
            raise SystemExit(2)

        kc_set_user_attributes(
            client,
            token,
            user["id"],
            {"platform_role": [args.platform_role]},
        )
        print(f"  set user attribute platform_role={args.platform_role}")

        client_uuid = kc_get_client_uuid(client, token)
        if "platform_role-mapper" not in kc_existing_mappers(client, token, client_uuid):
            kc_add_attribute_mapper(
                client,
                token,
                client_uuid,
                name="platform_role-mapper",
                user_attribute="platform_role",
                claim_name="platform_role",
            )
            print(f"  added protocol mapper platform_role-mapper on {CLIENT_ID}")
        else:
            print(f"  protocol mapper platform_role-mapper already present (skipped)")

    print(
        "\nDone. Sign out fully (user menu -> sign out), then sign back in. "
        "The new platform_role claim will be in your access token."
    )


if __name__ == "__main__":
    main()
