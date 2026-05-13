"""Sync HMAC-signed webhook delivery.

The notifications subscriber calls ``send_webhook`` with the URL,
secret, and JSON-serialisable body. The function:

  * Serialises the body deterministically (``json.dumps`` with sorted
    keys) so the signature is stable across senders/runtimes.
  * Computes ``sha256=<hex>`` HMAC over the raw bytes.
  * POSTs with the headers a receiver needs to verify:
        X-AgriPulse-Event:     <event-name>
        X-AgriPulse-Delivery:  <dispatch_id>
        X-AgriPulse-Signature: sha256=<hex>
  * Treats any non-2xx response, network error, or timeout as a
    delivery failure (raised as ``WebhookSendError``).

Single attempt per call. Retries are deferred per the slice roadmap;
a separate Celery beat could later sweep failed dispatches.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


class WebhookSendError(RuntimeError):
    """Raised when a webhook POST fails (network, timeout, or non-2xx)."""


@dataclass(frozen=True, slots=True)
class WebhookResult:
    status_code: int
    response_snippet: str


def sign_body(*, secret: str, body: bytes) -> str:
    """``sha256=<hex>`` of the HMAC over ``body`` with ``secret``.

    Receivers verify by recomputing this on their side and using
    constant-time compare.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def send_webhook(
    *,
    url: str,
    secret: str,
    event_name: str,
    delivery_id: UUID,
    body: dict[str, Any],
    timeout_seconds: float = 5.0,
) -> WebhookResult:
    """POST a signed JSON body and return the response status.

    Raises ``WebhookSendError`` on any failure path: timeouts,
    DNS / connection errors, and non-2xx responses are all surfaced
    the same way so the caller stores a single ``status='failed'``
    row with a useful message.
    """
    serialised = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    signature = sign_body(secret=secret, body=serialised)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "AgriPulse-Webhooks/1.0",
        "X-AgriPulse-Event": event_name,
        "X-AgriPulse-Delivery": str(delivery_id),
        "X-AgriPulse-Signature": signature,
    }
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(url, content=serialised, headers=headers)
    except httpx.HTTPError as exc:
        raise WebhookSendError(f"transport error: {exc}") from exc

    snippet = resp.text[:500] if resp.text else ""
    if resp.is_success:
        return WebhookResult(status_code=resp.status_code, response_snippet=snippet)
    raise WebhookSendError(f"non-2xx response {resp.status_code}: {snippet[:200]}")
