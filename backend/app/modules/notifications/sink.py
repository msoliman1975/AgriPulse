"""Suppress outbound notifications for simulation tenants.

The org simulation harness (``docs/testing/org-simulation-harness.md``) runs a
throwaway tenant on production, beside real customers. Its personas open alerts
and recommendations like anyone else, and the fan-out would post real email and
real push notifications to whatever addresses the seed data carries. This
module is what stops that.

Per-tenant, never process-wide
------------------------------
A global kill switch would silence real customers' alerts for as long as a
simulation ran. The switch is therefore a **slug prefix**:
``settings.notification_sink_tenant_prefix``, empty by default and set to
``sim-`` in the environments that host simulation runs. A run provisions
``sim-<run_id>``, so one setting covers every future run with no per-run
configuration and no migration, and a real tenant cannot match a prefix that is
reserved by convention.

Fails open, deliberately
------------------------
With no prefix configured, or outside a handler that established the context,
nothing is suppressed and delivery proceeds normally. Suppressing by accident
would silence a real customer, which is worse than a simulation run leaking one
test email. Act 0 of a run verifies the sink is actually live by dispatching one
notification and asserting the row came back ``suppressed`` — the harness never
assumes it.

Two layers
----------
Call sites in :mod:`app.modules.notifications.subscribers` check
:func:`is_suppressed` *before* sending, so the ``notification_dispatches`` row
records ``suppressed`` rather than a delivery that never happened. That table is
the harness's oracle, so a row reading ``sent`` for a suppressed message would
be worse than useless.

The transports raise :class:`OutboundSuppressedError` as a backstop. A call site
added later that forgets the check cannot leak: it fails loudly, records the
error against the dispatch, and delivers nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import text

from app.core.settings import get_settings

F = TypeVar("F", bound=Callable[..., Any])

# Set for the duration of one subscriber invocation, which handles exactly one
# tenant. Default False so any code path that never established the context —
# including every non-simulation caller — delivers normally.
_suppressed: ContextVar[bool] = ContextVar("notification_outbound_suppressed", default=False)


# notification_dispatches.status is CHECK-constrained to
# ('pending','sent','failed','skipped'), so suppression reuses `skipped` and
# says why in `error` -- the same shape as "channel disabled by tenant" and
# "no registered devices". Inventing a `suppressed` status would need a tenant
# migration and would still mean the same thing. The harness greps this exact
# string, so it is a constant rather than a literal at six call sites.
SUPPRESSED_REASON = "outbound suppressed for simulation tenant"


class OutboundSuppressedError(RuntimeError):
    """A transport was reached while outbound delivery was suppressed.

    Raised only when a call site failed to check :func:`is_suppressed` first.
    Nothing was sent; the caller records it against the dispatch row, where it
    reads as a bug report rather than a delivery failure.
    """


def is_suppressed() -> bool:
    """Whether outbound delivery is suppressed for the tenant being handled."""
    return _suppressed.get()


def resolve_for_tenant(session: Any, tenant_id: UUID) -> bool:
    """Whether this tenant's outbound notifications must not leave the system.

    Answers False when no prefix is configured, which is every environment that
    does not host simulation runs.
    """
    prefix = getattr(get_settings(), "notification_sink_tenant_prefix", "") or ""
    if not prefix:
        return False
    slug = session.execute(
        text("SELECT slug FROM public.tenants WHERE id = :id"),
        {"id": tenant_id},
    ).scalar_one_or_none()
    return bool(slug) and str(slug).startswith(prefix)


@contextmanager
def outbound_for_tenant(session: Any, tenant_id: UUID) -> Iterator[bool]:
    """Establish the suppression context for one tenant, and yield its value."""
    suppressed = resolve_for_tenant(session, tenant_id)
    token = _suppressed.set(suppressed)
    try:
        yield suppressed
    finally:
        _suppressed.reset(token)


def activate_for_tenant(session: Any, tenant_id: UUID) -> bool:
    """Turn suppression on or off for the tenant now being handled.

    Only safe inside :func:`resets_outbound`, which guarantees the value is
    torn down again.
    """
    suppressed = resolve_for_tenant(session, tenant_id)
    _suppressed.set(suppressed)
    return suppressed


def resets_outbound(fn: F) -> F:
    """Guarantee the suppression flag does not outlive one handler call.

    The subscribers are sync handlers with many early returns, so the reset
    cannot rely on reaching the end of the function. Without it a simulation
    tenant's alert would leave the flag set on that thread and silence the
    *next* tenant's notifications — a real customer's, silently. Applied to a
    handler whose tenant never activates suppression, it is a no-op.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _suppressed.set(False)
        try:
            return fn(*args, **kwargs)
        finally:
            _suppressed.reset(token)

    return cast("F", wrapper)


__all__ = [
    "SUPPRESSED_REASON",
    "OutboundSuppressedError",
    "activate_for_tenant",
    "is_suppressed",
    "outbound_for_tenant",
    "resets_outbound",
    "resolve_for_tenant",
]
