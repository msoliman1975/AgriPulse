"""Keep the realm's sign-in lockout at the numbers scouts are protected by.

A scout's credential is six digits, and the phone number that goes with it can
be guessed, so the lockout is the real protection. A realm that already exists
never re-reads agripulse-realm.json, which makes this hook the only path to the
live realm. Values match that file; change them together.

Self-contained on purpose (httpx only), so it runs whatever api image the hook
is pinned to. Idempotent. Touches these fields and nothing else.
"""
import os

import httpx

KC_BASE = os.environ.get("KEYCLOAK_BASE_URL", "http://keycloak-dev").rstrip("/")
REALM = os.environ.get("KEYCLOAK_REALM", "agripulse")
ADMIN = os.environ.get("KEYCLOAK_ADMIN", "user")
PASSWORD = os.environ.get("KEYCLOAK_PASSWORD", "admin")

# Ten wrong PINs locks the account for five minutes, growing with each further
# round to an hour. The count clears after a day with no failures. Temporary
# rather than permanent, because a permanent lock would let anyone take a scout
# off the app just by typing their number. A New PIN lifts it straight away.
LOCKOUT = {
    "bruteForceProtected": True,
    "permanentLockout": False,
    "failureFactor": 10,
    "waitIncrementSeconds": 300,
    "maxFailureWaitSeconds": 3600,
    "maxDeltaTimeSeconds": 86400,
    "quickLoginCheckMilliSeconds": 1000,
    "minimumQuickLoginWaitSeconds": 60,
}

with httpx.Client(timeout=30.0) as client:
    token = client.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN,
            "password": PASSWORD,
        },
    )
    token.raise_for_status()
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

    url = f"{KC_BASE}/admin/realms/{REALM}"
    current = client.get(url, headers=headers)
    current.raise_for_status()
    realm = current.json()

    changed = {k: v for k, v in LOCKOUT.items() if realm.get(k) != v}
    if not changed:
        print("realm: lockout already set")
    else:
        # The whole representation back, so nothing else can be blanked.
        realm.update(changed)
        client.put(url, headers=headers, json=realm).raise_for_status()
        print(f"realm: lockout updated: {sorted(changed)}")
