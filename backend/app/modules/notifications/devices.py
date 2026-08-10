"""Device registration for the push channel.

A device row is the answer to "where do I send this". The field app registers
its FCM token at sign-in and on every token refresh, and revokes it on sign-out.

Three rules shape this module:

* **Register is an upsert keyed on the token, not on the user.** FCM reassigns
  a token when an app is reinstalled, so the same string can legitimately move
  to a different person. Inserting blindly would leave the previous owner's row
  in place and push that person's farm data to a handset they no longer hold.

* **You may only touch your own devices.** Every statement is scoped to the
  caller, so a token string learned from a log cannot be used to silence
  somebody else's phone.

* **Revoking is not deleting.** A revoked row keeps the record that the device
  existed, which is what answers "why did this phone stop buzzing" weeks later.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def register_device(
    session: AsyncSession,
    *,
    user_id: UUID,
    token: str,
    platform: str,
    app_version: str | None,
    locale: str | None,
) -> dict[str, Any]:
    """Upsert a device token and mark it live.

    Also clears ``revoked_at``: a scout who signs back in on a handset they
    previously signed out of should start receiving pushes again without an
    administrator having to do anything.
    """
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO device_tokens
                           (user_id, token, platform, app_version, locale, created_by)
                    VALUES (:user_id, :token, :platform, :app_version, :locale, :user_id)
                    ON CONFLICT (token) DO UPDATE
                       SET user_id      = EXCLUDED.user_id,
                           platform     = EXCLUDED.platform,
                           app_version  = EXCLUDED.app_version,
                           locale       = EXCLUDED.locale,
                           last_seen_at = now(),
                           revoked_at   = NULL,
                           deleted_at   = NULL,
                           updated_at   = now(),
                           updated_by   = EXCLUDED.user_id
                    RETURNING id, user_id, platform, app_version, locale,
                              last_seen_at, revoked_at, created_at
                    """
                ),
                {
                    "user_id": user_id,
                    "token": token,
                    "platform": platform,
                    "app_version": app_version,
                    "locale": locale,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_devices(session: AsyncSession, *, user_id: UUID) -> tuple[dict[str, Any], ...]:
    """The caller's live devices, most recently seen first.

    Tokens are never returned — they are push credentials, and a list screen
    has no use for them beyond identifying the handset.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, user_id, platform, app_version, locale,
                           last_seen_at, revoked_at, created_at
                      FROM device_tokens
                     WHERE user_id = :user_id
                       AND deleted_at IS NULL
                       AND revoked_at IS NULL
                     ORDER BY last_seen_at DESC
                    """
                ),
                {"user_id": user_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(dict(r) for r in rows)


async def revoke_device(session: AsyncSession, *, user_id: UUID, token: str) -> bool:
    """Stop pushing to one device. Returns False when nothing matched.

    Scoped to ``user_id`` on purpose: the token alone must not be enough to
    revoke a device, or anyone who saw one in a log could silence a scout.
    """
    result = await session.execute(
        text(
            "UPDATE device_tokens SET revoked_at = now(), updated_at = now(), "
            "updated_by = :user_id "
            "WHERE token = :token AND user_id = :user_id AND revoked_at IS NULL"
        ),
        {"token": token, "user_id": user_id},
    )
    return bool(getattr(result, "rowcount", 0) or 0)
