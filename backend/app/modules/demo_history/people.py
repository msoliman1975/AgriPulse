"""The farm team, acting on what the engine opened.

Without this step a replayed history is the engine talking to nobody:
every recommendation stays open for two years and every alert is never
seen. A demo needs the other half of the loop, where somebody schedules
the irrigation, a crew does it, and the card closes.

The team is the build tenant's own users, picked by the role they hold,
so every action is attributed to a real login. Each action goes through
the same service call the API route makes, and each one runs in its own
transaction under its own moved clock, so the audit trail, the history
tables and the timeline all read like a working week.

Every choice is a hash of the row id, never a random draw. Rebuilding
the same tenant from the same inputs gives the same history, which is
what makes a bad demo reproducible.

The policy is written for mango on drip in Egypt and says so in its
reasons and product names. It is demo content, not product behaviour.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.alerts.service import get_alerts_service
from app.modules.plans.service import get_plans_service
from app.modules.recommendations.service import get_recommendations_service
from app.shared import clock
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)

# Recommendation action → board activity type, as the schedule route maps it.
_ACTIVITY_FOR_ACTION: dict[str, str] = {
    "irrigate": "irrigation",
    "fertilize": "fertilizing",
    "spray": "spraying",
    "prune": "pruning",
    "harvest_window": "harvesting",
}

# What the crew writes on the board for each kind of job.
_PRODUCT_FOR_ACTIVITY: dict[str, tuple[str | None, str | None]] = {
    "irrigation": (None, "Add 2 h to each drip cycle for 5 days"),
    "fertilizing": ("Potassium sulphate 50% K2O", "25 kg per feddan through the drip"),
    "spraying": ("Sulphur 80% WG", "250 g per 100 L, full cover"),
    "pruning": (None, "Open the canopy centre, remove dead wood"),
    "harvesting": (None, "Pick at colour break, morning only"),
    "observation": (None, "Walk the block, check emitters and 10 trees"),
}

_DISMISS_REASONS: tuple[str, ...] = (
    "Checked in the field. Emitters run and the trees look normal.",
    "Already covered by this week's program.",
    "Cloud shadow on the image. The block was fine on the ground.",
    "Seen by the agronomist. We will watch it at the next pass.",
)

_DEFER_DAYS = 7
_SKIP_NOTE = "Crew moved to another block. Rescheduled on the board."


def _roll(*parts: object) -> float:
    """A stable number in [0, 1) for these parts."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _at(day: date, key: object, first_hour: int, last_hour: int) -> datetime:
    """A working-hours instant on `day`, fixed by `key`."""
    span_minutes = (last_hour - first_hour) * 60
    minute = int(_roll(key, "minute") * span_minutes)
    return datetime.combine(day, time(first_hour), tzinfo=UTC) + timedelta(minutes=minute)


@dataclass(frozen=True)
class Team:
    """The users who act, by the role they hold in the tenant."""

    manager: UUID | None
    agronomist: UUID | None
    operator: UUID | None
    operator_membership: UUID | None

    @property
    def complete(self) -> bool:
        return None not in (self.manager, self.agronomist, self.operator)


def act_for_tenant(tenant_schema: str) -> dict[str, int]:
    """One day of the team's work in `tenant_schema`, on the clock's day."""
    return _run(_act_async(tenant_schema))


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


async def _begin(session: Any, tenant_schema: str) -> None:
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(text("SELECT set_config('app.current_tenant_id', :v, TRUE)"), {"v": safe})


async def _act_async(tenant_schema: str) -> dict[str, int]:
    counts = {
        "scheduled": 0,
        "deferred": 0,
        "dismissed": 0,
        "started": 0,
        "completed": 0,
        "skipped": 0,
        "acknowledged": 0,
        "resolved": 0,
    }
    today = clock.today()
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _begin(session, tenant_schema)
        team = await _load_team(session, tenant_schema)
        recs = await _open_items(session, today)
        activities = await _due_activities(session, today)
        alerts = await _active_alerts(session)

    if not team.complete:
        # Refuse loudly rather than write history with no actor on it.
        raise RuntimeError(
            "demo team incomplete: the tenant needs a FarmManager, an "
            "Agronomist and a FieldOperator before people can act"
        )

    for rec in recs:
        outcome = await _decide_recommendation(factory, tenant_schema, team, rec, today)
        if outcome:
            counts[outcome] += 1
    for act in activities:
        outcome = await _work_activity(factory, tenant_schema, team, act, today)
        if outcome:
            counts[outcome] += 1
    for alert in alerts:
        outcome = await _handle_alert(factory, tenant_schema, team, alert, today)
        if outcome:
            counts[outcome] += 1
    return counts


async def _load_team(session: Any, tenant_schema: str) -> Team:
    """The first active holder of each role, farm role before tenant role."""
    rows = (
        await session.execute(
            text(
                """
                SELECT m.id AS membership_id, m.user_id, fs.role
                  FROM public.tenant_memberships m
                  JOIN public.tenants t ON t.id = m.tenant_id
                  JOIN public.farm_scopes fs
                    ON fs.membership_id = m.id AND fs.revoked_at IS NULL
                 WHERE t.schema_name = :schema
                   AND m.status = 'active'
                 ORDER BY m.joined_at NULLS LAST, m.id
                """
            ),
            {"schema": tenant_schema},
        )
    ).mappings()
    by_role: dict[str, tuple[UUID, UUID]] = {}
    for row in rows:
        by_role.setdefault(row["role"], (row["membership_id"], row["user_id"]))
    operator = by_role.get("FieldOperator")
    return Team(
        manager=(by_role.get("FarmManager") or (None, None))[1],
        agronomist=(by_role.get("Agronomist") or (None, None))[1],
        operator=operator[1] if operator else None,
        operator_membership=operator[0] if operator else None,
    )


async def _open_items(session: Any, today: date) -> list[dict[str, Any]]:
    """Parents and block items still waiting on a person.

    Group members are left out: the service refuses to act on one, and the
    parent carries its cells with it.
    """
    rows = await session.execute(
        text(
            """
            SELECT id, block_id, farm_id, action_type, severity, state,
                   deferred_until, created_at::date AS opened_on
              FROM recommendations
             WHERE state IN ('open', 'deferred')
               AND group_parent_id IS NULL
               AND deleted_at IS NULL
               AND created_at::date < :today
             ORDER BY created_at, id
            """
        ),
        {"today": today},
    )
    return [dict(r) for r in rows.mappings()]


async def _due_activities(session: Any, today: date) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT id, activity_type, scheduled_date, duration_days, status
              FROM plan_activities
             WHERE status IN ('scheduled', 'in_progress')
               AND scheduled_date <= :today
               AND deleted_at IS NULL
             ORDER BY scheduled_date, id
            """
        ),
        {"today": today},
    )
    return [dict(r) for r in rows.mappings()]


async def _active_alerts(session: Any) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT id, status, severity, created_at::date AS opened_on,
                   acknowledged_at::date AS acknowledged_on
              FROM alerts
             WHERE status IN ('open', 'acknowledged')
               AND group_parent_id IS NULL
               AND deleted_at IS NULL
               AND created_at <= public.app_now()
             ORDER BY created_at, id
            """
        )
    )
    return [dict(r) for r in rows.mappings()]


async def _decide_recommendation(
    factory: Any, tenant_schema: str, team: Team, rec: dict[str, Any], today: date
) -> str | None:
    rid = rec["id"]
    until = rec["deferred_until"]
    if rec["state"] == "deferred" and until is not None and until.date() > today:
        return None
    # Somebody looks within one to three days of the card appearing.
    wait = 1 + int(_roll(rid, "wait") * 3)
    if (today - rec["opened_on"]).days < wait and rec["state"] == "open":
        return None

    roll = _roll(rid, "choice")
    activity = _ACTIVITY_FOR_ACTION.get(rec["action_type"])
    if rec["severity"] == "info" or (activity is None and roll >= 0.6):
        action, actor = "dismiss", team.agronomist
    elif roll < 0.72 or rec["state"] == "deferred":
        action, actor = "schedule", team.manager
    elif roll < 0.84:
        action, actor = "defer", team.agronomist
    else:
        action, actor = "dismiss", team.agronomist

    at = _at(today, rid, 7, 12)
    with clock.simulate(at):
        async with factory() as session, session.begin():
            await _begin(session, tenant_schema)
            async with factory() as public_session:
                svc = get_recommendations_service(
                    tenant_session=session, public_session=public_session
                )
                if action == "schedule":
                    await _schedule(
                        session, svc, tenant_schema, team, rec, activity or "observation", today
                    )
                    return "scheduled"
                if action == "defer":
                    await svc.transition_recommendation(
                        recommendation_id=rid,
                        action="defer",
                        dismissal_reason=None,
                        deferred_until=at + timedelta(days=_DEFER_DAYS),
                        outcome_notes="Waiting for the next image before acting.",
                        actor_user_id=actor,
                        tenant_schema=tenant_schema,
                    )
                    return "deferred"
                reasons = _DISMISS_REASONS
                await svc.transition_recommendation(
                    recommendation_id=rid,
                    action="dismiss",
                    dismissal_reason=reasons[int(_roll(rid, "reason") * len(reasons))],
                    deferred_until=None,
                    outcome_notes=None,
                    actor_user_id=actor,
                    tenant_schema=tenant_schema,
                )
                return "dismissed"


async def _schedule(
    session: Any,
    svc: Any,
    tenant_schema: str,
    team: Team,
    rec: dict[str, Any],
    activity_type: str,
    today: date,
) -> None:
    """Board activity plus apply, as the schedule route does it."""
    rid = rec["id"]
    when = today + timedelta(days=int(_roll(rid, "lead") * 2))
    product, dosage = _PRODUCT_FOR_ACTIVITY.get(activity_type, (None, None))
    plans = get_plans_service(tenant_session=session)
    activity = await plans.create_flat_activity(
        farm_id=rec["farm_id"],
        block_id=rec["block_id"],
        activity_type=activity_type,
        scheduled_date=when,
        duration_days=1,
        start_time=time(6, 30),
        product_name=product,
        dosage=dosage,
        notes="From the Action Center card.",
        actor_user_id=team.manager,
        tenant_schema=tenant_schema,
        recommendation_id=rid,
        assigned_membership_id=team.operator_membership,
    )
    await svc.transition_recommendation(
        recommendation_id=rid,
        action="apply",
        dismissal_reason=None,
        deferred_until=None,
        outcome_notes=f"Scheduled as plan activity {activity['id']} for {when.isoformat()}.",
        actor_user_id=team.manager,
        tenant_schema=tenant_schema,
    )


async def _work_activity(
    factory: Any, tenant_schema: str, team: Team, act: dict[str, Any], today: date
) -> str | None:
    aid = act["id"]
    if act["status"] == "scheduled" and act["scheduled_date"] == today:
        state_action, outcome, hours = "start", "started", (6, 8)
    elif act["status"] == "scheduled":
        # Missed its day with nobody starting it: the crew catches up.
        state_action, outcome, hours = "start", "started", (6, 8)
    elif _roll(aid, "skip") < 0.06:
        state_action, outcome, hours = "skip", "skipped", (13, 16)
    else:
        state_action, outcome, hours = "complete", "completed", (13, 17)
    if state_action == "complete" and act["scheduled_date"] == today:
        return None  # started this morning, finished tomorrow at the earliest

    with clock.simulate(_at(today, (aid, state_action), *hours)):
        async with factory() as session, session.begin():
            await _begin(session, tenant_schema)
            plans = get_plans_service(tenant_session=session)
            await plans.update_activity(
                activity_id=aid,
                metadata_changes={"notes": _SKIP_NOTE} if state_action == "skip" else {},
                state_action=state_action,
                actor_user_id=team.operator,
                tenant_schema=tenant_schema,
            )
    return outcome


async def _handle_alert(
    factory: Any, tenant_schema: str, team: Team, alert: dict[str, Any], today: date
) -> str | None:
    aid = alert["id"]
    if alert["status"] == "open":
        if (today - alert["opened_on"]).days < 1:
            return None
        action, actor, outcome, hours = "acknowledge", team.agronomist, "acknowledged", (7, 10)
    else:
        hold = 3 + int(_roll(aid, "hold") * 5)
        if alert["acknowledged_on"] is None or (today - alert["acknowledged_on"]).days < hold:
            return None
        action, actor, outcome, hours = "resolve", team.manager, "resolved", (14, 17)

    with clock.simulate(_at(today, (aid, action), *hours)):
        async with factory() as session, session.begin():
            await _begin(session, tenant_schema)
            async with factory() as public_session:
                svc = get_alerts_service(tenant_session=session, public_session=public_session)
                await svc.transition_alert(
                    alert_id=aid,
                    action=action,
                    snooze_until=None,
                    actor_user_id=actor,
                    tenant_schema=tenant_schema,
                )
    return outcome
