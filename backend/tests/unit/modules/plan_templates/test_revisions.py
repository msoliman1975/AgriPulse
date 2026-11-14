"""Agri Operation PR 4: manual snapshots and diffs by code."""

from __future__ import annotations

from uuid import uuid4

from app.modules.plan_templates.revisions import diff_snapshots, snapshot_of


def _tree() -> dict:
    mid = uuid4()
    return {
        "milestones": [{"id": mid, "code": "bloom"}],
        "activities": [
            {"code": "pruning-1", "activity_type": "pruning", "title": "Prune", "anchor": "start"},
            {
                "code": "fertilizing-1",
                "activity_type": "fertilizing",
                "title": "Feed",
                "anchor": "milestone",
                "milestone_id": mid,
                "offset_days": 3,
            },
        ],
    }


def test_snapshot_keys_by_code_and_names_milestones() -> None:
    snap = snapshot_of(_tree())
    assert set(snap) == {"pruning-1", "fertilizing-1"}
    assert snap["fertilizing-1"]["milestone_code"] == "bloom"
    assert snap["pruning-1"]["milestone_code"] is None


def test_diff_reports_added_removed_and_changed_fields() -> None:
    old = snapshot_of(_tree())
    tree = _tree()
    tree["activities"][1]["offset_days"] = 10
    tree["activities"][1]["dosage"] = "2 kg"
    tree["activities"] = tree["activities"][1:] + [
        {"code": "spraying-1", "activity_type": "spraying", "title": "Spray", "anchor": "start"}
    ]
    diff = diff_snapshots(old, snapshot_of(tree))
    assert diff["comparable"] is True
    assert [a["code"] for a in diff["added"]] == ["spraying-1"]
    assert [r["code"] for r in diff["removed"]] == ["pruning-1"]
    assert diff["changed"] == [
        {
            "code": "fertilizing-1",
            "title": "Feed",
            "title_ar": None,
            "activity_type": "fertilizing",
            "fields": ["offset_days", "dosage"],
        }
    ]


def test_no_baseline_is_not_comparable() -> None:
    diff = diff_snapshots(None, snapshot_of(_tree()))
    assert diff == {"comparable": False, "added": [], "removed": [], "changed": []}


def test_identical_snapshots_have_no_changes() -> None:
    snap = snapshot_of(_tree())
    assert diff_snapshots(snap, snapshot_of(_tree())) == {
        "comparable": True,
        "added": [],
        "removed": [],
        "changed": [],
    }
