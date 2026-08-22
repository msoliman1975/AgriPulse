"""A person's own notification preferences: which channels, and which language.

Two columns on ``public.user_preferences`` decide what reaches someone when an
alert or a recommendation opens, and until now nothing in the product could
change either of them:

* ``notification_channels`` — the array the fan-out intersects with the
  tenant's own enabled channels before it sends anything.
* ``language`` — read *only* by the notification fan-out, at
  ``subscribers.py`` lines 187 and 1669, to pick the template locale. No other
  code in the backend reads it, which is why it belongs on this screen rather
  than with the interface-language toggle in the shell.

Two shapes of truth are kept apart here, because collapsing them is what makes
a preferences screen lie:

* what the person **chose** — the stored array, returned as ``channels``;
* what can actually **reach them** — a tenant may have the channel switched
  off, an account may carry no email address, a person may have no phone
  signed in. That is ``availability``, and the screen shows it next to the
  toggle so "I ticked email and got nothing" has an answer on the page.

A person may switch every channel off. That is a real choice and it is
honoured. Nothing is lost by it: alerts and recommendations still open in the
Action Center, which reads its own tables and not the inbox.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The per-user channels, in the order the screen shows them. `webhook` is
# deliberately absent: it is one URL per tenant, configured in Settings, and
# has no per-person meaning. The fan-out agrees — see `_PER_USER_CHANNELS`
# in notifications/subscribers.py.
USER_CHANNELS: tuple[str, ...] = ("in_app", "email", "push")

# What the fan-out falls back to when a row or a column is missing. These
# must stay equal to the COALESCE defaults in
# notifications/subscribers.py::_load_recipients and _load_tenant_channels,
# or the screen shows one thing and the sender does another.
DEFAULT_USER_CHANNELS: tuple[str, ...] = ("in_app", "email")
DEFAULT_TENANT_CHANNELS: tuple[str, ...] = ("in_app", "email")
DEFAULT_LANGUAGE = "en"

# Machine-readable reasons a channel cannot deliver. The frontend owns the
# wording; the API owns the fact.
REASON_TENANT_DISABLED = "tenant_disabled"
REASON_NO_EMAIL = "no_email_address"
REASON_NO_DEVICE = "no_registered_device"


class UnknownChannelError(ValueError):
    """Raised when the caller asks for a channel that is not per-user."""

    def __init__(self, unknown: list[str]) -> None:
        super().__init__(f"unknown notification channels: {unknown}")
        self.unknown = unknown


def normalise_channels(channels: list[str]) -> list[str]:
    """Validate, de-duplicate, and put the channels in display order.

    Order matters because the stored array is echoed straight back to the
    screen; without this, a round-trip would reshuffle the toggles.
    """
    unknown = sorted({c for c in channels if c not in USER_CHANNELS})
    if unknown:
        raise UnknownChannelError(unknown)
    chosen = set(channels)
    return [c for c in USER_CHANNELS if c in chosen]


async def _tenant_channels(session: AsyncSession, tenant_id: UUID) -> list[str]:
    row = (
        await session.execute(
            text(
                "SELECT alert_notification_channels FROM public.tenant_settings "
                "WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or row.alert_notification_channels is None:
        return list(DEFAULT_TENANT_CHANNELS)
    return list(row.alert_notification_channels)


async def _live_device_count(tenant_session: AsyncSession, user_id: UUID) -> int:
    """How many handsets this person could receive a push on.

    A revoked token is a phone that signed out. Counting it would let the
    screen promise a push that goes nowhere.
    """
    count = (
        await tenant_session.execute(
            text(
                "SELECT count(*) FROM device_tokens " "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        )
    ).scalar_one()
    return int(count)


async def _read_row(session: AsyncSession, user_id: UUID) -> tuple[list[str], str]:
    """The person's stored choice, or the fan-out's own defaults.

    Six of the eleven users on production have no preferences row at all, so
    "no row" is the common case and not an error. The values returned here
    are exactly what the fan-out would COALESCE to.
    """
    row = (
        await session.execute(
            text(
                "SELECT language, notification_channels FROM public.user_preferences "
                "WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is None:
        return list(DEFAULT_USER_CHANNELS), DEFAULT_LANGUAGE
    # `is None`, not `or`. An empty array is a person who switched every
    # channel off, and `or DEFAULT_USER_CHANNELS` would read that choice back
    # as the default — silently turning their notifications on again.
    stored = row.notification_channels
    channels = list(DEFAULT_USER_CHANNELS if stored is None else stored)
    return channels, row.language or DEFAULT_LANGUAGE


def _availability(
    *,
    tenant_channels: list[str],
    email_address: str | None,
    device_count: int,
) -> list[dict[str, Any]]:
    """Per channel: can it actually deliver, and if not, why not.

    The order of the checks is the order the person can act on them. A tenant
    switch is not theirs to change, so it is reported first and the other
    reasons are not stacked on top of it.
    """
    states: list[dict[str, Any]] = []
    for channel in USER_CHANNELS:
        reason: str | None = None
        if channel not in tenant_channels:
            reason = REASON_TENANT_DISABLED
        elif channel == "email" and not email_address:
            reason = REASON_NO_EMAIL
        elif channel == "push" and device_count == 0:
            reason = REASON_NO_DEVICE
        states.append({"channel": channel, "deliverable": reason is None, "reason": reason})
    return states


async def read_preferences(
    *,
    session: AsyncSession,
    tenant_session: AsyncSession | None,
    user_id: UUID,
    tenant_id: UUID | None,
    email_address: str | None,
) -> dict[str, Any]:
    """Everything the screen needs in one round trip."""
    channels, language = await _read_row(session, user_id)
    tenant_channels = (
        await _tenant_channels(session, tenant_id)
        if tenant_id is not None
        else list(DEFAULT_TENANT_CHANNELS)
    )
    device_count = (
        await _live_device_count(tenant_session, user_id) if tenant_session is not None else 0
    )
    return {
        "channels": channels,
        "language": language,
        "email_address": email_address or None,
        "registered_device_count": device_count,
        "tenant_channels": tenant_channels,
        "availability": _availability(
            tenant_channels=tenant_channels,
            email_address=email_address,
            device_count=device_count,
        ),
    }


async def update_preferences(
    *,
    session: AsyncSession,
    tenant_session: AsyncSession | None,
    user_id: UUID,
    tenant_id: UUID | None,
    email_address: str | None,
    channels: list[str] | None,
    language: Literal["en", "ar"] | None,
) -> dict[str, Any]:
    """Upsert the caller's own row and return the fresh state.

    Read-merge-write rather than an ON CONFLICT expression, because this is a
    PATCH: a request that names only ``language`` must leave the channels
    alone. One person editing their own row is not a contended write, so the
    read-then-write window costs nothing.

    ``INSERT`` names only the three columns it sets. The other five carry
    server defaults from migration 0003, so a first-time row lands complete.
    """
    current_channels, current_language = await _read_row(session, user_id)
    next_channels = normalise_channels(channels) if channels is not None else current_channels
    next_language = language or current_language

    await session.execute(
        text(
            """
            INSERT INTO public.user_preferences (user_id, language, notification_channels)
            VALUES (:uid, :lang, CAST(:chans AS text[]))
            ON CONFLICT (user_id) DO UPDATE
               SET language = EXCLUDED.language,
                   notification_channels = EXCLUDED.notification_channels
            """
        ),
        {"uid": user_id, "lang": next_language, "chans": next_channels},
    )
    # No commit here. `shared/db/session._yield_session` wraps the whole
    # request in `session.begin()` and commits when the dependency exits, so
    # committing inside the route closes that transaction and every later
    # statement raises "Can't operate on closed transaction". The read below
    # still sees the write — it is the same transaction.

    return await read_preferences(
        session=session,
        tenant_session=tenant_session,
        user_id=user_id,
        tenant_id=tenant_id,
        email_address=email_address,
    )
