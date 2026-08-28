"""Trial provisioning.

One task, triggered by one thing: a platform admin approving a signup. It
is deliberately the only code path in the service that reaches
`create_tenant` without a platform admin's own request behind it.

Why a task and not the request that approves:

  * `create_tenant` bootstraps a Postgres schema and runs Alembic against
    it, then calls Keycloak. That is seconds of work, and an admin clicking
    approve should not hold a connection open for it.
  * Keycloak can be briefly unreachable. A task retries; a request cannot.

The rule that matters most is at the end: **success is reported only when
Keycloak provisioning succeeded.** `create_tenant` returns a tenant with
`provisioning_failed=True` and no exception when the invite does not land,
and that has already shipped as a bug once on the invite path. Here it
would mean telling a stranger to check an email that never arrives.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Coroutine
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.shared.db.session import dispose_engine

_log = get_logger(__name__)

#: How many times provisioning is retried before the row is marked failed
#: and a platform alert is raised.
_MAX_ATTEMPTS = 4


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="billing.provision_trial",
    bind=True,
    acks_late=True,
    max_retries=_MAX_ATTEMPTS,
    ignore_result=True,
)
def provision_trial(self: Any, signup_id: str) -> None:
    """Create the tenant for an approved trial signup.

    Retries on two different things, and they are not the same:

      * The approval has not committed yet. The API enqueues inside the
        request, and the transaction commits when the request ends, so a
        fast worker can read the row before it says `approved`. Short
        retry, no attempt counted.
      * Keycloak did not provision. Longer backoff, attempt counted, and
        the row is marked `failed` once the attempts run out.
    """
    outcome = _run_task(_provision(UUID(signup_id)))

    if outcome == "not_yet_committed":
        raise self.retry(countdown=5, max_retries=_MAX_ATTEMPTS)
    if outcome == "retry_provisioning":
        raise self.retry(countdown=60 * (self.request.retries + 1))


async def _provision(signup_id: UUID) -> str:  # noqa: PLR0911
    """Returns an outcome word the Celery wrapper turns into a retry.

    Seven exits, each a distinct outcome the caller must tell apart:
    unknown row, not yet committed, already decided, create failed with
    attempts left, create failed for good, Keycloak pending, and done.
    Collapsing them would mean the worker could not tell "retry in five
    seconds" from "stop and alert".
    """
    from sqlalchemy import text

    from app.modules.billing.emails import approved as approved_email
    from app.modules.billing.emails import send as send_email
    from app.modules.billing.repository import TrialRepository
    from app.modules.tenancy import get_tenant_service
    from app.shared.db.session import AsyncSessionLocal

    settings = get_settings()
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL search_path TO public"))
        repo = TrialRepository(public_session=session)
        signup = await repo.get(signup_id)

        if signup is None:
            _log.warning("trial_provision_unknown_signup", signup_id=str(signup_id))
            return "done"

        if signup.status == "awaiting_approval":
            # The approving transaction has not landed yet. Not an error.
            return "not_yet_committed"

        if signup.status not in ("approved", "provisioning"):
            _log.info(
                "trial_provision_skipped",
                signup_id=str(signup_id),
                status=signup.status,
            )
            return "done"

        signup.status = "provisioning"
        signup.provisioning_attempts += 1
        attempt = signup.provisioning_attempts
        await repo.save(signup)

        service = get_tenant_service(session)
        slug = await _unique_slug(session, signup.organisation)

        try:
            result = await service.create_tenant(
                slug=slug,
                name=signup.organisation,
                contact_email=signup.email,
                owner_email=signup.email,
                owner_full_name=signup.full_name,
                default_locale=signup.locale,
                default_unit_system="feddan",
                initial_tier="free",
                # No platform admin is acting here. The approval carries the
                # named actor; this step is the system doing what it was
                # told, and the audit trail already says who told it.
                actor_user_id=None,
            )
        except Exception as exc:
            signup.last_error = str(exc)[:2000]
            signup.status = "failed" if attempt >= _MAX_ATTEMPTS else "approved"
            await repo.save(signup)
            _log.warning(
                "trial_provision_failed",
                signup_id=str(signup_id),
                attempt=attempt,
                error=str(exc),
            )
            return "done" if attempt >= _MAX_ATTEMPTS else "retry_provisioning"

        signup.tenant_id = result.tenant_id

        if result.provisioning_failed:
            # The tenant rows and the schema exist, but Keycloak did not
            # take the owner. Nothing is sent to the visitor: an email
            # saying "set your password" with no account behind it is
            # worse than silence.
            signup.last_error = "keycloak provisioning did not succeed"
            if attempt >= _MAX_ATTEMPTS:
                signup.status = "failed"
                await repo.save(signup)
                _log.error(
                    "trial_provision_keycloak_exhausted",
                    signup_id=str(signup_id),
                    tenant_id=str(result.tenant_id),
                    attempts=attempt,
                )
                return "done"
            await repo.save(signup)
            _log.warning(
                "trial_provision_keycloak_pending",
                signup_id=str(signup_id),
                tenant_id=str(result.tenant_id),
                attempt=attempt,
            )
            return "retry_provisioning"

        await _write_trial_term(
            session,
            tenant_id=result.tenant_id,
            trial_days=settings.trial_length_days,
            max_area_feddan=settings.trial_max_area_feddan,
            max_farms=settings.trial_max_farms,
            max_seats=settings.trial_max_seats,
        )

        signup.status = "provisioned"
        signup.last_error = None
        await repo.save(signup)

    # Sent after the commit. A mail that goes out for a transaction that
    # then rolls back cannot be recalled.
    send_email(
        to_address=signup.email,
        email=approved_email(
            full_name=signup.full_name,
            set_password_url=f"{settings.trial_app_base_url.rstrip('/')}/",
            trial_days=settings.trial_length_days,
        ),
    )
    _log.info(
        "trial_provisioned",
        signup_id=str(signup_id),
        tenant_id=str(signup.tenant_id),
        slug=slug,
    )
    return "done"


async def _write_trial_term(
    session: Any,
    *,
    tenant_id: UUID,
    trial_days: int,
    max_area_feddan: int,
    max_farms: int,
    max_seats: int,
) -> None:
    """Put the trial dates and caps on the current subscription row.

    `create_tenant` writes the row with a tier and nothing else — the
    `trial_start` and `trial_end` columns have existed since PR-8 and no
    writer has ever filled them.

    The caps go into `feature_flags` for now. Nothing reads them yet; the
    entitlement gate is the next slice, and it reads them from here. Writing
    them now means the first trial tenants carry their caps from day one
    rather than needing a backfill.
    """
    from sqlalchemy import text

    starts = date.today()
    ends = starts + timedelta(days=trial_days)
    await session.execute(
        text(
            """
            UPDATE public.tenant_subscriptions
               SET trial_start = :starts,
                   trial_end = :ends,
                   plan_type = 'trial',
                   feature_flags = feature_flags || CAST(:flags AS jsonb),
                   updated_at = now()
             WHERE tenant_id = :tenant_id
               AND is_current IS TRUE
            """
        ),
        {
            "starts": starts,
            "ends": ends,
            "tenant_id": tenant_id,
            "flags": json.dumps(
                {
                    "max_area_feddan": max_area_feddan,
                    "max_farms": max_farms,
                    "max_seats": max_seats,
                    "writes_allowed": True,
                    "api_access": False,
                }
            ),
        },
    )


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


async def _unique_slug(session: Any, organisation: str) -> str:
    """A slug the visitor never sees fail.

    `create_tenant` raises on a duplicate slug and the platform route turns
    that into a 409. On this path there is nobody to hand a 409 to, so the
    collision is resolved here with a numeric suffix.

    The shape must satisfy `ck_tenants_slug_format`: lower-case letters,
    digits and hyphens, 3 to 32 characters.
    """
    from sqlalchemy import text

    base = _SLUG_STRIP.sub("-", organisation.lower()).strip("-")[:24].strip("-")
    if len(base) < 3:
        base = f"trial-{base}".strip("-")
    base = base[:24].strip("-")

    candidate = base
    suffix = 1
    while True:
        exists = await session.execute(
            text("SELECT 1 FROM public.tenants WHERE slug = :slug LIMIT 1"),
            {"slug": candidate},
        )
        if exists.first() is None:
            return candidate
        suffix += 1
        candidate = f"{base}-{suffix}"[:32].strip("-")


@shared_task(name="billing.chase_unreviewed_trials", ignore_result=True)  # type: ignore[misc,untyped-decorator,unused-ignore]
def chase_unreviewed_trials() -> None:
    """Mail anyone who has waited a working day with no decision.

    The promise on the verify page is "within one working day". A promise
    nobody is watching is how a queue quietly stops being answered, so the
    system chases on the visitor's behalf rather than waiting for them to
    ask.

    Sends once per signup — `chase_email_sent_at` is the guard.
    """
    _run_task(_chase())


async def _chase() -> None:
    from sqlalchemy import text

    from app.modules.billing.emails import send as send_email
    from app.modules.billing.emails import status_url, still_reviewing
    from app.modules.billing.repository import TrialRepository
    from app.shared.db.session import AsyncSessionLocal

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    factory = AsyncSessionLocal()
    to_send: list[tuple[str, str, str]] = []

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL search_path TO public"))
        repo = TrialRepository(public_session=session)
        for signup in await repo.list_queue():
            if signup.chase_email_sent_at is not None:
                continue
            if signup.created_at is None or signup.created_at > cutoff:
                continue
            signup.chase_email_sent_at = datetime.now(UTC)
            await repo.save(signup)
            to_send.append((signup.email, signup.full_name, signup.status_handle))

    for email, full_name, handle in to_send:
        send_email(
            to_address=email,
            email=still_reviewing(full_name=full_name, status_url=status_url(handle)),
        )
    if to_send:
        _log.info("trial_chase_sent", count=len(to_send))
