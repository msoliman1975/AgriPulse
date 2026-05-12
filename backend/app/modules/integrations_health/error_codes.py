"""Shared error classifier for the integration-health attempt logs.

Both weather and imagery pipelines run a classifier on every caught
exception before persisting it to `weather_ingestion_attempts` /
`imagery_ingestion_jobs`. The classifier produces a coarse, stable
short code (`tls_trust`, `timeout`, `http_4xx`, …) that the Runs tab
filters and groups on, while the original exception string lives in
`error_message` for forensic detail.

Why coarse: the UI filter dropdown can only stay useful with a small
fixed vocabulary. Provider error strings vary wildly (HTML pages,
asyncpg traceback fragments, JSON bodies); a free-text classifier
defeats grouping.

Mirrors the original `_classify_error` from `weather/tasks.py` — that
local function should be replaced by importing this module, but the
weather caller already uses a slightly older shape so we keep it
backward-compatible by re-exporting the same name.
"""

from __future__ import annotations

# Short-circuit signal strings checked in order. The order matters for
# overlap cases (e.g. an HTML error page mentioning "404" inside an SSL
# trust failure body — the `tls` check sits ahead of the http-status
# check on purpose).
_TLS_TRUST_MARKERS: tuple[str, ...] = (
    "certificate_verify_failed",
    "self-signed certificate",
    "unable to get local issuer",
    "tls",
)


def classify_error(exc: BaseException) -> str:
    """Categorize a caught exception into a short, stable error code.

    Returns one of:
      - 'tls_trust'        — TLS handshake / cert chain failed locally
      - 'timeout'          — request exceeded its timeout budget
      - 'connection_error' — TCP-level failure, DNS, refused, reset
      - 'http_4xx'         — provider returned a client-error status
      - 'http_5xx'         — provider returned a server-error status
      - 'parse_error'      — non-JSON / unexpected shape in a successful response
      - 'provider_error'   — fallback when nothing else matches
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if any(marker in msg for marker in _TLS_TRUST_MARKERS):
        return "tls_trust"
    if "timeout" in name or "timeout" in msg:
        return "timeout"
    if "connect" in name or "connect" in msg or "dns" in msg:
        return "connection_error"
    if any(s in msg for s in ("400", "401", "403", "404", "422")):
        return "http_4xx"
    if any(s in msg for s in ("500", "502", "503", "504")):
        return "http_5xx"
    if "json" in msg or "decode" in msg or "parse" in msg:
        return "parse_error"
    return "provider_error"
