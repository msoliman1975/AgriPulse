"""D21 crop-scoped signals and D6 windowed ``latest`` / ``days_since_latest``.

Pure checks: request validation, the service's normalisation and its handling
of the window, the Python twin of the catalog crop filter, and the snapshot
SQL's shape. The SQL itself is planned against Postgres in
``tests/integration/signals/test_crop_scoped_snapshot_sql.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.signals.aggregation import ObservationRow, aggregate_observations
from app.modules.signals.repository import crop_path_related
from app.modules.signals.schemas import (
    SignalAssignmentCreateRequest,
    SignalDefinitionCreateRequest,
    SignalDefinitionUpdateRequest,
    SignalTemplateCreateRequest,
)
from app.modules.signals.service import SignalsServiceImpl, _normalize_crop_paths
from app.shared.conditions.context import SIGNAL_KEYS, SignalEntry
from tests.unit.modules.signals.test_template_service import _impl_with_mocked_repo

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _def_payload(**extra: Any) -> dict[str, Any]:
    return {"code": "rpw_frass", "name": "RPW frass", "value_kind": "boolean", **extra}


class TestCropPathsValidation:
    def test_defaults_to_every_crop(self) -> None:
        assert SignalDefinitionCreateRequest(**_def_payload()).crop_paths == []

    @pytest.mark.parametrize(
        "path", ["date_palm", "date_palm.medjool", "date_palm.medjool.bc_line", "mango"]
    )
    def test_accepts_crop_paths(self, path: str) -> None:
        req = SignalDefinitionCreateRequest(**_def_payload(crop_paths=[path]))
        assert req.crop_paths == [path]

    @pytest.mark.parametrize(
        "path", ["", "Date_Palm", "date_palm.", ".medjool", "a.b.c.d", "date palm", "date-palm"]
    )
    def test_rejects_malformed_paths(self, path: str) -> None:
        with pytest.raises(ValidationError):
            SignalDefinitionCreateRequest(**_def_payload(crop_paths=[path]))

    def test_update_leaves_scope_alone_when_absent(self) -> None:
        req = SignalDefinitionUpdateRequest(name="x")
        assert "crop_paths" not in req.model_dump(exclude_unset=True)

    def test_template_accepts_crop_paths(self) -> None:
        req = SignalTemplateCreateRequest(
            code="medjool_rpw",
            name="RPW round",
            members=[{"signal_definition_id": uuid4(), "position": 0}],
            crop_paths=["date_palm.medjool"],
        )
        assert req.crop_paths == ["date_palm.medjool"]

    def test_assignment_opt_out_flag(self) -> None:
        assert SignalAssignmentCreateRequest().is_active is True
        assert SignalAssignmentCreateRequest(block_id=uuid4(), is_active=False).is_active is False


class TestNormalise:
    def test_dedupes_and_sorts(self) -> None:
        assert _normalize_crop_paths(["mango", "date_palm", "mango"]) == ["date_palm", "mango"]

    def test_null_means_every_crop(self) -> None:
        assert _normalize_crop_paths(None) == []


class TestCropPathRelated:
    @pytest.mark.parametrize(
        ("scope", "crop", "expected"),
        [
            ("date_palm", "date_palm", True),
            ("date_palm", "date_palm.medjool", True),  # scope is an ancestor
            ("date_palm.medjool", "date_palm", True),  # scope is a descendant
            ("date_palm.medjool", "date_palm.barhi", False),
            ("date_palm", "date_palmyra", False),  # prefix but not a path segment
            ("mango", "date_palm.medjool", False),
        ],
    )
    def test_matches_on_whole_segments(self, scope: str, crop: str, expected: bool) -> None:
        assert crop_path_related(scope, crop) is expected


def _impl(repo: AsyncMock) -> SignalsServiceImpl:
    impl = _impl_with_mocked_repo(repo)
    impl._log = MagicMock()  # type: ignore[attr-defined]
    return impl


@pytest.mark.asyncio
class TestServiceKeepsWindowForLatest:
    async def test_create_keeps_window_and_normalises_scope(self) -> None:
        repo = AsyncMock()
        repo.insert_definition.return_value = {"id": uuid4()}
        await _impl(repo).create_definition(
            code="rpw_frass",
            name="RPW frass",
            name_ar="نشارة سوسة النخيل",
            description=None,
            value_kind="boolean",
            unit=None,
            categorical_values=None,
            value_min=None,
            value_max=None,
            attachment_allowed=False,
            aggregation="latest",
            aggregation_window_days=14,
            crop_paths=["date_palm.medjool", "date_palm.medjool"],
            actor_user_id=None,
            tenant_schema=None,
        )
        kwargs = repo.insert_definition.await_args.kwargs
        assert kwargs["aggregation"] == "latest"
        assert kwargs["aggregation_window_days"] == 14
        assert kwargs["crop_paths"] == ["date_palm.medjool"]

    async def test_update_to_latest_keeps_window(self) -> None:
        repo = AsyncMock()
        repo.get_definition.return_value = {"code": "x", "value_kind": "numeric"}
        repo.update_definition.return_value = {"id": uuid4()}
        await _impl(repo).update_definition(
            definition_id=uuid4(),
            updates={"aggregation": "latest", "aggregation_window_days": 30, "crop_paths": None},
            actor_user_id=None,
            tenant_schema=None,
        )
        updates = repo.update_definition.await_args.kwargs["updates"]
        assert updates["aggregation_window_days"] == 30
        assert updates["crop_paths"] == []


def _row(days_ago: float, **values: Any) -> ObservationRow:
    return ObservationRow(time=NOW - timedelta(days=days_ago), **values)


class TestWindowedLatest:
    def test_fresh_answer_reads(self) -> None:
        out = aggregate_observations(
            [_row(3, value_boolean=True)],
            value_kind="boolean",
            aggregation="latest",
            window_days=14,
            now=NOW,
        )
        assert out is not None
        assert out.value_boolean is True
        assert out.days_since_latest == Decimal(3)

    def test_expired_answer_reads_as_missing_but_keeps_its_age(self) -> None:
        out = aggregate_observations(
            [_row(20, value_categorical="present"), _row(40, value_categorical="absent")],
            value_kind="categorical",
            aggregation="latest",
            window_days=14,
            now=NOW,
        )
        assert out is not None
        assert out.value_categorical is None
        assert out.time == NOW - timedelta(days=20)
        assert out.days_since_latest == Decimal(20)

    def test_no_window_means_any_age(self) -> None:
        out = aggregate_observations(
            [_row(400, value_numeric=Decimal("5"))],
            value_kind="numeric",
            aggregation="latest",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == Decimal("5")
        assert out.days_since_latest == Decimal(400)

    def test_days_are_whole_days_rounded_down(self) -> None:
        out = aggregate_observations(
            [_row(2.9, value_event="lure_changed")],
            value_kind="event",
            aggregation="latest",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.days_since_latest == Decimal(2)

    def test_aggregated_rules_report_age_of_newest_in_window(self) -> None:
        out = aggregate_observations(
            [_row(1, value_numeric=Decimal("2")), _row(5, value_numeric=Decimal("4"))],
            value_kind="numeric",
            aggregation="mean",
            window_days=7,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == Decimal("3")
        assert out.days_since_latest == Decimal(1)


class TestSignalKey:
    def test_days_since_latest_is_a_key_and_a_field(self) -> None:
        assert "days_since_latest" in SIGNAL_KEYS
        entry = SignalEntry(time=NOW, days_since_latest=Decimal(9))
        assert entry.days_since_latest == Decimal(9)


class TestSnapshotSqlShape:
    def test_applicability_honours_crop_scope_and_opt_out(self) -> None:
        from app.modules.signals.snapshot import _APPLIES_TO_BLOCK_SQL

        sql = " ".join(_APPLIES_TO_BLOCK_SQL.split())
        assert "a.is_active = TRUE" in sql
        assert "cardinality(d.crop_paths) > 0" in sql
        assert "starts_with(bc.crop_path, scope.p || '.')" in sql
        assert "bc.is_current = TRUE" in sql
        assert "NOT EXISTS" in sql
        assert "a.is_active = FALSE" in sql
        # LIKE would treat the `_` in every crop code as a wildcard.
        assert " LIKE " not in sql


class TestBlockListingFilter:
    def test_block_filter_matches_scope_at_or_above_the_crop_only(self) -> None:
        from app.modules.signals.models import SignalDefinition
        from app.modules.signals.repository import _applies_to_block_crop

        sql = " ".join(str(_applies_to_block_crop(SignalDefinition.crop_paths, uuid4())).split())
        assert "cardinality(signal_definitions.crop_paths) = 0" in sql
        assert "starts_with(bc.crop_path, cp.p || '.')" in sql
        # The catalog filter also matches scopes below the crop; a block must not.
        assert "starts_with(cp.p" not in sql
        assert "bc.is_current = TRUE" in sql
