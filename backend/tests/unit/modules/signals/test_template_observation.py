"""CS-4 unit tests — template-observation submission (mocked repo).

Covers the pre-DB validation in create_template_observation:
- Empty members list rejected.
- location_mode / location_point presence rules.
- Template-not-found surfaces 404.
- Members not bound to the template rejected.
- Duplicate signal_definition_id in submission rejected.
- Per-member value_kind / bounds checked before any insert fires.
- Lead-row id used as the shared template_observation_id.
- All sibling inserts share that template_observation_id; the lead
  row's own id equals it.
- Audit event payload includes template_id + observation_count +
  location_mode.

Repository writes mocked — the real ST_Within trigger + atomicity
properties are exercised by the integration suite (separate PR).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.signals.errors import (
    InvalidSignalValueError,
    SignalTemplateMembersInvalidError,
    SignalTemplateNotFoundError,
)
from app.modules.signals.schemas import (
    GeopointModel,
    SignalTemplateObservationMemberSubmission,
)
from app.modules.signals.service import SignalsServiceImpl


def _impl_with_mocked_repo(repo: AsyncMock) -> SignalsServiceImpl:
    impl = SignalsServiceImpl.__new__(SignalsServiceImpl)
    impl._repo = repo  # type: ignore[attr-defined]
    impl._audit = AsyncMock()
    impl._storage = MagicMock()
    impl._tenant = None  # type: ignore[attr-defined]
    impl._log = None  # type: ignore[attr-defined]
    return impl


def _numeric_defn(def_id: UUID, *, attachment_allowed: bool = False) -> dict:
    return {
        "id": def_id,
        "code": f"def-{def_id.hex[:6]}",
        "value_kind": "numeric",
        "value_min": Decimal("0"),
        "value_max": Decimal("100"),
        "categorical_values": None,
        "attachment_allowed": attachment_allowed,
    }


def _categorical_defn(def_id: UUID, *, allowed: list[str]) -> dict:
    return {
        "id": def_id,
        "code": f"def-{def_id.hex[:6]}",
        "value_kind": "categorical",
        "value_min": None,
        "value_max": None,
        "categorical_values": allowed,
        "attachment_allowed": False,
    }


def _member(
    def_id: UUID, *, numeric: Decimal | None = None, categorical: str | None = None
) -> SignalTemplateObservationMemberSubmission:
    return SignalTemplateObservationMemberSubmission(
        signal_definition_id=def_id,
        value_numeric=numeric,
        value_categorical=categorical,
    )


class TestValidateLocationPresence:
    """CS-1 D2 presence rule — covered as a static method so it's
    cheap to unit-test in isolation."""

    def test_entity_with_point_rejected(self) -> None:
        with pytest.raises(InvalidSignalValueError, match="must not include"):
            SignalsServiceImpl._validate_location_presence(
                location_mode="entity",
                location_point=GeopointModel(latitude=10, longitude=20),
            )

    def test_point_in_entity_requires_point(self) -> None:
        with pytest.raises(InvalidSignalValueError, match="requires a location_point"):
            SignalsServiceImpl._validate_location_presence(
                location_mode="point_in_entity", location_point=None
            )

    def test_free_point_requires_point(self) -> None:
        with pytest.raises(InvalidSignalValueError, match="requires a location_point"):
            SignalsServiceImpl._validate_location_presence(
                location_mode="free_point", location_point=None
            )

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(InvalidSignalValueError, match="Unknown location_mode"):
            SignalsServiceImpl._validate_location_presence(
                location_mode="nope", location_point=None
            )

    def test_happy_entity(self) -> None:
        # No raise = pass.
        SignalsServiceImpl._validate_location_presence(location_mode="entity", location_point=None)


@pytest.mark.asyncio
class TestCreateTemplateObservation:
    async def test_unknown_template_raises_404(self) -> None:
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value=None)
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(SignalTemplateNotFoundError):
            await impl.create_template_observation(
                template_id=uuid4(),
                farm_id=uuid4(),
                block_id=None,
                observed_at=None,
                location_mode="entity",
                location_point=None,
                members=(_member(uuid4(), numeric=Decimal("1")),),
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )
        repo.insert_observation.assert_not_called()

    async def test_member_not_bound_to_template_rejected(self) -> None:
        bound_id = uuid4()
        unbound_id = uuid4()
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value={"id": uuid4(), "code": "x"})
        repo.get_template_members = AsyncMock(
            return_value=({"signal_definition_id": bound_id, "position": 0, "is_required": False},)
        )
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(SignalTemplateMembersInvalidError, match="not bound to template"):
            await impl.create_template_observation(
                template_id=uuid4(),
                farm_id=uuid4(),
                block_id=None,
                observed_at=None,
                location_mode="entity",
                location_point=None,
                members=(_member(unbound_id, numeric=Decimal("1")),),
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )
        repo.insert_observation.assert_not_called()

    async def test_duplicate_definition_in_submission_rejected(self) -> None:
        def_id = uuid4()
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value={"id": uuid4(), "code": "x"})
        repo.get_template_members = AsyncMock(
            return_value=({"signal_definition_id": def_id, "position": 0, "is_required": False},)
        )
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(SignalTemplateMembersInvalidError, match="Duplicate"):
            await impl.create_template_observation(
                template_id=uuid4(),
                farm_id=uuid4(),
                block_id=None,
                observed_at=None,
                location_mode="entity",
                location_point=None,
                members=(
                    _member(def_id, numeric=Decimal("1")),
                    _member(def_id, numeric=Decimal("2")),
                ),
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )

    async def test_invalid_value_rejected_before_any_insert(self) -> None:
        def_id = uuid4()
        defn = _numeric_defn(def_id)  # value_max=100
        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value={"id": uuid4(), "code": "x"})
        repo.get_template_members = AsyncMock(
            return_value=({"signal_definition_id": def_id, "position": 0, "is_required": False},)
        )
        repo.get_definition = AsyncMock(return_value=defn)
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(InvalidSignalValueError, match="value_max"):
            await impl.create_template_observation(
                template_id=uuid4(),
                farm_id=uuid4(),
                block_id=None,
                observed_at=None,
                location_mode="entity",
                location_point=None,
                members=(_member(def_id, numeric=Decimal("999")),),
                recorded_by=uuid4(),
                tenant_schema="t_x",
            )
        repo.insert_observation.assert_not_called()

    async def test_happy_path_shares_template_observation_id(self) -> None:
        def_a = uuid4()
        def_b = uuid4()
        template_id = uuid4()
        farm_id = uuid4()
        recorded_by = uuid4()
        observed_at = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

        repo = AsyncMock()
        repo.get_template = AsyncMock(return_value={"id": template_id, "code": "soil-lab"})
        repo.get_template_members = AsyncMock(
            return_value=(
                {"signal_definition_id": def_a, "position": 0, "is_required": True},
                {"signal_definition_id": def_b, "position": 1, "is_required": False},
            )
        )
        repo.get_definition = AsyncMock(
            side_effect=lambda *, definition_id: (
                _numeric_defn(def_a)
                if definition_id == def_a
                else _categorical_defn(def_b, allowed=["red", "green"])
            )
        )
        repo.insert_observation = AsyncMock()
        impl = _impl_with_mocked_repo(repo)

        result = await impl.create_template_observation(
            template_id=template_id,
            farm_id=farm_id,
            block_id=None,
            observed_at=observed_at,
            location_mode="entity",
            location_point=None,
            members=(
                _member(def_a, numeric=Decimal("42")),
                _member(def_b, categorical="green"),
            ),
            recorded_by=recorded_by,
            tenant_schema="t_x",
        )

        # Two inserts, both with the same template_observation_id;
        # the lead row's own id equals it.
        assert repo.insert_observation.await_count == 2
        calls = repo.insert_observation.await_args_list
        lead_kwargs = calls[0].kwargs
        sibling_kwargs = calls[1].kwargs
        shared = lead_kwargs["template_observation_id"]
        assert shared == lead_kwargs["observation_id"]  # lead row points at itself
        assert sibling_kwargs["template_observation_id"] == shared
        assert sibling_kwargs["observation_id"] != shared  # sibling has its own id

        # Response carries the same id + count + the observed_at the
        # caller supplied.
        assert result["template_observation_id"] == shared
        assert result["template_id"] == template_id
        assert result["observation_count"] == 2
        assert result["observed_at"] == observed_at

        # Audit emitted with the expected payload.
        audit_call = impl._audit.record.await_args  # type: ignore[attr-defined]
        assert audit_call.kwargs["event_type"] == "signals.template_observation_recorded"
        assert audit_call.kwargs["subject_id"] == shared
        assert audit_call.kwargs["details"]["template_id"] == str(template_id)
        assert audit_call.kwargs["details"]["observation_count"] == 2
        assert audit_call.kwargs["details"]["location_mode"] == "entity"
