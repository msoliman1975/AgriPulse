"""Configure realm-level SMTP on the local-dev Keycloak so it can
actually send the emails it tries to send (invites, password resets,
update-password actions for new platform admins, etc.).

The freshly-imported `agripulse` realm ships with `smtpServer = {}`,
which means every Keycloak email attempt silently no-ops. This script
PUTs the realm with `smtpServer` populated from the backend's own
Brevo SMTP env (SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD /
SMTP_STARTTLS / SMTP_FROM). Idempotent.

    python -m scripts.dev_keycloak_smtp                          # configure
    python -m scripts.dev_keycloak_smtp --send-test you@x.com    # ... and trigger a real
                                                                 #   UPDATE_PASSWORD invite
                                                                 #   email to that address

Production wires this through the Keycloak helm chart (CD-13). This
script is dev-only — it reuses the master/admin-cli token path that
`dev_bootstrap.py` uses, not the per-realm `agripulse-tenancy` admin
client.
"""

from __future__ import annotations

import argparse
import sys
from email.utils import parseaddr

import httpx

from app.core.settings import get_settings
from scripts.dev_bootstrap import (
    KEYCLOAK_BASE_URL,
    KEYCLOAK_REALM,
    kc_admin_token,
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_smtp_block() -> dict[str, str]:
    s = get_settings()
    if not s.smtp_host:
        raise SystemExit("SMTP_HOST is empty in settings; check backend/.env")
    if not s.smtp_username or not s.smtp_password:
        raise SystemExit(
            "SMTP_USERNAME / SMTP_PASSWORD must be set in backend/.env " "for Keycloak SMTP auth"
        )

    # SMTP_FROM is "Display Name <addr@host>" — Keycloak wants the parts split.
    display_name, from_addr = parseaddr(s.smtp_from)
    if not from_addr:
        raise SystemExit(f"Could not parse SMTP_FROM={s.smtp_from!r}")

    # Keycloak's realm smtpServer wants ALL values as strings, including
    # port and booleans. Submitting raw ints/bools breaks the admin UI later.
    return {
        "host": s.smtp_host,
        "port": str(s.smtp_port),
        "from": from_addr,
        "fromDisplayName": display_name or "AgriPulse",
        "replyTo": "",
        "replyToDisplayName": "",
        "envelopeFrom": "",
        "ssl": "false",  # STARTTLS, not implicit TLS, for Brevo on 587
        "starttls": "true" if s.smtp_starttls else "false",
        "auth": "true",
        "user": s.smtp_username,
        "password": s.smtp_password,
    }


def _get_realm(http: httpx.Client, token: str) -> dict:
    resp = http.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}",
        headers=_bearer(token),
    )
    resp.raise_for_status()
    return resp.json()


def _put_realm(http: httpx.Client, token: str, realm: dict) -> None:
    resp = http.put(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}",
        headers=_bearer(token),
        json=realm,
    )
    resp.raise_for_status()


def _send_real_invite(http: httpx.Client, token: str, recipient_email: str) -> None:
    """Trigger a real UPDATE_PASSWORD email to the given address.

    Note: we deliberately don't use Keycloak's `/testSMTPConnection`
    endpoint. In Keycloak 26 that endpoint fails ("Failed to send email")
    even when real sends succeed — likely because the test path doesn't
    re-resolve the stored masked password. `execute-actions-email` uses
    the actual stored realm config, so a 204 here confirms end-to-end
    delivery via the live Brevo SMTP.
    """
    # Look up by username, not email — the seeded dev user has username
    # set but no email (Keycloak 26 user-profile validator rejects the
    # `.local` TLD on import). Caller can pass any registered username
    # or an email of a user whose email field is populated.
    for key in ("username", "email"):
        resp = http.get(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users",
            params={key: recipient_email, "exact": "true"},
            headers=_bearer(token),
        )
        resp.raise_for_status()
        users = resp.json()
        if users:
            user_id = users[0]["id"]
            break
    else:
        raise SystemExit(f"user {recipient_email!r} not found in realm by username or email")

    # Make sure the user's email field is populated and verified, else
    # Keycloak will skip the send silently.
    user_obj = users[0]
    if not user_obj.get("email"):
        user_obj["email"] = recipient_email
        user_obj["emailVerified"] = True
        put = http.put(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
            headers=_bearer(token),
            json=user_obj,
        )
        put.raise_for_status()
        print(f"  patched email field on {recipient_email} (was empty)")

    resp = http.put(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}"
        "/execute-actions-email",
        headers={**_bearer(token), "Content-Type": "application/json"},
        json=["UPDATE_PASSWORD"],
    )
    if resp.status_code in (200, 204):
        print(f"  invite email sent to {recipient_email} (action: UPDATE_PASSWORD)")
        return
    raise SystemExit(
        f"execute-actions-email failed: HTTP {resp.status_code} body={resp.text[:300]}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-test",
        metavar="EMAIL",
        help=(
            "After configuring, trigger a real UPDATE_PASSWORD invite email "
            "to this address (must be a registered user's username or email). "
            "204 + an email in your inbox confirms the full pipeline works."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"Configuring SMTP on realm {KEYCLOAK_REALM!r} ({KEYCLOAK_BASE_URL})")
    print(f"  host:    {settings.smtp_host}:{settings.smtp_port}")
    print(f"  from:    {settings.smtp_from}")
    print(f"  user:    {settings.smtp_username}")
    print(f"  starttls: {settings.smtp_starttls}")

    smtp_block = _build_smtp_block()

    with httpx.Client(timeout=30.0) as http:
        token = kc_admin_token(http)
        realm = _get_realm(http, token)
        existing = realm.get("smtpServer") or {}
        already_matches = all(
            str(existing.get(k, "")) == str(smtp_block.get(k, ""))
            for k in ("host", "port", "from", "user", "starttls", "auth")
        )
        if already_matches and existing.get("password"):
            print("  smtpServer already matches settings (skipped PUT)")
        else:
            realm["smtpServer"] = smtp_block
            _put_realm(http, token, realm)
            print("  smtpServer updated on realm")

        if args.send_test:
            _send_real_invite(http, token, args.send_test)

    print("\nDone. Keycloak will now use Brevo for invite / reset / verify emails.")
    print("Tip: open http://localhost:8080 -> realm 'agripulse' -> Email settings to confirm.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:400] if exc.response is not None else ""
        print(f"\nKeycloak request failed: {exc} body={body}", file=sys.stderr)
        raise SystemExit(2) from exc
    except Exception as exc:
        print(f"\nfailed: {exc}", file=sys.stderr)
        raise
