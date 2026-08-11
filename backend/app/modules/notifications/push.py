"""Synchronous FCM send used by the notifications push channel.

Mirrors ``smtp.py``: the notifications subscriber runs in a sync handler, so a
synchronous client (``httpx.Client``) is the right fit. Sends are best-effort
with a hard timeout; failures bubble to the caller, which records them on the
``notification_dispatches`` row.

Two things are deliberate here.

**Data messages, not notification messages.** FCM's ``notification`` block is
rendered by the OS, which means the app cannot control presentation, cannot act
on a cold start, and cannot deep-link reliably. Sending ``data`` only puts the
app in charge — which is what the "I'll take it" action on the lock screen
needs.

**Delivery is never the source of truth.** FCM is best-effort and fails
silently on some OEM Android builds, so a dropped push must never mean lost
work: the visit list reconciles on every app open. This module's job is to
report honestly whether the send happened, not to guarantee it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

_log = get_logger(__name__)

# FCM's response for a token that no longer exists. The caller revokes the
# device row on this rather than retrying forever — an uninstalled app is a
# permanent condition, not a transient failure.
UNREGISTERED_ERRORS = frozenset({"UNREGISTERED", "NOT_FOUND", "INVALID_ARGUMENT"})


class PushSendError(RuntimeError):
    """Raised when FCM delivery fails. The caller stores the message on the
    dispatch row so an operator can read it later."""

    def __init__(self, detail: str, *, unregistered: bool = False) -> None:
        super().__init__(detail)
        # Distinguishes "this device is gone" from "the send failed". Only the
        # former should revoke the token.
        self.unregistered = unregistered


@dataclass(frozen=True)
class PushResult:
    sent: bool
    message_id: str | None = None
    # True when the channel is configured off — the dispatch row records
    # `skipped`, not `failed`, so a dev environment without FCM credentials
    # does not look like an outage.
    skipped: bool = False


# FCM v1 has no static API key: every send needs an OAuth2 bearer minted from
# the service account, and those expire after an hour. Holding one in an env
# var therefore works for exactly one hour after deploy and then 401s — which
# is why the credential is loaded once and refreshed on demand instead.
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_credentials: Any = None


def _bearer(settings: Any) -> str:
    """A live access token, refreshed when it is close to expiring.

    ``FCM_ACCESS_TOKEN`` still wins when set — it keeps a hand-minted token
    usable for a one-off test without a service-account file on disk.
    """
    static = getattr(settings, "fcm_access_token", "")
    if static:
        return str(static)

    key_file = getattr(settings, "fcm_service_account_file", "")
    key_json = getattr(settings, "fcm_service_account_json", "")
    if not key_file and not key_json:
        raise PushSendError(
            "FCM is enabled but none of FCM_SERVICE_ACCOUNT_JSON, "
            "FCM_SERVICE_ACCOUNT_FILE or FCM_ACCESS_TOKEN is set"
        )

    global _credentials
    if _credentials is None:
        from google.oauth2 import service_account  # imported lazily: dev has no key file

        # google-auth ships no type stubs, so mypy sees untyped calls here.
        if key_json:
            # Inline wins: a cluster that sets both is one that mounted a file
            # for a previous deploy and has since moved to env injection.
            try:
                info = json.loads(key_json)
            except ValueError as exc:
                raise PushSendError("FCM_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
            _credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                info, scopes=[_SCOPE]
            )
        else:
            _credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                key_file, scopes=[_SCOPE]
            )
    if not _credentials.valid or _credentials.expired:
        from google.auth.transport.requests import Request

        _credentials.refresh(Request())
    return str(_credentials.token)


def reset_fcm_credentials() -> None:
    """Drop the cached credential — for tests, and after a key rotation."""
    global _credentials
    _credentials = None


def send_push(
    *,
    token: str,
    title: str,
    body: str,
    data: dict[str, str],
) -> PushResult:
    """Deliver one data message to one device token."""
    settings = get_settings()
    if not getattr(settings, "fcm_enabled", False):
        _log.info("push_skipped_disabled", token_suffix=token[-8:])
        return PushResult(sent=False, skipped=True)

    project_id = getattr(settings, "fcm_project_id", "")
    if not project_id:
        raise PushSendError("FCM is enabled but FCM_PROJECT_ID is not set")
    access_token = _bearer(settings)

    # Title and body ride in `data` too: the app draws its own notification, so
    # it needs the text even though there is no `notification` block.
    payload: dict[str, Any] = {
        "message": {
            "token": token,
            "data": {**data, "title": title, "body": body},
            "android": {
                # `high` wakes the app for a data-only message; a scouting
                # deadline measured in hours does not survive being batched
                # into the next maintenance window.
                "priority": "high",
            },
        }
    }

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=getattr(settings, "fcm_timeout_seconds", 10.0),
        )
    except httpx.HTTPError as exc:  # network-level failure
        raise PushSendError(f"FCM request failed: {exc}") from exc

    if response.status_code == httpx.codes.OK:
        return PushResult(sent=True, message_id=str(response.json().get("name")))

    detail = response.text[:500]
    status_code = _fcm_error_status(response)
    if status_code in UNREGISTERED_ERRORS:
        # The app was uninstalled or the token was rotated. Permanent.
        raise PushSendError(f"device token is no longer valid: {status_code}", unregistered=True)
    raise PushSendError(f"FCM returned {response.status_code}: {detail}")


def _fcm_error_status(response: httpx.Response) -> str:
    """Pull FCM's machine-readable status out of an error body, tolerantly.

    A malformed error body must not mask the underlying failure, so anything
    unparseable degrades to an empty string and the caller treats it as a
    generic (retryable) error rather than revoking a device.
    """
    try:
        return str(response.json().get("error", {}).get("status", ""))
    except (ValueError, AttributeError):
        return ""
