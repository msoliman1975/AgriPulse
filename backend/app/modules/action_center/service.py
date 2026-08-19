"""Action Center service — folding, grouping and dispatch.

Three derivations live here and nowhere else: the unified status (imported from
the repository, which owns the native mapping), the due bucket, and the
one-line "why".
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from datetime import date as date_type
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.action_center.repository import ActionCenterRepository, unified_status
from app.modules.action_center.schemas import (
    ActionItem,
    ActionItemGroup,
    ActionItemListResponse,
    ActionItemMember,
    ActionItemMembersResponse,
    Aggregation,
    CellLocation,
    DispatchResponse,
    DispatchResultItem,
    Recurrence,
)
from app.shared.action_items import (
    GRID_GROUP_RULE_CODE,
    derive_recurrence,
    derive_spread,
)

# Recommendation action_type -> board activity_type. Mirrors the map the
# rec-schedule flow already uses; kept here rather than imported so a change to
# one is a deliberate change to both.
_ACTION_TO_ACTIVITY: dict[str, str] = {
    "irrigate": "irrigation",
    "fertilize": "fertilizing",
    "spray": "spraying",
    "scout": "observation",
    "prune": "pruning",
    "harvest_window": "harvesting",
    "inspect": "observation",
}

# Horizon -> bucket, for recommendations that carry structured guidance.
_HORIZON_BUCKET = {
    "immediate": "today",
    "short_term": "week",
    "long_term": "later",
    "monitoring": "monitoring",
}

_ACTION_LABELS = {
    "irrigate": "Irrigate",
    "fertilize": "Fertilize",
    "spray": "Spray",
    "scout": "Scout",
    "prune": "Prune",
    "harvest_window": "Harvest window",
    "inspect": "Inspect",
    "other": "Other",
    "no_action": "No action",
}
_DUE_LABELS = {
    "overdue": "Overdue",
    "today": "Today",
    "week": "This week",
    "later": "Later",
    "monitoring": "Ongoing / monitoring",
    "none": "No deadline",
}


def derive_due(  # noqa: PLR0911 - a priority ladder; each rung is one return
    row: dict[str, Any], *, now: datetime
) -> tuple[str, date_type | None]:
    """Bucket + concrete date for the "action date" grouping.

    Order of authority: a real scheduled date beats a deadline, a deadline
    beats a horizon, a horizon beats severity. Anything already past its
    deadline is overdue regardless of what the horizon claims — a monitoring
    item with an expired window is still late.
    """
    valid_until = row.get("valid_until")
    if valid_until is not None and valid_until < now:
        return "overdue", valid_until.date()

    scheduled = row.get("scheduled_date")
    if scheduled is not None:
        today = now.date()
        if scheduled < today:
            return "overdue", scheduled
        if scheduled == today:
            return "today", scheduled
        if scheduled <= today + timedelta(days=7):
            return "week", scheduled
        return "later", scheduled

    actions = row.get("actions") or {}
    if isinstance(actions, dict):
        for horizon in ("immediate", "short_term", "long_term", "monitoring"):
            if actions.get(horizon):
                bucket = _HORIZON_BUCKET[horizon]
                return bucket, (valid_until.date() if valid_until else None)

    if valid_until is not None:
        delta = valid_until - now
        if delta <= timedelta(days=1):
            return "today", valid_until.date()
        if delta <= timedelta(days=7):
            return "week", valid_until.date()
        return "later", valid_until.date()

    if row["kind"] == "alert":
        # An alert has no deadline of its own, so severity is the only signal
        # about when it needs looking at.
        return ({"critical": "today", "warning": "week"}.get(row["severity"], "later"), None)
    return "none", None


def derive_why(row: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The one-line "because …" plus the structured payload behind it.

    Recommendations keep the walk in ``tree_path``; the deciding fact is the
    last step that matched. Alerts have no path at all — only
    ``signal_snapshot`` — so their line is built from the snapshot. Neither
    depends on the evaluation trace, which is purged after 100 days.
    """
    path = row.get("reasoning_path")
    if isinstance(path, list) and path:
        for step in reversed(path):
            if not isinstance(step, dict):
                continue
            snap = step.get("condition_snapshot")
            if isinstance(snap, dict) and snap:
                left = snap.get("left") or snap.get("field") or snap.get("ref")
                op = snap.get("op") or snap.get("operator")
                right = snap.get("right") or snap.get("value")
                observed = snap.get("observed", snap.get("actual"))
                if left and op is not None:
                    line = f"{left} {op} {right}"
                    if observed is not None:
                        line = f"{line} — observed {observed}"
                    return line, {"source": "tree_path", "condition": snap}
            label = step.get("label_en")
            if label:
                return str(label), {"source": "tree_path", "step": step}

    snapshot = row.get("signal_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        parts = [
            f"{k} {v}"
            for k, v in list(snapshot.items())[:3]
            if not isinstance(v, dict | list) and v is not None
        ]
        if parts:
            return " · ".join(parts), {"source": "signal_snapshot", "snapshot": snapshot}

    detail = row.get("detail_en")
    if detail:
        return str(detail), {"source": "prescription"}
    return None, {}


def _cell_of(row: dict[str, Any]) -> CellLocation | None:
    if row.get("cell_id") is None:
        return None
    return CellLocation(
        cell_id=row["cell_id"],
        row=row.get("row_idx") or 0,
        col=row.get("col_idx") or 0,
        ordinal=row.get("ordinal"),
        total=row.get("total"),
        lat=row.get("lat"),
        lon=row.get("lon"),
        area_m2=row.get("area_m2"),
    )


def member_label(rule_code: str | None) -> str | None:
    """Name a member that is a measurement rather than a place.

    A grid-anomaly member's `rule_code` is `grid:<index>_spatial_anomaly`, and
    the only part a supervisor reads is the index. Returns None for anything
    else, including cell members, which are identified by where they are.
    """
    if not rule_code or not rule_code.startswith("grid:"):
        return None
    tail = rule_code.split(":", 1)[1]
    return tail.removesuffix("_spatial_anomaly") or None


def to_member(row: dict[str, Any]) -> ActionItemMember:
    return ActionItemMember(
        id=row["id"],
        cell=_cell_of(row),
        label=member_label(row.get("rule_code")),
        severity=row["severity"],
        native_status=row["native_status"],
        text_en=row.get("text_en"),
        text_ar=row.get("text_ar"),
        created_at=row["created_at"],
        last_seen_at=row.get("last_seen_at"),
        cleared_at=row.get("cleared_at"),
        occurrence_count=row.get("occurrence_count") or 1,
        day_streak=row.get("day_streak") or 1,
    )


def to_item(row: dict[str, Any], *, now: datetime) -> ActionItem:
    bucket, due_date = derive_due(row, now=now)
    why, reasoning = derive_why(row)
    cell = _cell_of(row)
    status = unified_status(
        row["kind"],
        row["native_status"],
        has_assignee=row.get("assigned_membership_id") is not None,
    )
    # "Acted" is anything past needs_action: dispatched, done, or knowingly set
    # aside. Escalation is about neglect, so an item somebody is already
    # dealing with never climbs past `recurring` no matter how long the tree
    # keeps agreeing with itself.
    recurrence = Recurrence(
        state=derive_recurrence(
            day_streak=row.get("day_streak") or 1,
            occurrence_count=row.get("occurrence_count") or 1,
            acted=status != "needs_action",
        ),
        occurrence_count=row.get("occurrence_count") or 1,
        day_streak=row.get("day_streak") or 1,
        first_seen_at=row.get("first_seen_at"),
        last_seen_at=row.get("last_seen_at"),
    )
    return ActionItem(
        id=row["id"],
        kind=row["kind"],
        status=status,
        native_status=row["native_status"],
        farm_id=row["farm_id"],
        block_id=row["block_id"],
        block_code=row["block_code"],
        block_name=row.get("block_name"),
        cell=cell,
        action_type=row.get("action_type"),
        severity=row["severity"],
        title_en=row["title_en"],
        title_ar=row.get("title_ar"),
        detail_en=row.get("detail_en"),
        detail_ar=row.get("detail_ar"),
        tree_code=row.get("tree_code"),
        tree_version=row.get("tree_version"),
        confidence=row.get("confidence"),
        created_at=row["created_at"],
        valid_until=row.get("valid_until"),
        due_bucket=bucket,
        due_date=due_date,
        responsible_membership_id=row.get("responsible_membership_id"),
        assigned_membership_id=row.get("assigned_membership_id"),
        activity_id=row.get("activity_id"),
        scheduled_date=row.get("scheduled_date"),
        why=why,
        reasoning=reasoning,
        aggregation=Aggregation(
            is_group=bool(row.get("is_group")),
            member_count=row.get("member_count") or 0,
            # A grid-anomaly parent aggregates indices, not places; everything
            # else aggregates the cells that fired.
            member_kind=("signal" if row.get("rule_code") == GRID_GROUP_RULE_CODE else "cell"),
            previous_member_count=row.get("previous_member_count") or 0,
            trend=derive_spread(
                is_group=bool(row.get("is_group")),
                member_count=row.get("member_count") or 0,
                previous_member_count=row.get("previous_member_count") or 0,
            ),
        ),
        recurrence=recurrence,
    )


_DUE_ORDER = ["overdue", "today", "week", "later", "monitoring", "none"]
_ACTION_ORDER = [
    "scout",
    "spray",
    "irrigate",
    "fertilize",
    "prune",
    "harvest_window",
    "inspect",
    "other",
]


def build_groups(
    items: list[ActionItem], *, group_by: str, responsible: dict[UUID, UUID | None]
) -> list[ActionItemGroup]:
    if group_by == "none":
        return [_group("all", "All items", items)]

    if group_by == "due":
        keyed: dict[str, list[ActionItem]] = {k: [] for k in _DUE_ORDER}
        for i in items:
            keyed[i.due_bucket].append(i)
        return [_group(k, _DUE_LABELS[k], v) for k, v in keyed.items() if v]

    if group_by == "block":
        by_block: dict[str, list[ActionItem]] = {}
        for i in items:
            by_block.setdefault(i.block_code, []).append(i)
        out = []
        for code in sorted(by_block):
            members = by_block[code]
            out.append(
                _group(
                    code,
                    f"Block {code}",
                    members,
                    responsible_membership_id=responsible.get(members[0].block_id),
                )
            )
        return out

    # action_type — unclassified last, since it is a data gap and not a verb.
    by_action: dict[str, list[ActionItem]] = {}
    for i in items:
        by_action.setdefault(i.action_type or "unclassified", []).append(i)
    ordered = [k for k in _ACTION_ORDER if k in by_action]
    ordered += [k for k in sorted(by_action) if k not in _ACTION_ORDER and k != "unclassified"]
    if "unclassified" in by_action:
        ordered.append("unclassified")
    return [
        _group(k, _ACTION_LABELS.get(k, k.replace("_", " ").title()), by_action[k]) for k in ordered
    ]


def _group(
    key: str,
    label: str,
    items: list[ActionItem],
    *,
    responsible_membership_id: UUID | None = None,
) -> ActionItemGroup:
    return ActionItemGroup(
        key=key,
        label=label,
        count=len(items),
        critical_count=sum(1 for i in items if i.severity == "critical"),
        block_count=len({i.block_id for i in items}),
        # Cells covered, not rows shown. An aggregate row stands for its whole
        # membership; counting it as one would report a quieter farm every time
        # the grouping did its job.
        cell_count=sum(
            (
                i.aggregation.member_count
                if i.aggregation.is_group
                else (1 if i.cell is not None else 0)
            )
            for i in items
        ),
        aggregate_count=sum(1 for i in items if i.aggregation.is_group),
        spreading_count=sum(1 for i in items if i.aggregation.trend == "spreading"),
        recurring_count=sum(1 for i in items if i.recurrence.state != "new"),
        responsible_membership_id=responsible_membership_id,
        items=items,
    )


class ActionCenterService(Protocol):
    async def list_items(self, **kwargs: Any) -> ActionItemListResponse: ...


class ActionCenterServiceImpl:
    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._session = tenant_session
        self._repo = ActionCenterRepository(tenant_session=tenant_session)

    async def list_items(
        self,
        *,
        farm_id: UUID,
        status: str | None = None,
        kinds: tuple[str, ...] = (),
        block_id: UUID | None = None,
        action_types: tuple[str, ...] = (),
        severities: tuple[str, ...] = (),
        assigned_membership_id: UUID | None = None,
        raised_from: datetime | None = None,
        raised_to: datetime | None = None,
        group_by: str = "action_type",
        limit: int = 500,
    ) -> ActionItemListResponse:
        rows = await self._repo.list_items(
            farm_id=farm_id,
            kinds=kinds,
            block_id=block_id,
            action_types=action_types,
            severities=severities,
            assigned_membership_id=assigned_membership_id,
            raised_from=raised_from,
            raised_to=raised_to,
            limit=limit,
        )
        now = datetime.now(UTC)
        all_items = [to_item(r, now=now) for r in rows]

        # Tab counts are computed BEFORE the status filter, so a tab never
        # advertises rows the active date range and filters have excluded.
        counts: dict[str, int] = {"needs_action": 0, "dispatched": 0, "done": 0, "dismissed": 0}
        for i in all_items:
            counts[i.status] = counts.get(i.status, 0) + 1
        counts["all"] = len(all_items)

        items = [i for i in all_items if status in (None, "all") or i.status == status]
        responsible = {r["block_id"]: r.get("responsible_membership_id") for r in rows}
        return ActionItemListResponse(
            total=len(items),
            status_counts=counts,
            grouped_by=group_by,
            groups=build_groups(items, group_by=group_by, responsible=responsible),
        )

    async def list_members(
        self, *, farm_id: UUID, item_id: UUID
    ) -> ActionItemMembersResponse | None:
        """The cells behind one aggregated item.

        Resolved through `get_item` first, which is also the authorization
        boundary: it is farm-scoped, so a member list cannot be used to read
        across farms by guessing a parent id.
        """
        parent = await self._repo.get_item(farm_id=farm_id, item_id=item_id)
        if parent is None:
            return None
        rows = await self._repo.list_members(kind=parent["kind"], parent_id=item_id)
        members = [to_member(r) for r in rows]
        return ActionItemMembersResponse(
            item_id=item_id,
            kind=parent["kind"],
            total=len(members),
            active=sum(1 for m in members if m.cleared_at is None),
            members=members,
        )

    async def dispatch(
        self,
        *,
        farm_id: UUID,
        item_ids: list[UUID],
        assigned_membership_id: UUID | None,
        scheduled_date: date_type | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        target: str = "board",
    ) -> DispatchResponse:
        """Send items to a person, as board activities or as scouting visits.

        Per-item SAVEPOINT: one bad item in a batch of 40 must not abort the
        transaction and take the other 39 with it — the pattern this codebase
        learned the hard way on cross-tenant loops.

        `target="scout"` opens a visit in the scouting module instead of a plan
        activity, which is what puts the item on a field worker's phone with a
        claim/start/submit lifecycle behind it. A plan activity has none of
        that, so the two destinations are genuinely different work, not two
        spellings of one.
        """
        from app.modules.plans.service import get_plans_service

        plans = get_plans_service(tenant_session=self._session)
        when = scheduled_date or date_type.today()
        # A scouting deadline is a moment, not a working day, so a date has to
        # become a time. End of the working day rather than midday: dispatching
        # something "for today" at 12:14 with a midday deadline puts it on the
        # scout's phone already overdue, which is how a queue teaches people to
        # ignore its red badges.
        due_by = datetime.combine(when, time(18, 0), tzinfo=UTC) if target == "scout" else None
        results: list[DispatchResultItem] = []
        fallback_cache: UUID | None = None

        for item_id in item_ids:
            row = await self._repo.get_item(farm_id=farm_id, item_id=item_id)
            if row is None:
                results.append(
                    DispatchResultItem(
                        item_id=item_id,
                        kind="recommendation",
                        activity_id=None,
                        assigned_membership_id=None,
                        error="not_found",
                    )
                )
                continue

            assignee = assigned_membership_id
            defaulted = False
            if assignee is None:
                assignee = await self._repo.block_responsible(block_id=row["block_id"])
                defaulted = assignee is not None
            if assignee is None:
                if fallback_cache is None:
                    fallback_cache = await self._repo.any_farm_member(farm_id=farm_id)
                assignee = fallback_cache
                defaulted = True

            if target == "scout":
                results.append(
                    await self._dispatch_to_scout(
                        farm_id=farm_id,
                        item_id=item_id,
                        row=row,
                        assignee_membership_id=assignee,
                        assignee_defaulted=defaulted,
                        note=notes,
                        due_by=due_by,
                        actor_user_id=actor_user_id,
                    )
                )
                continue

            savepoint = await self._session.begin_nested()
            try:
                activity = await plans.create_flat_activity(
                    farm_id=farm_id,
                    block_id=row["block_id"],
                    activity_type=_ACTION_TO_ACTIVITY.get(
                        row.get("action_type") or "", "observation"
                    ),
                    scheduled_date=when,
                    duration_days=1,
                    start_time=None,
                    product_name=None,
                    dosage=None,
                    notes=notes,
                    actor_user_id=actor_user_id,
                    tenant_schema=tenant_schema,
                    recommendation_id=item_id if row["kind"] == "recommendation" else None,
                    assigned_membership_id=assignee,
                )
                if row["kind"] == "alert":
                    await self._repo.link_alert_activity(
                        alert_id=item_id, activity_id=activity["id"]
                    )
                await savepoint.commit()
            except Exception as exc:
                await savepoint.rollback()
                results.append(
                    DispatchResultItem(
                        item_id=item_id,
                        kind=row["kind"],
                        activity_id=None,
                        assigned_membership_id=None,
                        error=type(exc).__name__,
                    )
                )
                continue

            results.append(
                DispatchResultItem(
                    item_id=item_id,
                    kind=row["kind"],
                    activity_id=activity["id"],
                    assigned_membership_id=assignee,
                    assignee_defaulted=defaulted,
                )
            )

        ok = sum(1 for r in results if r.error is None)
        return DispatchResponse(dispatched=ok, failed=len(results) - ok, results=results)

    async def _dispatch_to_scout(
        self,
        *,
        farm_id: UUID,
        item_id: UUID,
        row: dict[str, Any],
        assignee_membership_id: UUID | None,
        assignee_defaulted: bool,
        note: str | None,
        due_by: datetime | None,
        actor_user_id: UUID | None,
    ) -> DispatchResultItem:
        """One item onto a scout's phone. Never raises — returns the outcome."""
        from app.modules.scouting.service import get_scouting_service

        scouting = get_scouting_service(tenant_session=self._session)
        try:
            # Membership -> Keycloak subject. Leaving this untranslated is the
            # failure that looks like success: the row says assigned, the phone
            # shows nothing.
            subject = (
                await self._repo.membership_subject(membership_id=assignee_membership_id)
                if assignee_membership_id is not None
                else None
            )
            visit = await scouting.dispatch_from_action_item(
                farm_id=farm_id,
                block_id=row["block_id"],
                kind=row["kind"],
                item_id=item_id,
                title=row.get("title_en") or row.get("title_ar") or "Field check",
                severity=row.get("severity") or "info",
                note=note,
                assigned_to=subject,
                due_by=due_by,
                actor_user_id=actor_user_id,
            )
        except Exception as exc:
            return DispatchResultItem(
                item_id=item_id,
                kind=row["kind"],
                activity_id=None,
                assigned_membership_id=None,
                error=type(exc).__name__,
            )

        if visit is None:
            # A live visit already covers this item — normally one the routing
            # rules opened. Reported as a distinct outcome so the UI can say
            # "already with a scout" rather than claiming a fresh dispatch.
            return DispatchResultItem(
                item_id=item_id,
                kind=row["kind"],
                activity_id=None,
                visit_id=None,
                already_dispatched=True,
                assigned_membership_id=assignee_membership_id,
                assignee_defaulted=assignee_defaulted,
            )

        # If the membership had no Keycloak subject behind it the visit was
        # created unassigned, and saying otherwise would be a lie the UI then
        # repeats to the supervisor. Queued is the right outcome — any scout on
        # the farm can still claim it — but it must be reported as unassigned.
        landed_on = assignee_membership_id if visit.get("assigned_to") is not None else None
        return DispatchResultItem(
            item_id=item_id,
            kind=row["kind"],
            activity_id=None,
            visit_id=visit["id"],
            assigned_membership_id=landed_on,
            assignee_defaulted=assignee_defaulted and landed_on is not None,
        )


def get_action_center_service(*, tenant_session: AsyncSession) -> ActionCenterServiceImpl:
    return ActionCenterServiceImpl(tenant_session=tenant_session)
