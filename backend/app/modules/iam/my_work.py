"""Everything assigned to the signed-in person, in one feed (W4-B).

"Assign this to Ahmed" means a different column depending on which surface you
are standing on, and the three do not share a key space:

* ``scouting_visits.assigned_to``          -> ``public.users.id``
* ``plan_activities.assigned_membership_id`` -> ``public.tenant_memberships.id``
* ``activity_resources.resource_id``       -> ``resources.id``, which reaches a
  membership through the nullable ``resources.membership_id``

The phone could only ever query the first. A supervisor who put somebody on the
board — the natural way to schedule field work — produced an assignment the
scout's app was structurally unable to see: nothing failed, nothing logged, and
the scout looked at an empty list while their name sat on four activities.

Resolving that braid once on the server beats every client learning the join,
and it is the only place that can: the chain crosses the schema boundary
(``public`` for the membership, the tenant schema for the work), which no
single query can span.

This became possible only after tenant migration 0071 made
``resources.membership_id`` unique. Before it, a person working two farms had
two worker rows and "which resource is this member" had no single answer.

**No capability gate, deliberately.** Every row returned is one where the
caller *is* the assignee, so there is nothing here they could not already see
by other means, and gating it would defeat the point: a Scout holds no
``plan_activity.complete``, so requiring it would hide from them precisely the
work somebody assigned them.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# A visit stops being work once it is closed or withdrawn; an activity once it
# is done or cancelled. Everything else is still somebody's problem.
_OPEN_VISIT_STATUSES = ("queued", "assigned", "accepted", "in_progress")
_OPEN_ACTIVITY_STATUSES = ("scheduled", "in_progress", "overdue")

WorkKind = Literal["scouting_visit", "plan_activity"]


async def membership_for(
    public_session: AsyncSession, *, user_id: UUID, tenant_id: UUID
) -> UUID | None:
    row = (
        await public_session.execute(
            text(
                "SELECT id FROM public.tenant_memberships "
                "WHERE user_id = :uid AND tenant_id = :tid "
                "  AND status = 'active' AND deleted_at IS NULL "
                "LIMIT 1"
            ).bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True)),
                bindparam("tid", type_=PG_UUID(as_uuid=True)),
            ),
            {"uid": user_id, "tid": tenant_id},
        )
    ).first()
    return row.id if row else None


async def list_my_work(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    farm_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Open work assigned to this person, newest deadline first.

    ``farm_id`` narrows to one farm, which is what the phone asks for. Omitted,
    it spans every farm the person is assigned on — the answer a "my work"
    screen wants before a farm has been chosen.
    """
    membership_id = await membership_for(public_session, user_id=user_id, tenant_id=tenant_id)

    items: list[dict[str, Any]] = []
    items.extend(await _scouting_visits(tenant_session, user_id=user_id, farm_id=farm_id))
    if membership_id is not None:
        items.extend(
            await _plan_activities(tenant_session, membership_id=membership_id, farm_id=farm_id)
        )

    # Overdue first, then by deadline, then undated last — the same order the
    # visit list already uses, so one merged feed does not reorder itself
    # depending on which surface a row came from.
    items.sort(key=lambda i: (i["due_at"] is None, i["due_at"] or ""))
    return items


async def _scouting_visits(
    session: AsyncSession, *, user_id: UUID, farm_id: UUID | None
) -> list[dict[str, Any]]:
    where = "assigned_to = :uid AND status = ANY(:statuses)"
    params: dict[str, Any] = {"uid": user_id, "statuses": list(_OPEN_VISIT_STATUSES)}
    if farm_id is not None:
        where += " AND farm_id = :fid"
        params["fid"] = farm_id
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT id, farm_id, block_id, title, instruction, status,
                           origin, severity, priority, due_by, template_id
                      FROM scouting_visits
                     WHERE {where}
                    """
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                params,
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "kind": "scouting_visit",
            "id": r["id"],
            "farm_id": r["farm_id"],
            "block_id": r["block_id"],
            "title": r["title"],
            "detail": r["instruction"],
            "status": r["status"],
            "category": r["origin"],
            "severity": r["severity"],
            "priority": r["priority"],
            "due_at": r["due_by"].isoformat() if r["due_by"] else None,
            # Which form to put in front of the scout. A visit dispatched
            # against a pest signal should not open the general catalogue.
            "template_id": r["template_id"],
        }
        for r in rows
    ]


async def _plan_activities(
    session: AsyncSession, *, membership_id: UUID, farm_id: UUID | None
) -> list[dict[str, Any]]:
    """Board work, reached two ways.

    Directly, through ``assigned_membership_id`` (what the Action Center sets),
    and indirectly through the labour roster: an activity this person is
    attached to as a *resource*. Both are somebody telling them to do
    something, so both belong in the same feed.
    """
    where = (
        "(a.assigned_membership_id = :mid"
        " OR EXISTS ("
        "      SELECT 1 FROM activity_resources ar"
        "        JOIN resources r ON r.id = ar.resource_id"
        "       WHERE ar.activity_id = a.id"
        "         AND r.membership_id = :mid"
        "         AND r.archived_at IS NULL"
        " ))"
        " AND a.status = ANY(:statuses)"
    )
    params: dict[str, Any] = {
        "mid": membership_id,
        "statuses": list(_OPEN_ACTIVITY_STATUSES),
    }
    if farm_id is not None:
        where += " AND a.farm_id = :fid"
        params["fid"] = farm_id
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT a.id, a.farm_id, a.block_id, a.activity_type, a.notes,
                           a.status, a.scheduled_date, a.start_time, a.product_name
                      FROM plan_activities a
                     WHERE {where}
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                params,
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "kind": "plan_activity",
            "id": r["id"],
            "farm_id": r["farm_id"],
            "block_id": r["block_id"],
            # The board has no free-text title; the activity type *is* the
            # instruction ("spraying", "observation"), and the product is the
            # next most useful thing to see without opening it.
            "title": r["activity_type"],
            "detail": r["product_name"] or r["notes"],
            "status": r["status"],
            "category": r["activity_type"],
            "severity": None,
            "priority": None,
            # A date, not a timestamp: the board schedules by day. Rendered as
            # the start of that day so it sorts against visit deadlines
            # without pretending to a precision it does not have.
            "due_at": r["scheduled_date"].isoformat() if r["scheduled_date"] else None,
            # The board carries no signal template; board work opens the
            # full catalogue.
            "template_id": None,
        }
        for r in rows
    ]


__all__ = ["WorkKind", "list_my_work", "membership_for"]
