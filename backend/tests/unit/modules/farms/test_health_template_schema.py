"""The health-override wire schema, and the two gates behind it.

`HealthDefinitionBody` is the first gate: `extra="forbid"` turns an unknown
key into a 422 before it reaches the column. `parse_definition` is the
second, and it exists because this schema is not the only way a body can
reach the column.

The subtle one is `exclude_unset`. Three fields take null as a REAL value —
a null `snoozed_as` means "a snoozed alert counts by its own severity", not
"inherit" — so "not provided" and "provided as null" cannot be collapsed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.farms.config_schemas import HealthDefinitionBody, HealthTemplateRequest
from app.shared.health_definition import HealthDefinitionError, parse_definition


class TestTheBoundary:
    def test_an_unknown_key_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            HealthDefinitionBody(stale_hours=12)  # type: ignore[call-arg]

    def test_a_known_key_passes(self) -> None:
        assert HealthDefinitionBody(stale_after_hours=12).stale_after_hours == 12

    def test_version_is_not_settable(self) -> None:
        """`version` identifies the generation of a platform-authored
        definition. A farm setting it would pin nothing."""
        with pytest.raises(ValidationError):
            HealthDefinitionBody(version=2)  # type: ignore[call-arg]

    def test_an_unknown_key_on_the_wrapper_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            HealthTemplateRequest(definition=None, force=True)  # type: ignore[call-arg]


class TestExcludeUnset:
    def test_only_what_was_sent_survives(self) -> None:
        body = HealthTemplateRequest.model_validate({"definition": {"stale_after_hours": 12}})
        assert body.definition is not None
        assert body.definition.model_dump(exclude_unset=True) == {"stale_after_hours": 12}

    def test_a_null_that_was_sent_is_kept(self) -> None:
        """The case `exclude_unset` exists for. `snoozed_as: null` is a real
        choice and must reach the column; the six fields nobody named must
        not."""
        body = HealthTemplateRequest.model_validate({"definition": {"snoozed_as": None}})
        assert body.definition is not None
        assert body.definition.model_dump(exclude_unset=True) == {"snoozed_as": None}

    def test_dumping_everything_would_pin_six_values_nobody_chose(self) -> None:
        """Not a behaviour test — a guard on the alternative. If the router
        ever drops `exclude_unset`, this is what it would store, and the farm
        would stop tracking the knowledge base for every one of them."""
        body = HealthTemplateRequest.model_validate({"definition": {"stale_after_hours": 12}})
        assert body.definition is not None
        assert len(body.definition.model_dump()) == 7

    def test_an_empty_body_dumps_to_nothing(self) -> None:
        body = HealthTemplateRequest.model_validate({"definition": {}})
        assert body.definition is not None
        assert body.definition.model_dump(exclude_unset=True) == {}


class TestTheSecondGate:
    """Everything the schema lets through that `parse_definition` must not.

    The schema knows the KEYS. It deliberately does not know the bounds —
    those live in `app.shared.health_definition`, and duplicating them here
    would give two sources of truth of which this would be the one that
    drifts.
    """

    @pytest.mark.parametrize(
        "body",
        [
            {"no_tree_coverage": "critical"},
            {"snoozed_as": "nonsense"},
            {"cell_critical_share": 1.5},
            {"cell_critical_share": 0},
            {"recommendation_floor": 2},
            {"stale_after_hours": 0},
            {"counted_statuses": ["open", "resolved"]},
            {"severity_map": {"critical": "critical"}},
        ],
    )
    def test_the_schema_accepts_it_and_the_parser_does_not(self, body: dict) -> None:
        HealthDefinitionBody.model_validate(body)  # the schema is happy
        with pytest.raises(HealthDefinitionError):
            parse_definition(body)
