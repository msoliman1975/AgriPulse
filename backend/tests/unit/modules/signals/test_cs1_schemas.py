"""CS-1 foundation — unit tests for the additive schema surface."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.signals.schemas import (
    NUMERIC_VALUE_KINDS,
    Aggregation,
    SignalDefinitionCreateRequest,
    SignalObservationCreateRequest,
    SignalTemplateCreateRequest,
    SignalTemplateDefinitionMember,
    _coerce_aggregation_for_value_kind,
)


class TestCoerceAggregationForValueKind:
    """D3 — non-numeric value_kinds must always use `latest`."""

    @pytest.mark.parametrize(
        ("value_kind", "requested"),
        [
            ("categorical", "mean"),
            ("event", "max"),
            ("boolean", "median"),
            ("geopoint", "min"),
        ],
    )
    def test_non_numeric_kinds_clamp_to_latest(
        self, value_kind: str, requested: Aggregation
    ) -> None:
        assert _coerce_aggregation_for_value_kind(value_kind, requested) == "latest"

    def test_non_numeric_with_none_still_returns_latest(self) -> None:
        assert _coerce_aggregation_for_value_kind("categorical", None) == "latest"

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            ("latest", "latest"),
            ("mean", "mean"),
            ("median", "median"),
            ("max", "max"),
            ("min", "min"),
        ],
    )
    def test_numeric_passes_through(self, requested: Aggregation, expected: Aggregation) -> None:
        assert _coerce_aggregation_for_value_kind("numeric", requested) == expected

    def test_numeric_with_none_defaults_to_latest(self) -> None:
        assert _coerce_aggregation_for_value_kind("numeric", None) == "latest"

    def test_known_numeric_kinds_set(self) -> None:
        # Defensive: catches additions to NUMERIC_VALUE_KINDS that would
        # change the coercion behavior for existing definitions.
        assert frozenset({"numeric"}) == NUMERIC_VALUE_KINDS


class TestSignalDefinitionCreate:
    """D3 fields on the create request."""

    def test_defaults(self) -> None:
        req = SignalDefinitionCreateRequest(
            code="ndvi-spot", name="NDVI spot", value_kind="numeric"
        )
        assert req.aggregation == "latest"
        assert req.aggregation_window_days is None

    def test_explicit_aggregation_window(self) -> None:
        req = SignalDefinitionCreateRequest(
            code="brix",
            name="Brix",
            value_kind="numeric",
            aggregation="mean",
            aggregation_window_days=7,
        )
        assert req.aggregation == "mean"
        assert req.aggregation_window_days == 7

    def test_zero_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SignalDefinitionCreateRequest(
                code="brix",
                name="Brix",
                value_kind="numeric",
                aggregation_window_days=0,
            )

    def test_negative_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SignalDefinitionCreateRequest(
                code="brix",
                name="Brix",
                value_kind="numeric",
                aggregation_window_days=-1,
            )


class TestSignalObservationCreate:
    """D2 + D8 fields on the create request."""

    def test_defaults_preserve_old_api_shape(self) -> None:
        # Existing clients POST with no location_mode and get
        # `entity`-mode behavior (no location_point captured). The
        # template_observation_id stays NULL for standalone records.
        req = SignalObservationCreateRequest(
            farm_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        )
        assert req.location_mode == "entity"
        assert req.location_point is None
        assert req.template_observation_id is None


class TestSignalTemplateCreate:
    """D1 — group N definitions for entry UX."""

    def test_min_one_member(self) -> None:
        with pytest.raises(ValidationError):
            SignalTemplateCreateRequest(
                code="soil-lab",
                name="Soil lab batch",
                members=[],
            )

    def test_member_position_must_be_nonneg(self) -> None:
        with pytest.raises(ValidationError):
            SignalTemplateDefinitionMember(
                signal_definition_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
                position=-1,
            )

    def test_happy_path(self) -> None:
        req = SignalTemplateCreateRequest(
            code="soil-lab",
            name="Soil lab batch",
            members=[
                SignalTemplateDefinitionMember(
                    signal_definition_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
                    position=0,
                    is_required=True,
                ),
                SignalTemplateDefinitionMember(
                    signal_definition_id="00000000-0000-0000-0000-000000000002",  # type: ignore[arg-type]
                    position=1,
                ),
            ],
        )
        assert len(req.members) == 2
        assert req.members[0].is_required is True
        assert req.members[1].is_required is False  # default
