"""Action Center derivations — status folding, due buckets, why-lines, grouping.

These four functions are the whole product logic of the screen: everything
else is a SQL union and a Pydantic shape. They are pure, so they get tested
without a database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.action_center.repository import unified_status
from app.modules.action_center.service import (
    build_groups,
    derive_due,
    derive_why,
    to_item,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


# ---------- status folding ------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "native", "expected"),
    [
        ("recommendation", "open", "needs_action"),
        ("recommendation", "applied", "done"),
        ("recommendation", "dismissed", "dismissed"),
        ("recommendation", "deferred", "dismissed"),
        ("recommendation", "expired", "dismissed"),
        ("alert", "open", "needs_action"),
        ("alert", "acknowledged", "dispatched"),
        ("alert", "resolved", "done"),
        ("alert", "snoozed", "dismissed"),
    ],
)
def test_native_states_fold_onto_the_tab_vocabulary(kind, native, expected):
    assert unified_status(kind, native, has_assignee=False) == expected


def test_an_assignee_moves_an_open_item_to_dispatched():
    # The rec table still says `open` — there is no native state for "sent to
    # someone" — so the assignee is what distinguishes the two tabs.
    assert unified_status("recommendation", "open", has_assignee=True) == "dispatched"


def test_an_assignee_does_not_resurrect_a_closed_item():
    # Dispatching then applying must land in Done, not back in Dispatched.
    assert unified_status("recommendation", "applied", has_assignee=True) == "done"
    assert unified_status("alert", "resolved", has_assignee=True) == "done"
    assert unified_status("alert", "snoozed", has_assignee=True) == "dismissed"


def test_an_unknown_native_state_does_not_vanish():
    # A state added to one table and not to the map must still be visible to a
    # supervisor rather than silently dropping out of every tab.
    assert unified_status("alert", "escalated", has_assignee=False) == "needs_action"


# ---------- due buckets ---------------------------------------------------


def _row(**over):
    base = {
        "kind": "recommendation",
        "severity": "warning",
        "valid_until": None,
        "scheduled_date": None,
        "actions": {},
    }
    base.update(over)
    return base


def test_a_past_deadline_is_overdue():
    bucket, due = derive_due(_row(valid_until=NOW - timedelta(days=2)), now=NOW)
    assert bucket == "overdue"
    assert due == date(2026, 8, 7)


def test_a_past_deadline_beats_a_monitoring_horizon():
    # A monitoring item whose window has closed is late, not "ongoing".
    row = _row(valid_until=NOW - timedelta(hours=1), actions={"monitoring": [{"text_en": "x"}]})
    assert derive_due(row, now=NOW)[0] == "overdue"


def test_a_scheduled_date_outranks_a_horizon():
    row = _row(scheduled_date=date(2026, 8, 9), actions={"long_term": [{"text_en": "x"}]})
    assert derive_due(row, now=NOW) == ("today", date(2026, 8, 9))


def test_a_scheduled_date_in_the_past_is_overdue():
    assert derive_due(_row(scheduled_date=date(2026, 8, 1)), now=NOW)[0] == "overdue"


@pytest.mark.parametrize(
    ("horizon", "bucket"),
    [
        ("immediate", "today"),
        ("short_term", "week"),
        ("long_term", "later"),
        ("monitoring", "monitoring"),
    ],
)
def test_each_horizon_maps_to_its_bucket(horizon, bucket):
    row = _row(actions={horizon: [{"text_en": "do it"}]})
    assert derive_due(row, now=NOW)[0] == bucket


def test_an_empty_horizon_list_is_not_a_horizon():
    # `{"immediate": []}` means the leaf declared the key and put nothing in
    # it; treating that as "due today" would invent urgency.
    assert derive_due(_row(actions={"immediate": []}), now=NOW)[0] == "none"


def test_a_deadline_without_a_horizon_buckets_by_distance():
    assert derive_due(_row(valid_until=NOW + timedelta(hours=6)), now=NOW)[0] == "today"
    assert derive_due(_row(valid_until=NOW + timedelta(days=3)), now=NOW)[0] == "week"
    assert derive_due(_row(valid_until=NOW + timedelta(days=40)), now=NOW)[0] == "later"


def test_an_alert_falls_back_to_severity():
    assert derive_due(_row(kind="alert", severity="critical"), now=NOW)[0] == "today"
    assert derive_due(_row(kind="alert", severity="warning"), now=NOW)[0] == "week"
    assert derive_due(_row(kind="alert", severity="info"), now=NOW)[0] == "later"


def test_a_recommendation_with_nothing_to_go_on_has_no_deadline():
    # Deliberately NOT "today" — a bucket invented from no evidence is how a
    # queue becomes noise the user learns to ignore.
    assert derive_due(_row(), now=NOW) == ("none", None)


# ---------- why lines -----------------------------------------------------


def test_why_uses_the_last_matched_condition_of_the_tree_path():
    path = [
        {"node_id": "n1", "condition_snapshot": {"left": "crop", "op": "eq", "right": "mango"}},
        {
            "node_id": "n2",
            "condition_snapshot": {
                "left": "ndvi_mean",
                "op": "<",
                "right": 0.45,
                "observed": 0.32,
            },
        },
    ]
    why, meta = derive_why({"reasoning_path": path})
    assert why == "ndvi_mean < 0.45 — observed 0.32"
    assert meta["source"] == "tree_path"


def test_why_falls_back_to_a_step_label_when_the_snapshot_is_empty():
    path = [{"node_id": "n1", "label_en": "Canopy stress detected", "condition_snapshot": {}}]
    why, meta = derive_why({"reasoning_path": path})
    assert why == "Canopy stress detected"


def test_an_alert_gets_a_why_from_its_signal_snapshot():
    # Alerts have no tree_path at all — this is the whole reason the alert
    # reasoning section could not just reuse the recommendation code path.
    why, meta = derive_why(
        {"reasoning_path": None, "signal_snapshot": {"soil_ec": 4.6, "readings": 3}}
    )
    assert why == "soil_ec 4.6 · readings 3"
    assert meta["source"] == "signal_snapshot"


def test_nested_snapshot_values_are_skipped_not_stringified():
    why, _ = derive_why({"signal_snapshot": {"nested": {"a": 1}, "list": [1, 2], "soil_ec": 4.6}})
    assert why == "soil_ec 4.6"


def test_why_is_none_when_there_is_nothing_to_say():
    why, meta = derive_why({"reasoning_path": None, "signal_snapshot": None})
    assert why is None
    assert meta == {}


# ---------- grouping ------------------------------------------------------


def _item(**over):
    block_id = over.pop("block_id", uuid4())
    row = {
        "id": uuid4(),
        "kind": "recommendation",
        "native_status": "open",
        "farm_id": uuid4(),
        "block_id": block_id,
        "block_code": over.pop("block_code", "B-01"),
        "block_name": None,
        "cell_id": None,
        "action_type": over.pop("action_type", "scout"),
        "severity": over.pop("severity", "warning"),
        "title_en": "t",
        "title_ar": None,
        "tree_code": "t1",
        "tree_version": 1,
        "confidence": Decimal("0.8"),
        "created_at": NOW,
        "valid_until": None,
        "scheduled_date": None,
        "actions": {},
        "assigned_membership_id": None,
    }
    row.update(over)
    return to_item(row, now=NOW)


def test_grouping_by_action_type_orders_by_field_workflow_not_alphabet():
    items = [
        _item(action_type="prune"),
        _item(action_type="scout"),
        _item(action_type="spray"),
    ]
    keys = [g.key for g in build_groups(items, group_by="action_type", responsible={})]
    assert keys == ["scout", "spray", "prune"]


def test_unclassified_sorts_last_and_is_named_not_hidden():
    # NULL action_type is every alert raised before migration 0063. Dropping
    # those rows would hide real work; guessing a verb would be worse.
    items = [_item(action_type=None), _item(action_type="spray")]
    groups = build_groups(items, group_by="action_type", responsible={})
    assert [g.key for g in groups] == ["spray", "unclassified"]


def test_due_groups_keep_urgency_order_and_drop_empty_buckets():
    items = [
        _item(valid_until=NOW - timedelta(days=1)),
        _item(actions={"short_term": [{"text_en": "x"}]}),
    ]
    assert [g.key for g in build_groups(items, group_by="due", responsible={})] == [
        "overdue",
        "week",
    ]


def test_block_groups_carry_the_responsible_member():
    block_id = uuid4()
    member = uuid4()
    items = [_item(block_id=block_id, block_code="B-12")]
    groups = build_groups(items, group_by="block", responsible={block_id: member})
    assert groups[0].responsible_membership_id == member
    assert groups[0].label == "Block B-12"


def test_a_block_with_no_responsible_member_is_not_an_error():
    items = [_item(block_code="B-07")]
    groups = build_groups(items, group_by="block", responsible={})
    assert groups[0].responsible_membership_id is None


def test_group_counts_describe_the_group_not_the_page():
    items = [
        _item(action_type="scout", severity="critical", block_code="B-01"),
        _item(action_type="scout", severity="warning", block_code="B-02"),
    ]
    g = build_groups(items, group_by="action_type", responsible={})[0]
    assert (g.count, g.critical_count, g.block_count) == (2, 1, 2)


def test_group_by_none_returns_one_group_holding_everything():
    items = [_item(), _item(action_type="spray")]
    groups = build_groups(items, group_by="none", responsible={})
    assert len(groups) == 1
    assert groups[0].count == 2


# ---------- item shaping --------------------------------------------------


def test_a_cell_scoped_item_carries_coordinates_not_just_a_zone_code():
    cell_id = uuid4()
    item = _item(
        cell_id=cell_id,
        row_idx=2,
        col_idx=3,
        lat=30.04421,
        lon=31.23578,
        ordinal=3,
        total=36,
    )
    assert item.cell is not None
    assert (item.cell.lat, item.cell.lon) == (30.04421, 31.23578)
    assert (item.cell.ordinal, item.cell.total) == (3, 36)


def test_a_block_scoped_item_has_no_cell():
    assert _item().cell is None
