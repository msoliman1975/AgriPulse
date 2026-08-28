"""Data access for trial signups and the capacity numbers behind the queue.

Every method takes the public-schema session. There is no tenant context on
the signup path — at that point no tenant exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import LIVE_STATUSES, QUEUE_STATUSES, TrialSignup

#: Matches `farms.service._M2_PER_FEDDAN`. Duplicated rather than imported:
#: importing another module's private helper is what the import contracts
#: exist to stop.
_M2_PER_FEDDAN = 4200.83


class TrialRepository:
    def __init__(self, *, public_session: AsyncSession) -> None:
        self._session = public_session

    # ---- writes ---------------------------------------------------------

    async def insert_signup(
        self,
        *,
        full_name: str,
        email: str,
        email_domain: str,
        organisation: str,
        country: str | None,
        phone: str | None,
        locale: str,
        status_handle: str,
        verification_token_hash: str,
        verification_expires_at: datetime,
        source_ip: str | None,
        user_agent: str | None,
    ) -> TrialSignup:
        signup = TrialSignup(
            status="pending_verification",
            full_name=full_name,
            email=email,
            email_domain=email_domain,
            organisation=organisation,
            country=country,
            phone=phone,
            locale=locale,
            status_handle=status_handle,
            verification_token_hash=verification_token_hash,
            verification_expires_at=verification_expires_at,
            verification_sent_at=datetime.now(UTC),
            source_ip=source_ip,
            user_agent=user_agent,
        )
        self._session.add(signup)
        await self._session.flush()
        return signup

    async def save(self, signup: TrialSignup) -> TrialSignup:
        signup.updated_at = datetime.now(UTC)
        await self._session.flush()
        return signup

    # ---- reads ----------------------------------------------------------

    async def get(self, signup_id: UUID) -> TrialSignup | None:
        return await self._session.get(TrialSignup, signup_id)

    async def get_by_handle(self, handle: str) -> TrialSignup | None:
        stmt = select(TrialSignup).where(TrialSignup.status_handle == handle)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> TrialSignup | None:
        stmt = select(TrialSignup).where(TrialSignup.verification_token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def live_signup_exists(self, *, email: str, email_domain: str) -> bool:
        """A live request already holds the slot for this address or company.

        Checked before the insert so a duplicate reads as a quiet 202 rather
        than a unique-violation traceback. The partial indexes in 0056 are
        still the authority — this is the friendly path, not the guard.
        """
        stmt = select(TrialSignup.id).where(
            TrialSignup.status.in_(LIVE_STATUSES),
            (func.lower(TrialSignup.email) == email.lower())
            | (TrialSignup.email_domain == email_domain),
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def list_queue(self, *, statuses: tuple[str, ...] | None = None) -> list[TrialSignup]:
        """The review queue, oldest first — the one that has waited longest
        is the one that needs a decision.
        """
        stmt = (
            select(TrialSignup)
            .where(TrialSignup.status.in_(statuses or QUEUE_STATUSES))
            .order_by(TrialSignup.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_recent(self, *, limit: int = 50) -> list[TrialSignup]:
        stmt = select(TrialSignup).order_by(TrialSignup.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_failed_provisioning(self) -> list[TrialSignup]:
        stmt = (
            select(TrialSignup)
            .where(TrialSignup.status.in_(("provisioning", "failed")))
            .order_by(TrialSignup.updated_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ---- capacity -------------------------------------------------------

    async def count_approved_since(self, since: datetime) -> int:
        """Approvals, not provisionings. The cap is on the decision, so an
        approval that later fails in Keycloak still spends a slot — otherwise
        a broken provisioner would silently lift the cap.
        """
        stmt = select(func.count()).select_from(TrialSignup).where(
            TrialSignup.reviewed_at.is_not(None),
            TrialSignup.reviewed_at >= since,
            TrialSignup.status.in_(("approved", "provisioning", "provisioned", "failed")),
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def capacity_snapshot(self, *, day_start: datetime, week_start: datetime) -> dict[str, Any]:
        """The numbers the approval screen shows above the queue.

        Live trials, and the farms and area they carry, come from a
        cross-schema roll-up. Trial tenants are few, so the loop is cheap
        and stays readable; if that stops being true it becomes a view.
        """
        approved_today = await self.count_approved_since(day_start)
        approved_week = await self.count_approved_since(week_start)

        queue = await self.list_queue()
        oldest_wait_hours: float | None = None
        if queue:
            oldest = min(s.created_at for s in queue if s.created_at is not None)
            oldest_wait_hours = (datetime.now(UTC) - oldest).total_seconds() / 3600.0

        live_trials = await self._session.execute(
            text(
                """
                SELECT COUNT(*) FROM public.tenant_subscriptions
                 WHERE is_current IS TRUE
                   AND tier = 'free'
                   AND trial_end IS NOT NULL
                   AND trial_end >= CURRENT_DATE
                """
            )
        )
        expired_trials = await self._session.execute(
            text(
                """
                SELECT COUNT(*) FROM public.tenant_subscriptions
                 WHERE is_current IS TRUE
                   AND tier = 'free'
                   AND trial_end IS NOT NULL
                   AND trial_end < CURRENT_DATE
                """
            )
        )
        converted = await self._session.execute(
            text(
                """
                SELECT COUNT(*) FROM public.tenant_subscriptions
                 WHERE is_current IS TRUE
                   AND tier <> 'free'
                   AND trial_start IS NOT NULL
                """
            )
        )

        return {
            "approved_today": approved_today,
            "approved_this_week": approved_week,
            "queue_depth": len(queue),
            "oldest_wait_hours": oldest_wait_hours,
            "live_trials": int(live_trials.scalar_one()),
            "expired_trials": int(expired_trials.scalar_one()),
            "converted_trials": int(converted.scalar_one()),
        }

    async def trial_usage(self) -> dict[str, int]:
        """Farms and enrolled area across every live trial tenant.

        Reads each trial tenant's schema in turn. A tenant whose schema is
        mid-bootstrap is skipped rather than failing the whole screen.
        """
        rows = await self._session.execute(
            text(
                """
                SELECT t.schema_name
                  FROM public.tenants t
                  JOIN public.tenant_subscriptions s ON s.tenant_id = t.id
                 WHERE s.is_current IS TRUE
                   AND s.tier = 'free'
                   AND s.trial_end IS NOT NULL
                   AND s.trial_end >= CURRENT_DATE
                   AND t.status = 'active'
                """
            )
        )
        farms = 0
        area_m2 = 0.0
        for (schema_name,) in rows.all():
            # Each schema is read in its own SAVEPOINT: one missing table
            # must not abort the transaction and blank the whole screen.
            nested = await self._session.begin_nested()
            try:
                result = await self._session.execute(
                    text(
                        "SELECT COUNT(*), COALESCE(SUM(area_m2), 0) "  # noqa: S608
                        f'FROM "{schema_name}".farms '
                        "WHERE active_to IS NULL OR active_to > CURRENT_DATE"
                    )
                )
                farm_count, farm_area = result.one()
                farms += int(farm_count)
                area_m2 += float(farm_area or 0)
                await nested.commit()
            except Exception:
                await nested.rollback()
        # farms.area_m2 is the stored unit; the screen talks in feddan.
        # Same divisor as farms.service so the two never disagree.
        return {
            "trial_farms": farms,
            "trial_area_feddan": int(round(area_m2 / _M2_PER_FEDDAN)),
        }


def day_and_week_start(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Cap windows, both in UTC.

    The day resets at midnight UTC and the week on Monday. Stated here once
    so the screen and the check cannot disagree about when a cap lifts.
    """
    moment = now or datetime.now(UTC)
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    return day_start, week_start
