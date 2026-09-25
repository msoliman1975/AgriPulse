"""A task worker listens to the events its tasks publish.

The API registered its subscribers when it built the app; a worker never
builds the app, so the scheduled decision-tree sweep, which runs in a worker,
opened alerts and recommendations and told nobody. Every message users ever
got came from an on-demand run in the API.

Pinned here:

  * a worker registers the run digest, the recommendation handler and a
    tree-only alert handler when it starts;
  * building the Celery app alone registers nothing, so unit tests that
    build it do not leave handlers on the shared bus;
  * a grid anomaly alert, also published in a worker, still reaches nobody
    (Mohamed, 2026-09-24), and a tree alert does;
  * scouting auto-dispatch is not registered in a worker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from app.modules.alerts.events import AlertOpenedV1
from app.modules.notifications import subscribers as notifications
from app.modules.recommendations.events import (
    EvaluationRunFinishedV1,
    RecommendationOpenedV1,
)
from app.modules.scouting import subscribers as scouting
from app.shared.eventbus.bus import EventBus
from workers.celery_factory import build_celery, register_event_subscribers


def _handlers(bus: EventBus, event_cls: type) -> set[object]:
    return {sub.handler for sub in bus.handlers_for(event_cls)}


def test_a_starting_worker_registers_the_three_handlers() -> None:
    bus = EventBus()
    with patch("app.shared.eventbus.get_default_bus", return_value=bus):
        register_event_subscribers()

    assert _handlers(bus, AlertOpenedV1) == {notifications._on_tree_alert_opened}
    assert _handlers(bus, RecommendationOpenedV1) == {notifications._on_recommendation_opened}
    assert _handlers(bus, EvaluationRunFinishedV1) == {notifications._on_evaluation_run_finished}


def test_registering_twice_does_not_double_the_handlers() -> None:
    bus = EventBus()
    notifications.register_worker_subscribers(bus)
    notifications.register_worker_subscribers(bus)
    assert len(list(bus.handlers_for(AlertOpenedV1))) == 1
    assert len(list(bus.handlers_for(EvaluationRunFinishedV1))) == 1


def test_scouting_dispatch_is_not_registered_in_a_worker() -> None:
    bus = EventBus()
    notifications.register_worker_subscribers(bus)
    assert scouting._on_recommendation_opened not in _handlers(bus, RecommendationOpenedV1)
    assert scouting._on_alert_opened not in _handlers(bus, AlertOpenedV1)


def test_building_the_app_registers_nothing() -> None:
    bus = EventBus()
    with patch("app.shared.eventbus.get_default_bus", return_value=bus):
        build_celery("light")
    assert list(bus.handlers_for(EvaluationRunFinishedV1)) == []


def _alert(rule_code: str) -> AlertOpenedV1:
    return AlertOpenedV1(
        alert_id=uuid4(),
        block_id=uuid4(),
        farm_id=uuid4(),
        rule_code=rule_code,
        severity="warning",
        diagnosis_en=None,
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        signal_snapshot=None,
        created_at=datetime.now(UTC),
        tenant_schema="tenant_x",
    )


def test_a_grid_alert_reaches_nobody_and_a_tree_alert_does() -> None:
    with patch.object(notifications, "_on_alert_opened") as fan_out:
        notifications._on_tree_alert_opened(_alert("grid:ndvi_spatial_anomaly"))
        assert fan_out.call_count == 0
        notifications._on_tree_alert_opened(_alert("tree:mango_water:findings=dry"))
        assert fan_out.call_count == 1
