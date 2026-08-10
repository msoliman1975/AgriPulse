"""Action Center service — folding, grouping and dispatch.

Three derivations live here and nowhere else: the unified status (imported from
the repository, which owns the native mapping), the due bucket, and the
one-line "why".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.action_center.repository import ActionCenterRepository, unified_status
from app.modules.action_center.schemas import (
    ActionItem,
    ActionItemGroup,
    ActionItemListResponse,
    CellLocation,
    DispatchResponse,
    DispatchResultItem,
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


def to_item(row: dict[str, Any], *, now: datetime) -> ActionItem:
    bucket, due_date = derive_due(row, now=now)
    why, reasoning = derive_why(row)
    cell = None
    if row.get("cell_id") is not None:
        cell = CellLocation(
            cell_id=row["cell_id"],
            row=row.get("row_idx") or 0,
            col=row.get("col_idx") or 0,
            ordinal=row.get("ordinal"),
            total=row.get("total"),
            lat=row.get("lat"),
            lon=row.get("lon"),
            area_m2=row.get("area_m2"),
        )
    return ActionItem(
        id=row["id"],
        kind=row["kind"],
        status=unified_status(
            row["kind"],
            row["native_status"],
            has_assignee=row.get("assigned_membership_id") is not None,
        ),
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
        assigned_membership_id=row.get("assigned_membership_id"),
        activity_id=row.get("activity_id"),
        scheduled_date=row.get("scheduled_date"),
        why=why,
        reasoning=reasoning,
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
        keyed = {k: [] for k in _DUE_ORDER}
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
        cell_count=sum(1 for i in items if i.cell is not None),
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
            grouped_by=group_by,  # type: ignore[arg-type]
            groups=build_groups(items, group_by=group_by, responsible=responsible),
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
    ) -> DispatchResponse:
        """Send items to a person as board activities.

        Per-item SAVEPOINT: one bad item in a batch of 40 must not abort the
        transaction and take the other 39 with it — the pattern this codebase
        learned the hard way on cross-tenant loops.
        """
        from app.modules.plans.service import get_plans_service

        plans = get_plans_service(tenant_session=self._session)
        when = scheduled_date or date_type.today()
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


def get_action_center_service(*, tenant_session: AsyncSession) -> ActionCenterServiceImpl:
    return ActionCenterServiceImpl(tenant_session=tenant_session)
