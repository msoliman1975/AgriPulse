"""Scouting service — the visit lifecycle and dispatch rules.

The state machine is enforced here and re-asserted in SQL: every transition
names the states it may run from, and the repository applies it as a
conditional UPDATE. Two scouts claiming the same visit therefore cannot both
succeed, regardless of how the requests interleave.

    queued ──assign──> assigned ──accept──> accepted ──start──> in_progress
      ▲                    │                                        │
      └──── decline ───────┘                                     submit
                                                                    ▼
                                                                completed
    side paths: cancelled (supervisor withdrew) · expired (past due_by, swept)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.scouting.errors import (
    InvalidVisitTransitionError,
    NotVisitAssigneeError,
    ScoutingVisitNotFoundError,
    VisitAlreadyClaimedError,
)
from app.modules.scouting.events import ScoutingVisitAssignedV1
from app.modules.scouting.repository import ScoutingRepository
from app.shared.eventbus import get_default_bus

# A visit is still "open" in any of these — the states a sweep or a supervisor
# may still act on.
OPEN_STATUSES: tuple[str, ...] = ("queued", "assigned", "accepted", "in_progress")

# A triaged item carries a severity but no priority of its own. Mapping keeps
# the scout's list ordered by the same urgency the supervisor saw.
_SEVERITY_PRIORITY: dict[str, str] = {"critical": "high", "warning": "medium", "info": "low"}


class ScoutingService:
    def __init__(self, *, tenant_session: AsyncSession, tenant_schema: str | None = None) -> None:
        self._repo = ScoutingRepository(tenant_session)
        self._session = tenant_session
        self._tenant_schema = tenant_schema
        self._log = get_logger(__name__)

    def _announce_assignment(self, visit: dict[str, Any]) -> None:
        """Tell the assignee their phone should ring.

        Published, not called directly, so notifications stays the only
        module that knows how a person is reached. Publishing is
        best-effort: a bus failure must not undo an assignment that the
        supervisor has already been told succeeded.
        """
        if visit.get("assigned_to") is None:
            return
        try:
            get_default_bus().publish(
                ScoutingVisitAssignedV1(
                    visit_id=visit["id"],
                    farm_id=visit["farm_id"],
                    block_id=visit["block_id"],
                    cell_id=visit.get("cell_id"),
                    assignee_user_id=visit["assigned_to"],
                    assigned_by_user_id=visit.get("assigned_by"),
                    origin=str(visit["origin"]),
                    severity=str(visit["severity"]),
                    priority=str(visit["priority"]),
                    title=str(visit["title"]),
                    instruction=visit.get("instruction"),
                    due_by=visit.get("due_by"),
                    assigned_at=visit.get("assigned_at") or datetime.now(UTC),
                    tenant_schema=self._tenant_schema,
                )
            )
        except Exception:
            self._log.exception("visit_assignment_announce_failed", visit_id=str(visit["id"]))

    # ---- Reads -------------------------------------------------------------

    async def list_visits(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        assigned_to: UUID | None = None,
        statuses: tuple[str, ...] = (),
        claimable: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        # "Assigned to me" is a work queue, not a history: without a status
        # filter a cancelled or completed visit stays on the scout's list
        # forever, and they walk out to do work that was called off. `claimable`
        # already pins status='queued', which is why only this path was exposed.
        # `expired` is deliberately included — it is a flag, not a closure, and
        # such a visit is still actionable (cancel accepts it too).
        # An explicit `statuses` still wins, so a supervisor can ask for history.
        if assigned_to is not None and not statuses and not claimable:
            statuses = (*OPEN_STATUSES, "expired")
        return await self._repo.list_visits(
            farm_id=farm_id,
            block_id=block_id,
            assigned_to=assigned_to,
            statuses=statuses,
            claimable=claimable,
        )

    async def get_visit(self, *, visit_id: UUID) -> dict[str, Any]:
        visit = await self._repo.get_visit(visit_id=visit_id)
        if visit is None:
            raise ScoutingVisitNotFoundError(visit_id)
        return visit

    # ---- Creation ----------------------------------------------------------

    async def dispatch_ad_hoc(
        self,
        *,
        farm_id: UUID,
        payload: Any,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """A supervisor saw something and wants eyes on it.

        The only origin that carries human instructions, so `title` falls back
        to the first line of what they wrote rather than a generated string —
        the scout should see a sentence a colleague typed, not a template.
        """
        due_by = (
            datetime.now(UTC) + timedelta(hours=payload.due_within_hours)
            if payload.due_within_hours
            else None
        )
        title = payload.title or payload.instruction.strip().split("\n")[0][:200]
        values: dict[str, Any] = {
            "farm_id": farm_id,
            "block_id": payload.block_id,
            "cell_id": payload.cell_id,
            "origin": "ad_hoc",
            "title": title,
            "instruction": payload.instruction,
            "severity": payload.severity,
            "priority": payload.priority,
            "due_by": due_by,
            "template_id": payload.template_id,
            "created_by": actor_user_id,
        }
        if payload.assigned_to is not None:
            values.update(
                status="assigned",
                assigned_to=payload.assigned_to,
                assigned_by=actor_user_id,
                assigned_at=datetime.now(UTC),
            )
        if payload.lat is not None and payload.lon is not None:
            values.update(lat=payload.lat, lon=payload.lon)
        visit = await self._repo.insert_visit(values=values)
        self._announce_assignment(visit)
        return visit

    async def dispatch_from_action_item(
        self,
        *,
        farm_id: UUID,
        block_id: UUID,
        kind: str,
        item_id: UUID,
        title: str,
        severity: str,
        note: str | None,
        assigned_to: UUID | None,
        due_by: datetime | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any] | None:
        """A supervisor triaged a rec/alert in the Action Center and sent it to a scout.

        Origin is the item's own kind rather than `ad_hoc`, so the partial
        UNIQUE on recommendation_id/alert_id dedups against a visit the
        auto-dispatch subscriber may already have opened: triaging something
        the routing rules already sent must not put the same walk on a scout's
        list twice. Returns None when a live visit already covers the item, so
        the caller can report "already dispatched" rather than an error.

        The supervisor's note rides in `reason_snapshot`, not `instruction` —
        that column is CHECK-constrained to ad_hoc, and relaxing it would let a
        machine-generated visit carry words no human typed.
        """
        values: dict[str, Any] = {
            "farm_id": farm_id,
            "block_id": block_id,
            "origin": kind,
            ("recommendation_id" if kind == "recommendation" else "alert_id"): item_id,
            "title": title[:200],
            "severity": severity,
            "priority": _SEVERITY_PRIORITY.get(severity, "medium"),
            "due_by": due_by,
            "status": "queued",
            "reason_snapshot": {
                "source": "action_center",
                **({"note": note} if note else {}),
            },
            "created_by": actor_user_id,
        }
        if assigned_to is not None:
            values.update(
                status="assigned",
                assigned_to=assigned_to,
                assigned_by=actor_user_id,
                assigned_at=datetime.now(UTC),
            )
        # Nested so a duplicate does not poison the caller's transaction — the
        # Action Center dispatches in batches and one already-covered item must
        # not take the other thirty-nine with it.
        savepoint = await self._session.begin_nested()
        try:
            visit = await self._repo.insert_visit(values=values)
            await savepoint.commit()
        except IntegrityError:
            await savepoint.rollback()
            return None
        self._announce_assignment(visit)
        return visit

    async def create_self_initiated(
        self, *, farm_id: UUID, payload: Any, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        """The scout is already standing there, so skip the queue entirely."""
        now = datetime.now(UTC)
        return await self._repo.insert_visit(
            values={
                "farm_id": farm_id,
                "block_id": payload.block_id,
                "cell_id": payload.cell_id,
                "origin": "self_initiated",
                "title": payload.title or "Field observation",
                "severity": "info",
                "priority": "low",
                "status": "in_progress",
                "assigned_to": actor_user_id,
                "assigned_at": now,
                "accepted_at": now,
                "started_at": now,
                "template_id": payload.template_id,
                "created_by": actor_user_id,
            }
        )

    # ---- Lifecycle ---------------------------------------------------------

    async def claim(self, *, visit_id: UUID, actor_user_id: UUID | None) -> dict[str, Any]:
        """Take an unassigned visit. Losing the race is a 409, not a silent no-op."""
        now = datetime.now(UTC)
        updated = await self._repo.apply_transition(
            visit_id=visit_id,
            sets={
                "status": "accepted",
                "assigned_to": actor_user_id,
                "assigned_at": now,
                "accepted_at": now,
            },
            expected_statuses=("queued",),
        )
        if updated is None:
            await self._assert_exists(visit_id)
            raise VisitAlreadyClaimedError()
        return updated

    async def accept(self, *, visit_id: UUID, actor_user_id: UUID | None) -> dict[str, Any]:
        await self._assert_assignee(visit_id, actor_user_id)
        return await self._transition(
            visit_id,
            sets={"status": "accepted", "accepted_at": datetime.now(UTC)},
            expected=("assigned",),
            action="accepted",
        )

    async def decline(
        self, *, visit_id: UUID, reason: str, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        """Refusing work is legitimate; refusing it silently is not.

        The visit returns to the queue with the reason attached so a supervisor
        sees *why* rather than watching it quietly go stale.
        """
        await self._assert_assignee(visit_id, actor_user_id)
        return await self._transition(
            visit_id,
            sets={
                "status": "queued",
                "assigned_to": None,
                "assigned_at": None,
                "accepted_at": None,
                "decline_reason": reason,
            },
            expected=("assigned", "accepted"),
            action="declined",
        )

    async def start(self, *, visit_id: UUID, actor_user_id: UUID | None) -> dict[str, Any]:
        await self._assert_assignee(visit_id, actor_user_id)
        visit = await self.get_visit(visit_id=visit_id)
        if visit["status"] == "in_progress":
            return visit  # idempotent: the app calls this on arrival
        return await self._transition(
            visit_id,
            sets={"status": "in_progress", "started_at": datetime.now(UTC)},
            expected=("accepted",),
            action="started",
        )

    async def submit(
        self, *, visit_id: UUID, payload: Any, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        """Close the visit with an outcome.

        Replaying the same `idempotency_key` returns the original result rather
        than erroring — a scout on a bad connection will retry, and a retry must
        not look like a failure.
        """
        if payload.idempotency_key:
            existing = await self._repo.find_by_idempotency_key(key=payload.idempotency_key)
            if existing is not None:
                return existing
        await self._assert_assignee(visit_id, actor_user_id)
        return await self._transition(
            visit_id,
            sets={
                "status": "completed",
                "outcome": payload.outcome,
                "summary_note": payload.summary_note,
                "observation_group_id": payload.observation_group_id,
                "idempotency_key": payload.idempotency_key,
                "completed_at": datetime.now(UTC),
                "completed_by": actor_user_id,
            },
            expected=("accepted", "in_progress"),
            action="submitted",
        )

    # ---- Supervisor actions ------------------------------------------------

    async def assign(
        self, *, visit_id: UUID, assignee_user_id: UUID, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        visit = await self._transition(
            visit_id,
            sets={
                "status": "assigned",
                "assigned_to": assignee_user_id,
                "assigned_by": actor_user_id,
                "assigned_at": datetime.now(UTC),
                "accepted_at": None,
            },
            # Reassignment is allowed right up until the scout starts walking.
            expected=("queued", "assigned", "accepted", "expired"),
            action="assigned",
        )
        self._announce_assignment(visit)
        return visit

    async def cancel(self, *, visit_id: UUID, actor_user_id: UUID | None) -> dict[str, Any]:
        del actor_user_id
        return await self._transition(
            visit_id,
            sets={"status": "cancelled"},
            expected=(*OPEN_STATUSES, "expired"),
            action="cancelled",
        )

    # ---- Routing rules -----------------------------------------------------

    async def list_rules(self, *, farm_id: UUID | None = None) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_rules(farm_id=farm_id)

    async def upsert_rule(self, *, payload: Any, actor_user_id: UUID | None) -> dict[str, Any]:
        return await self._repo.upsert_rule(
            values={
                "farm_id": payload.farm_id,
                "block_id": payload.block_id,
                "origin": payload.origin,
                "min_severity": payload.min_severity,
                "mode": payload.mode,
                "default_assignee": payload.default_assignee,
                "fallback_assignee": payload.fallback_assignee,
                "template_id": payload.template_id,
                "default_due_hours": payload.default_due_hours,
                "is_active": payload.is_active,
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            }
        )

    async def resolve_assignment(
        self, *, farm_id: UUID, block_id: UUID, origin: str
    ) -> tuple[str, UUID | None, dict[str, Any] | None]:
        """Decide how a machine-created visit should be routed.

        Returns `(mode, assignee, rule)`. A rule in `auto` mode whose assignee
        cannot be resolved **degrades to triage** rather than dropping the
        visit: a visit sitting in a queue is a nuisance, a visit that silently
        never existed is a missed field problem.
        """
        rule = await self._repo.resolve_rule(farm_id=farm_id, block_id=block_id, origin=origin)
        if rule is None:
            return "triage", None, None
        if rule["mode"] != "auto":
            return "triage", None, rule
        assignee = rule["default_assignee"] or rule["fallback_assignee"]
        if assignee is None:
            self._log.warning(
                "scouting_auto_rule_without_assignee",
                rule_id=str(rule["id"]),
                farm_id=str(farm_id),
                block_id=str(block_id),
            )
            return "triage", None, rule
        return "auto", assignee, rule

    # ---- Internals ---------------------------------------------------------

    async def _assert_exists(self, visit_id: UUID) -> dict[str, Any]:
        return await self.get_visit(visit_id=visit_id)

    async def _assert_assignee(self, visit_id: UUID, actor_user_id: UUID | None) -> None:
        visit = await self.get_visit(visit_id=visit_id)
        if visit["assigned_to"] is not None and visit["assigned_to"] != actor_user_id:
            raise NotVisitAssigneeError()

    async def _transition(
        self,
        visit_id: UUID,
        *,
        sets: dict[str, Any],
        expected: tuple[str, ...],
        action: str,
    ) -> dict[str, Any]:
        updated = await self._repo.apply_transition(
            visit_id=visit_id, sets=sets, expected_statuses=expected
        )
        if updated is None:
            current = await self._assert_exists(visit_id)
            raise InvalidVisitTransitionError(current=str(current["status"]), action=action)
        return updated


def get_scouting_service(
    *, tenant_session: AsyncSession, tenant_schema: str | None = None
) -> ScoutingService:
    return ScoutingService(tenant_session=tenant_session, tenant_schema=tenant_schema)
