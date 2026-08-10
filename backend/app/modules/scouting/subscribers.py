"""Auto-dispatch: turn a recommendation or an alert into a scouting visit.

This is the middle of the loop the platform was always missing — the tree
already says "go and look", and now something acts on it.

Why sync SQLAlchemy on its own connection: same reason as
``notifications/subscribers.py``. The publisher's transaction has not committed
when a sync handler runs, so this cannot read the recommendation or alert row —
everything it needs must come off the event payload, which is precisely why
both events carry content snapshots.

**No handler here may raise.** Sync handler exceptions propagate and roll back
the publishing transaction, so a bug in dispatch would destroy the alert that
triggered it. Every failure path logs and returns. A missing visit is a
nuisance; a lost alert is a field problem nobody ever hears about.

Two paths, deliberately asymmetric:

*Recommendations* dispatch automatically when the tree says ``action_type:
scout`` — the tree has already decided this needs a human, and it carries the
deadline in ``parameters.within_hours``.

*Alerts* dispatch **only where a routing rule explicitly sets
``min_severity``**. `AlertOpenedV1` has no ``action_type`` to key on, and it is
also published by the grid anomaly sweep, so an opt-out design would raise a
visit for every grid alert on every block from the day it shipped. Opt-in means
a farm gets alert-driven scouting when somebody asks for it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.alerts.events import AlertOpenedV1
from app.modules.recommendations.events import RecommendationOpenedV1
from app.modules.scouting.events import ScoutingVisitAssignedV1
from app.shared.db.session import sanitize_tenant_schema
from app.shared.eventbus import EventBus, get_default_bus

_log = get_logger(__name__)

# Ascending urgency. `min_severity` on a rule means "this severity or worse".
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

# Used when neither the tree nor the rule says when the visit is due. Chosen to
# match the warning branch of scout_for_stress_v1 rather than invented: a visit
# with no deadline never appears overdue and quietly stops being work.
_FALLBACK_DUE_HOURS = 72


def _session_factory() -> Any:
    # Imported lazily and delegated to notifications' factory so both
    # subscriber families share the same NullPool connection policy — a
    # previous handler's aborted transaction must never leak into this one.
    from app.modules.notifications.subscribers import _session_factory as factory

    return factory()


def _resolve_rule(
    session: Session, *, farm_id: UUID, block_id: UUID, origin: str
) -> dict[str, Any] | None:
    """Most-specific-first: block → farm → tenant-wide."""
    row = (
        session.execute(
            text(
                """
            SELECT * FROM scouting_routing_rules
             WHERE deleted_at IS NULL AND is_active
               AND (block_id = :block_id OR block_id IS NULL)
               AND (farm_id = :farm_id OR farm_id IS NULL)
               AND (origin = :origin OR origin IS NULL)
             ORDER BY (block_id IS NULL), (farm_id IS NULL), (origin IS NULL)
             LIMIT 1
            """
            ),
            {"farm_id": farm_id, "block_id": block_id, "origin": origin},
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _create_visit(session: Session, *, values: dict[str, Any]) -> UUID | None:
    """Insert a visit, treating a duplicate as success.

    The partial UNIQUEs on ``recommendation_id`` / ``alert_id`` are what stop
    the daily evaluator queueing the same visit every morning, and what makes a
    redelivered event harmless. Hitting one means the work is already dispatched
    — that is the desired end state, not an error.
    """
    # JSONB columns need an explicit cast: psycopg does not adapt a bare dict
    # through `text()`. Use CAST(:x AS jsonb) — the postfix `:x::jsonb` form
    # is parsed as a bind-parameter marker by SQLAlchemy and breaks here.
    values = {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in values.items()}
    cols = ", ".join(values)
    placeholders = ", ".join(
        f"CAST(:{c} AS jsonb)" if c == "reason_snapshot" else f":{c}" for c in values
    )
    try:
        with session.begin_nested():
            return session.execute(
                text(
                    f"INSERT INTO scouting_visits ({cols}) "  # noqa: S608 - keys are module-controlled
                    f"VALUES ({placeholders}) RETURNING id"
                ),
                values,
            ).scalar_one()
    except IntegrityError:
        _log.info(
            "scouting_visit_already_dispatched",
            recommendation_id=str(values.get("recommendation_id")),
            alert_id=str(values.get("alert_id")),
        )
        return None


def _assignment_for(rule: dict[str, Any] | None) -> tuple[str, UUID | None]:
    """Decide triage vs auto.

    An `auto` rule whose assignee cannot be resolved **degrades to triage**
    rather than dropping the visit: a visit waiting in a queue is a nuisance, a
    visit that silently never existed is a missed field problem.
    """
    if rule is None or rule["mode"] != "auto":
        return "queued", None
    assignee = rule["default_assignee"] or rule["fallback_assignee"]
    if assignee is None:
        _log.warning("scouting_auto_rule_without_assignee", rule_id=str(rule["id"]))
        return "queued", None
    return "assigned", assignee


def _dispatch(
    *,
    tenant_schema: str | None,
    farm_id: UUID | None,
    block_id: UUID,
    origin: str,
    title: str,
    severity: str,
    values: dict[str, Any],
    due_hours: int | None,
    log_key: str,
) -> None:
    """Shared tail of both paths: resolve the rule, then insert."""
    if tenant_schema is None or farm_id is None:
        _log.warning(f"{log_key}_missing_context", block_id=str(block_id))
        return
    try:
        sanitize_tenant_schema(tenant_schema)
    except ValueError:
        _log.warning(f"{log_key}_invalid_tenant_schema", schema=tenant_schema)
        return

    factory = _session_factory()
    with factory() as session:
        session.execute(text(f"SET LOCAL search_path TO {tenant_schema}, public"))
        rule = _resolve_rule(session, farm_id=farm_id, block_id=block_id, origin=origin)
        status, assignee = _assignment_for(rule)

        hours = due_hours or (rule or {}).get("default_due_hours") or _FALLBACK_DUE_HOURS
        row: dict[str, Any] = {
            "farm_id": farm_id,
            "block_id": block_id,
            "origin": origin,
            "title": title[:200],
            "severity": severity,
            "due_by": datetime.now(UTC) + timedelta(hours=int(hours)),
            "status": status,
            "template_id": (rule or {}).get("template_id"),
            **values,
        }
        if assignee is not None:
            # assigned_by stays NULL: a rule did this, not a person, and the
            # supervisor board reads that distinction.
            row["assigned_to"] = assignee
            row["assigned_at"] = datetime.now(UTC)

        visit_id = _create_visit(session, values=row)
        if visit_id is None:
            return
        session.commit()
        _log.info(log_key, visit_id=str(visit_id), status=status, block_id=str(block_id))

        # A rule that assigned the visit has to say so, or the scout it named
        # never learns the work exists. Published after commit: the visit is
        # already durable, so a notification failure cannot undo it.
        if assignee is not None:
            try:
                get_default_bus().publish(
                    ScoutingVisitAssignedV1(
                        visit_id=visit_id,
                        farm_id=farm_id,
                        block_id=block_id,
                        assignee_user_id=assignee,
                        assigned_by_user_id=None,
                        origin=origin,
                        severity=severity,
                        priority=str(row.get("priority") or "medium"),
                        title=str(row["title"]),
                        due_by=row.get("due_by"),
                        assigned_at=datetime.now(UTC),
                        tenant_schema=tenant_schema,
                    )
                )
            except Exception:
                _log.exception("visit_assignment_announce_failed", visit_id=str(visit_id))


def _on_recommendation_opened(event: RecommendationOpenedV1) -> None:
    """A tree asked for a scouting visit."""
    try:
        if event.action_type != "scout":
            return
        # Per-cell P2: a cell-scoped tree opens one recommendation per grid
        # cell. Dispatching each would put 36 visits on one scout for one
        # block. The sweep publishes a single block-level digest
        # (cell_id=None, zone_count set) and that is the one we act on — the
        # map still shows which zones were flagged.
        if event.cell_id is not None:
            return

        params = event.parameters or {}
        within_hours = params.get("within_hours")
        priority = str(params.get("priority") or "medium")
        title = (event.text_en or f"Scout {event.tree_code}").strip().split("\n")[0]

        _dispatch(
            tenant_schema=event.tenant_schema,
            farm_id=event.farm_id,
            block_id=event.block_id,
            origin="recommendation",
            title=title,
            severity=event.severity,
            due_hours=int(within_hours) if within_hours else None,
            values={
                "recommendation_id": event.recommendation_id,
                "priority": priority if priority in ("low", "medium", "high") else "medium",
                # The reason a scout reads in the field, snapshotted so it
                # cannot drift or disappear underneath them.
                "reason_snapshot": _reason_snapshot(event),
            },
            log_key="scouting_visit_from_recommendation",
        )
    except Exception:
        _log.exception("scouting_dispatch_failed", recommendation_id=str(event.recommendation_id))


def _on_alert_opened(event: AlertOpenedV1) -> None:
    """An alert fired — dispatch only where a rule opted this farm in."""
    try:
        if event.cell_id is not None:
            return
        if event.tenant_schema is None or event.farm_id is None:
            return
        try:
            sanitize_tenant_schema(event.tenant_schema)
        except ValueError:
            _log.warning("scouting_alert_invalid_tenant_schema", schema=event.tenant_schema)
            return

        factory = _session_factory()
        with factory() as session:
            session.execute(text(f"SET LOCAL search_path TO {event.tenant_schema}, public"))
            rule = _resolve_rule(
                session, farm_id=event.farm_id, block_id=event.block_id, origin="alert"
            )
        # Opt-in, and deliberately so. AlertOpenedV1 carries no action_type to
        # key on and is also published by the grid anomaly sweep, so dispatching
        # by default would raise a visit for every grid alert on every block.
        if rule is None or rule["min_severity"] is None:
            return
        if _SEVERITY_RANK.get(event.severity, 0) < _SEVERITY_RANK.get(rule["min_severity"], 0):
            return

        title = (event.diagnosis_en or f"Alert: {event.rule_code}").strip().split("\n")[0]
        _dispatch(
            tenant_schema=event.tenant_schema,
            farm_id=event.farm_id,
            block_id=event.block_id,
            origin="alert",
            title=title,
            severity=event.severity,
            # AlertOpenedV1 has no parameters, so the deadline can only come
            # from the rule (or the fallback).
            due_hours=None,
            values={
                "alert_id": event.alert_id,
                "priority": "high" if event.severity == "critical" else "medium",
                "reason_snapshot": {
                    "rule_code": event.rule_code,
                    "diagnosis_en": event.diagnosis_en,
                    "diagnosis_ar": event.diagnosis_ar,
                    "signal_snapshot": event.signal_snapshot,
                },
            },
            log_key="scouting_visit_from_alert",
        )
    except Exception:
        _log.exception("scouting_dispatch_failed", alert_id=str(event.alert_id))


def _reason_snapshot(event: RecommendationOpenedV1) -> dict[str, Any]:
    return {
        "tree_code": event.tree_code,
        "tree_version": event.tree_version,
        "text_en": event.text_en,
        "text_ar": event.text_ar,
        "parameters": event.parameters,
        "evaluation_snapshot": event.evaluation_snapshot,
        "zone_count": event.zone_count,
    }


def register_subscribers(bus: EventBus) -> None:
    """Idempotent registration — re-registering in tests must not double-fire."""
    if not any(
        sub.handler is _on_recommendation_opened for sub in bus.handlers_for(RecommendationOpenedV1)
    ):
        bus.register(RecommendationOpenedV1, _on_recommendation_opened, mode="sync")
    if not any(sub.handler is _on_alert_opened for sub in bus.handlers_for(AlertOpenedV1)):
        bus.register(AlertOpenedV1, _on_alert_opened, mode="sync")


__all__ = ["register_subscribers"]
