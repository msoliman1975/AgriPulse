"""Cloudflare Turnstile verification for the public trial form.

The marketing site is already on Cloudflare, so the widget needs no
third-party script and the check is one POST.

With no secret configured the check passes and logs that it did. A dev
stack and the test suite run that way; a cluster environment must set
`TURNSTILE_SECRET_KEY`, and § 8 of the trial design says so.
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

_log = get_logger(__name__)


async def verify_token(*, token: str | None, remote_ip: str | None) -> bool:
    """True when the visitor passed the challenge.

    A Cloudflare outage returns False rather than True: the form is a
    write path open to anyone, so an unverifiable challenge is not a
    passed challenge. The visitor sees "try again", which is recoverable.
    """
    settings = get_settings()
    if not settings.turnstile_secret_key:
        _log.info("turnstile_disabled")
        return True

    if not token:
        return False

    payload = {"secret": settings.turnstile_secret_key, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=settings.turnstile_timeout_seconds) as client:
            response = await client.post(settings.turnstile_verify_url, data=payload)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        _log.warning("turnstile_unavailable", error=str(exc))
        return False

    success = bool(body.get("success"))
    if not success:
        _log.info("turnstile_rejected", codes=body.get("error-codes"))
    return success
