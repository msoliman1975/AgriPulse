"""Set up Keycloak for tenant provisioning:

  1. Create / upsert the `agripulse-tenancy` service-account client
     (confidential, client_credentials grant, secret from SM).
  2. Grant its service-account the `realm-management` roles needed by
     the api's KeycloakAdminClient: manage-users, manage-clients,
     query-groups, query-users, view-clients, view-realm.
  3. Configure the realm's smtpServer with the Brevo credentials so
     KC's execute-actions-email actually delivers.

Run inside the api pod (it has httpx + cluster DNS to keycloak-dev).
"""
import os
import sys
import httpx

KC_BASE = "http://keycloak-dev"
REALM = "agripulse"
TENANCY_CLIENT_ID = "agripulse-tenancy"

# Filled by caller via env vars to avoid baking secrets into the file.
TENANCY_SECRET = os.environ["TENANCY_CLIENT_SECRET"]
BREVO_HOST = os.environ.get("BREVO_HOST", "smtp-relay.brevo.com")
BREVO_PORT = os.environ.get("BREVO_PORT", "587")
BREVO_LOGIN = os.environ["BREVO_LOGIN"]
BREVO_PASSWORD = os.environ["BREVO_PASSWORD"]
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "admin@agripulse.tech")
BREVO_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "AgriPulse")

KC_ADMIN = os.environ.get("KC_ADMIN", "user")
KC_ADMIN_PW = os.environ.get("KC_ADMIN_PW", "admin")


def admin_token(c: httpx.Client) -> str:
    r = c.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": KC_ADMIN,
            "password": KC_ADMIN_PW,
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def upsert_tenancy_client(c: httpx.Client, token: str) -> str:
    """Returns the client UUID."""
    h = {"Authorization": f"Bearer {token}"}
    # Lookup
    r = c.get(
        f"{KC_BASE}/admin/realms/{REALM}/clients",
        headers=h,
        params={"clientId": TENANCY_CLIENT_ID},
    )
    r.raise_for_status()
    matches = r.json()
    body = {
        "clientId": TENANCY_CLIENT_ID,
        "name": "AgriPulse Tenancy (admin)",
        "description": "Service-account client used by the api to provision Keycloak groups + users when a tenant is created.",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True,
        "secret": TENANCY_SECRET,
        "attributes": {"client.secret.creation.time": "0"},
    }
    if matches:
        uuid = matches[0]["id"]
        # Force a PUT with the desired state. KC merges; we want a full replace
        # of the bits we care about, so we send our body verbatim.
        existing = matches[0]
        existing.update(body)
        r = c.put(
            f"{KC_BASE}/admin/realms/{REALM}/clients/{uuid}",
            headers=h,
            json=existing,
        )
        r.raise_for_status()
        # Reset secret explicitly so it matches the SM value.
        r = c.put(
            f"{KC_BASE}/admin/realms/{REALM}/clients/{uuid}/client-secret",
            headers=h,
        )
        r.raise_for_status()
        # KC just generated a new random one — restore ours.
        r = c.post(
            f"{KC_BASE}/admin/realms/{REALM}/clients/{uuid}/client-secret",
            headers=h,
            json={"type": "secret", "value": TENANCY_SECRET},
        )
        # POST may 404 in some KC versions; fall back to PUT with rep
        if r.status_code in (404, 405):
            rep = c.get(
                f"{KC_BASE}/admin/realms/{REALM}/clients/{uuid}", headers=h
            ).json()
            rep["secret"] = TENANCY_SECRET
            r2 = c.put(
                f"{KC_BASE}/admin/realms/{REALM}/clients/{uuid}",
                headers=h,
                json=rep,
            )
            r2.raise_for_status()
        print(f"updated client {TENANCY_CLIENT_ID} (uuid={uuid})")
        return uuid
    # Create
    r = c.post(f"{KC_BASE}/admin/realms/{REALM}/clients", headers=h, json=body)
    r.raise_for_status()
    location = r.headers["Location"]
    uuid = location.rsplit("/", 1)[-1]
    print(f"created client {TENANCY_CLIENT_ID} (uuid={uuid})")
    return uuid


def grant_realm_mgmt_roles(c: httpx.Client, token: str, client_uuid: str) -> None:
    """Give the service account the realm-management roles the api needs."""
    h = {"Authorization": f"Bearer {token}"}
    # Look up service-account user
    r = c.get(
        f"{KC_BASE}/admin/realms/{REALM}/clients/{client_uuid}/service-account-user",
        headers=h,
    )
    r.raise_for_status()
    sa_user_id = r.json()["id"]
    print(f"service account user: {sa_user_id}")

    # Look up realm-management client uuid
    r = c.get(
        f"{KC_BASE}/admin/realms/{REALM}/clients",
        headers=h,
        params={"clientId": "realm-management"},
    )
    r.raise_for_status()
    rm_uuid = r.json()[0]["id"]

    # Fetch all available realm-management client roles
    r = c.get(
        f"{KC_BASE}/admin/realms/{REALM}/clients/{rm_uuid}/roles", headers=h
    )
    r.raise_for_status()
    by_name = {role["name"]: role for role in r.json()}

    desired_role_names = [
        "manage-users",
        "manage-clients",
        "manage-realm",
        "query-users",
        "query-groups",
        "query-clients",
        "view-clients",
        "view-realm",
        "view-users",
    ]
    chosen = [by_name[n] for n in desired_role_names if n in by_name]
    missing = [n for n in desired_role_names if n not in by_name]
    if missing:
        print(f"WARN: missing realm-management roles: {missing}", file=sys.stderr)

    r = c.post(
        f"{KC_BASE}/admin/realms/{REALM}/users/{sa_user_id}/role-mappings/clients/{rm_uuid}",
        headers=h,
        json=chosen,
    )
    r.raise_for_status()
    print(f"granted {len(chosen)} realm-management roles to service account")


def configure_smtp(c: httpx.Client, token: str) -> None:
    h = {"Authorization": f"Bearer {token}"}
    r = c.get(f"{KC_BASE}/admin/realms/{REALM}", headers=h)
    r.raise_for_status()
    realm = r.json()
    realm["smtpServer"] = {
        "host": BREVO_HOST,
        "port": BREVO_PORT,
        "auth": "true",
        "user": BREVO_LOGIN,
        "password": BREVO_PASSWORD,
        "starttls": "true",
        "ssl": "false",
        "from": BREVO_FROM_EMAIL,
        "fromDisplayName": BREVO_FROM_NAME,
    }
    r = c.put(f"{KC_BASE}/admin/realms/{REALM}", headers=h, json=realm)
    r.raise_for_status()
    print(f"realm smtpServer set: {BREVO_HOST}:{BREVO_PORT} from={BREVO_FROM_EMAIL}")


def main() -> None:
    with httpx.Client(timeout=30.0) as c:
        tok = admin_token(c)
        print("got admin token")
        uuid = upsert_tenancy_client(c, tok)
        grant_realm_mgmt_roles(c, tok, uuid)
        configure_smtp(c, tok)
    print("DONE")


if __name__ == "__main__":
    main()
