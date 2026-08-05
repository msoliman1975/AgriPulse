"""The closed vocabulary is only worth having if it is actually enforced."""

from __future__ import annotations

import pytest

from app.modules.telemetry.taxonomy import (
    TaxonomyError,
    get_taxonomy,
    load_taxonomy_from_yaml,
)

_MINIMAL = """
version: 3
events:
  page_view:
    props: [a, b]
  feature_used: {}
features: [insights]
flows:
  onboarding:
    timeout_minutes: 45
    steps: [one, two]
"""


def test_shipped_taxonomy_parses() -> None:
    """The file we actually ship must load — a typo here breaks every ingest."""
    tax = get_taxonomy()
    assert tax.version >= 1
    # The 10 MVP event names from plan § 4.1. flow_abandon is deliberately
    # absent: it is derived, never emitted.
    for name in (
        "session_start",
        "session_end",
        "page_view",
        "page_leave",
        "feature_used",
        "flow_start",
        "flow_step",
        "flow_complete",
        "api_error",
        "client_error",
    ):
        assert tax.has_event(name), name
    assert not tax.has_event("flow_abandon"), (
        "flow_abandon must not be emittable — a client cannot report the user "
        "who closed their laptop, which is the case we care about most"
    )
    assert tax.has_feature("insights")
    assert not tax.has_feature("not_a_feature")
    assert tax.has_flow("farm_onboarding")
    assert tax.allows_step("farm_onboarding", "subscriptions")
    assert not tax.allows_step("farm_onboarding", "wat")


def test_every_flow_has_steps_and_a_timeout() -> None:
    """The abandonment query needs both; a flow missing either is dead weight."""
    for name, flow in get_taxonomy().flows.items():
        assert flow.steps, f"flow {name} has no steps"
        assert flow.timeout_minutes > 0, f"flow {name} has no timeout"


def test_props_allow_list_drops_unknown_keys() -> None:
    tax = load_taxonomy_from_yaml(_MINIMAL)
    kept, dropped = tax.filter_props("page_view", {"a": 1, "zzz": "leak"})
    assert kept == {"a": 1}
    assert dropped == 1


def test_event_with_empty_props_list_drops_everything() -> None:
    """An event that declares no props must not become a free-form bag."""
    tax = load_taxonomy_from_yaml(_MINIMAL)
    kept, dropped = tax.filter_props("feature_used", {"farm_name": "Bashayer"})
    assert kept == {}
    assert dropped == 1


def test_unknown_event_allows_nothing() -> None:
    tax = load_taxonomy_from_yaml(_MINIMAL)
    kept, dropped = tax.filter_props("nope", {"a": 1})
    assert kept == {}
    assert dropped == 1


def test_no_props_key_is_a_free_text_field() -> None:
    """Guard against the failure mode the allow-list exists to prevent.

    Nothing in the shipped taxonomy should invite a name, note, message or
    geometry. This is a blunt check, and that is the point — it fails loudly the
    day someone adds `props: [farm_name]`.
    """
    banned = ("name", "note", "message", "comment", "label", "geom", "email", "text")
    for event, props in get_taxonomy().events.items():
        for key in props:
            assert not any(b in key.lower() for b in banned), (
                f"{event}.props declares '{key}', which invites free text or "
                f"identifying data into telemetry"
            )


@pytest.mark.parametrize(
    "doc",
    [
        "version: notanint\nevents: {a: {}}\nfeatures: [x]",
        "version: 1\nevents: {}\nfeatures: [x]",
        "version: 1\nfeatures: [x]",
        "version: 1\nevents: {a: {}}\nfeatures: []",
        "version: 1\nevents: {a: {props: 3}}\nfeatures: [x]",
        "version: 1\nevents: {a: {}}\nfeatures: [x, x]",
        "version: 1\nevents: {a: {}}\nfeatures: [x]\nflows: {f: {steps: [s]}}",
        "version: 1\nevents: {a: {}}\nfeatures: [x]\nflows: {f: {timeout_minutes: 0}}",
    ],
)
def test_malformed_taxonomy_raises(doc: str) -> None:
    """Fail at load, not per-request — a broken vocabulary is a deploy bug."""
    with pytest.raises(TaxonomyError):
        load_taxonomy_from_yaml(doc)
