"""Trial signup service — the state machine behind the front door.

The states and the transitions are the design in
`docs/proposals/self-serve-trial-flow.md` § 3:

    pending_verification
        -> routed_to_existing   (company already has a tenant)
        -> rejected             (disposable domain)
        -> awaiting_approval    (everything else)
    awaiting_approval / paused
        -> approved             (platform admin, capped)
        -> paused               (platform admin, capacity)
        -> rejected             (platform admin, reason)
    approved -> provisioning -> provisioned | failed

Two rules hold everywhere in here:

1. **Nothing provisions without an approval.** `approve` is the only method
   that enqueues the provisioning task, and it always records who approved.
2. **The signup endpoint never says whether an address is known.** Duplicate,
   new, or already a customer — the caller gets the same answer. Anything
   else is an account-enumeration oracle on an unauthenticated route.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.audit import AuditService
from app.modules.billing import emails
from app.modules.billing.errors import (
    CapReachedError,
    InvalidTransitionError,
    SignupNotFoundError,
)
from app.modules.billing.models import QUEUE_STATUSES, TrialSignup
from app.modules.billing.repository import TrialRepository, day_and_week_start

_log = get_logger(__name__)

#: Free-mail providers. These are NOT rejected — the decision on record is
#: that many growers use them — but the queue flags them so an admin can see
#: what they are approving.
_FREE_MAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "yahoo.com",
        "yahoo.co.uk",
        "icloud.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "zoho.com",
        "mail.com",
        "gmx.com",
        "yandex.com",
    }
)


class TrialService:
    def __init__(
        self,
        *,
        public_session: AsyncSession,
        audit: AuditService | None = None,
    ) -> None:
        self._session = public_session
        self._repo = TrialRepository(public_session=public_session)
        self._audit = audit

    # ---- stage 2: the form ---------------------------------------------

    async def register_signup(
        self,
        *,
        full_name: str,
        email: str,
        organisation: str,
        country: str | None,
        phone: str | None,
        locale: str,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None:
        """Record a signup and send the verification link.

        Returns nothing. The endpoint answers 202 with the same body either
        way, so there is nothing for a caller to branch on — that is the
        point.
        """
        email = email.strip().lower()
        domain = _domain_of(email)

        if await self._repo.live_signup_exists(email=email, email_domain=domain):
            # Someone already asked, and the row is still live. Resending
            # here would let a stranger mail-bomb an address by replaying
            # the form, so we do nothing and still answer 202.
            _log.info("trial_signup_duplicate_ignored", domain=domain)
            return

        token = secrets.token_urlsafe(32)
        settings = get_settings()
        signup = await self._repo.insert_signup(
            full_name=full_name.strip(),
            email=email,
            email_domain=domain,
            organisation=organisation.strip(),
            country=country,
            phone=phone,
            locale=locale,
            status_handle=secrets.token_urlsafe(16),
            verification_token_hash=_hash_token(token),
            verification_expires_at=datetime.now(UTC)
            + timedelta(hours=settings.trial_verification_ttl_hours),
            source_ip=source_ip,
            user_agent=user_agent,
        )

        emails.send(
            to_address=signup.email,
            email=emails.verify_address(
                full_name=signup.full_name,
                verify_url=emails.verify_url(token),
            ),
        )
        _log.info("trial_signup_created", signup_id=str(signup.id), domain=domain)

    # ---- stage 3: verification and classification ----------------------

    async def verify(self, *, token: str) -> TrialSignup:
        """Verify the address, then classify the request.

        Classification decides only whether the request reaches the queue.
        It never provisions anything.
        """
        signup = await self._repo.get_by_token_hash(_hash_token(token))
        if signup is None:
            raise SignupNotFoundError("unknown verification token")

        if signup.status != "pending_verification":
            # Already verified. A second click on the same link is a normal
            # thing for a person to do, so this is not an error — the caller
            # shows the current state.
            return signup

        expires = signup.verification_expires_at
        if expires is not None and expires < datetime.now(UTC):
            signup.status = "expired"
            await self._repo.save(signup)
            return signup

        signup.verified_at = datetime.now(UTC)
        # The token is single-use. Clearing the hash makes a replayed link
        # fail even before the expiry is reached.
        signup.verification_token_hash = None

        settings = get_settings()
        if await self._domain_has_active_tenant(signup.email_domain):
            signup.status = "routed_to_existing"
            await self._repo.save(signup)
            emails.send(
                to_address=signup.email,
                email=emails.routed_to_existing(
                    full_name=signup.full_name,
                    organisation_hint=signup.email_domain,
                ),
            )
            _log.info("trial_routed_to_existing", signup_id=str(signup.id))
            return signup

        if signup.email_domain in {d.lower() for d in settings.trial_disposable_domains}:
            signup.status = "rejected"
            signup.decision_reason = "Disposable email domain."
            await self._repo.save(signup)
            _log.info("trial_rejected_disposable", signup_id=str(signup.id))
            return signup

        signup.status = "awaiting_approval"
        await self._repo.save(signup)
        emails.send(
            to_address=signup.email,
            email=emails.under_review(
                full_name=signup.full_name,
                status_url=emails.status_url(signup.status_handle),
            ),
        )
        _log.info("trial_awaiting_approval", signup_id=str(signup.id))
        return signup

    async def get_by_handle(self, handle: str) -> TrialSignup:
        signup = await self._repo.get_by_handle(handle)
        if signup is None:
            raise SignupNotFoundError("unknown status handle")
        return signup

    # ---- stage 4: review -------------------------------------------------

    async def capacity(self) -> dict[str, Any]:
        """Everything the approval screen shows above the queue."""
        settings = get_settings()
        day_start, week_start = day_and_week_start()
        snapshot = await self._repo.capacity_snapshot(
            day_start=day_start, week_start=week_start
        )
        usage = await self._repo.trial_usage()
        return {
            **snapshot,
            **usage,
            "cap_per_day": settings.trial_approvals_per_day,
            "cap_per_week": settings.trial_approvals_per_week,
            "day_resets_at": (day_start + timedelta(days=1)).isoformat(),
            "week_resets_at": (week_start + timedelta(days=7)).isoformat(),
            "can_approve": (
                snapshot["approved_today"] < settings.trial_approvals_per_day
                and snapshot["approved_this_week"] < settings.trial_approvals_per_week
            ),
        }

    async def list_queue(self, *, include_recent: bool = False) -> list[TrialSignup]:
        if include_recent:
            return await self._repo.list_recent()
        return await self._repo.list_queue()

    async def approve(
        self,
        *,
        signup_id: UUID,
        actor_user_id: UUID | None,
        override_reason: str | None = None,
    ) -> TrialSignup:
        """Approve a request. The only path that leads to a tenant.

        Past a cap this raises `CapReachedError` unless `override_reason` is
        given, and an override is written to the audit log with both counts.
        """
        signup = await self._require(signup_id)
        if signup.status not in QUEUE_STATUSES:
            raise InvalidTransitionError(current=signup.status, action="approve")

        settings = get_settings()
        day_start, week_start = day_and_week_start()
        used_today = await self._repo.count_approved_since(day_start)
        used_week = await self._repo.count_approved_since(week_start)

        over_day = used_today >= settings.trial_approvals_per_day
        over_week = used_week >= settings.trial_approvals_per_week
        if (over_day or over_week) and not override_reason:
            scope = "daily" if over_day else "weekly"
            used = used_today if over_day else used_week
            cap = (
                settings.trial_approvals_per_day
                if over_day
                else settings.trial_approvals_per_week
            )
            resets = (
                day_start + timedelta(days=1) if over_day else week_start + timedelta(days=7)
            )
            raise CapReachedError(
                scope=scope, used=used, cap=cap, resets_at=resets.isoformat()
            )

        signup.status = "approved"
        signup.reviewed_by = actor_user_id
        signup.reviewed_at = datetime.now(UTC)
        signup.cap_override = bool(over_day or over_week)
        if override_reason:
            signup.decision_reason = override_reason
        await self._repo.save(signup)

        await self._record_audit(
            event_type="billing.trial_approved",
            signup=signup,
            actor_user_id=actor_user_id,
            details={
                "approved_today": used_today,
                "approved_this_week": used_week,
                "cap_per_day": settings.trial_approvals_per_day,
                "cap_per_week": settings.trial_approvals_per_week,
                "cap_override": signup.cap_override,
                "override_reason": override_reason,
            },
        )
        _log.info(
            "trial_approved",
            signup_id=str(signup.id),
            cap_override=signup.cap_override,
            actor=str(actor_user_id),
        )
        return signup

    async def pause(
        self,
        *,
        signup_id: UUID,
        actor_user_id: UUID | None,
        reason: str | None = None,
    ) -> TrialSignup:
        """Hold a request on capacity. It stays in the queue."""
        signup = await self._require(signup_id)
        if signup.status not in QUEUE_STATUSES:
            raise InvalidTransitionError(current=signup.status, action="pause")

        signup.status = "paused"
        signup.reviewed_by = actor_user_id
        signup.reviewed_at = datetime.now(UTC)
        signup.decision_reason = reason
        await self._repo.save(signup)

        emails.send(
            to_address=signup.email,
            email=emails.paused(
                full_name=signup.full_name,
                status_url=emails.status_url(signup.status_handle),
            ),
        )
        await self._record_audit(
            event_type="billing.trial_paused",
            signup=signup,
            actor_user_id=actor_user_id,
            details={"reason": reason},
        )
        return signup

    async def reject(
        self,
        *,
        signup_id: UUID,
        actor_user_id: UUID | None,
        reason: str,
    ) -> TrialSignup:
        signup = await self._require(signup_id)
        if signup.status not in QUEUE_STATUSES:
            raise InvalidTransitionError(current=signup.status, action="reject")

        signup.status = "rejected"
        signup.reviewed_by = actor_user_id
        signup.reviewed_at = datetime.now(UTC)
        signup.decision_reason = reason
        await self._repo.save(signup)

        emails.send(
            to_address=signup.email,
            email=emails.rejected(
                full_name=signup.full_name,
                reason=reason,
                contact_url=emails.contact_url(),
            ),
        )
        await self._record_audit(
            event_type="billing.trial_rejected",
            signup=signup,
            actor_user_id=actor_user_id,
            details={"reason": reason},
        )
        return signup

    # ---- helpers ---------------------------------------------------------

    async def _require(self, signup_id: UUID) -> TrialSignup:
        signup = await self._repo.get(signup_id)
        if signup is None:
            raise SignupNotFoundError(f"no trial signup {signup_id}")
        return signup

    async def _domain_has_active_tenant(self, domain: str) -> bool:
        """True when a live tenant already belongs to this company.

        Matched on the contact address and on the owner address, because a
        tenant created by an admin carries the customer's address in
        `contact_email` while a self-serve one carries it in both.
        """
        result = await self._session.execute(
            text(
                """
                SELECT 1
                  FROM public.tenants
                 WHERE status IN ('active', 'pending_provision')
                   AND deleted_at IS NULL
                   AND lower(split_part(contact_email, '@', 2)) = :domain
                 LIMIT 1
                """
            ),
            {"domain": domain},
        )
        if result.first() is not None:
            return True

        result = await self._session.execute(
            text(
                """
                SELECT 1
                  FROM public.users u
                  JOIN public.tenant_memberships m ON m.user_id = u.id
                  JOIN public.tenants t ON t.id = m.tenant_id
                 WHERE t.status IN ('active', 'pending_provision')
                   AND t.deleted_at IS NULL
                   AND lower(split_part(u.email, '@', 2)) = :domain
                 LIMIT 1
                """
            ),
            {"domain": domain},
        )
        return result.first() is not None

    async def _record_audit(
        self,
        *,
        event_type: str,
        signup: TrialSignup,
        actor_user_id: UUID | None,
        details: dict[str, Any],
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            # No tenant exists yet, so the event goes to
            # `public.audit_events_archive` rather than a tenant
            # hypertable. `tenant_schema=None` is the documented way to
            # ask for that.
            tenant_schema=None,
            event_type=event_type,
            actor_user_id=actor_user_id,
            subject_kind="trial_signup",
            subject_id=signup.id,
            details={
                "email_domain": signup.email_domain,
                "organisation": signup.organisation,
                "status": signup.status,
                **details,
            },
        )


def is_free_mail(domain: str) -> bool:
    return domain.lower() in _FREE_MAIL_DOMAINS


def _domain_of(email: str) -> str:
    _, _, domain = email.partition("@")
    return domain.strip().lower()


def _hash_token(token: str) -> str:
    """SHA-256, not a password hash.

    The token is 32 random bytes from `secrets`, so there is nothing to
    brute-force and no salt to add; the hash exists only so a database dump
    does not contain working links.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
