"""CS-7 unit tests — CSV parser + service orchestration (mocked repo).

The parser is pure stdlib so it's all unit-testable here. The service
import_observations_csv is exercised with an AsyncMock'd repo to
verify the all-or-nothing transaction behaviour and the two-pass
error accumulation (shape errors + business-rule errors merged into
one report).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.signals.csv_import import (
    MAX_ROWS,
    CsvRowError,
    parse_csv,
)
from app.modules.signals.errors import (
    CsvImportFailedError,
    CsvImportTooLargeError,
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


def _numeric_defn(code: str) -> dict:
    return {
        "id": uuid4(),
        "code": code,
        "value_kind": "numeric",
        "value_min": Decimal("0"),
        "value_max": Decimal("100"),
        "categorical_values": None,
        "attachment_allowed": False,
    }


def _categorical_defn(code: str, allowed: list[str]) -> dict:
    return {
        "id": uuid4(),
        "code": code,
        "value_kind": "categorical",
        "value_min": None,
        "value_max": None,
        "categorical_values": allowed,
        "attachment_allowed": False,
    }


# ---------- parser ----------


class TestParseCsvHappy:
    def test_minimal_numeric_row(self) -> None:
        text = "signal_code,observed_at,value_numeric\n" "soil_ph,2026-05-18T08:00:00+00:00,6.7\n"
        result = parse_csv(text)
        assert result.errors == []
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.row_number == 2
        assert row.signal_code == "soil_ph"
        assert row.value_numeric == Decimal("6.7")
        assert row.value_categorical is None
        assert row.block_id is None
        assert row.notes is None

    def test_unknown_columns_ignored(self) -> None:
        # Forwards-compat: extra columns the parser doesn't recognise
        # are silently dropped (so callers can add export-side fluff).
        text = (
            "signal_code,observed_at,value_numeric,extra_field\n"
            "soil_ph,2026-05-18T08:00:00+00:00,6.7,ignored\n"
        )
        result = parse_csv(text)
        assert result.errors == []
        assert result.rows[0].value_numeric == Decimal("6.7")

    def test_block_id_parsed(self) -> None:
        block = uuid4()
        text = (
            "signal_code,observed_at,block_id,value_categorical\n"
            f"scout,2026-05-18T08:00:00+00:00,{block},green\n"
        )
        result = parse_csv(text)
        assert result.errors == []
        assert result.rows[0].block_id == block
        assert result.rows[0].value_categorical == "green"

    def test_boolean_truthy_strings(self) -> None:
        text = (
            "signal_code,observed_at,value_boolean\n"
            "irrigated,2026-05-18T08:00:00+00:00,true\n"
            "irrigated,2026-05-18T08:00:00+00:00,YES\n"
            "irrigated,2026-05-18T08:00:00+00:00,0\n"
        )
        result = parse_csv(text)
        assert result.errors == []
        assert [r.value_boolean for r in result.rows] == [True, True, False]


class TestParseCsvShape:
    def test_empty_body(self) -> None:
        result = parse_csv("")
        assert result.rows == []
        assert len(result.errors) == 1
        assert "empty" in result.errors[0].message.lower()

    def test_missing_required_column(self) -> None:
        text = "signal_code,value_numeric\nsoil_ph,6.7\n"
        result = parse_csv(text)
        assert result.rows == []
        assert any("observed_at" in e.message for e in result.errors)

    def test_unparseable_observed_at(self) -> None:
        text = "signal_code,observed_at,value_numeric\n" "soil_ph,not-a-date,6.7\n"
        result = parse_csv(text)
        assert result.rows == []
        assert any(e.field == "observed_at" for e in result.errors)

    def test_no_value_column_set(self) -> None:
        text = "signal_code,observed_at,value_numeric\n" "soil_ph,2026-05-18T08:00:00+00:00,\n"
        result = parse_csv(text)
        assert result.rows == []
        assert any("No value column" in e.message for e in result.errors)

    def test_multiple_value_columns_set(self) -> None:
        text = (
            "signal_code,observed_at,value_numeric,value_categorical\n"
            "soil_ph,2026-05-18T08:00:00+00:00,6.7,green\n"
        )
        result = parse_csv(text)
        assert result.rows == []
        assert any("Multiple value columns" in e.message for e in result.errors)

    def test_row_limit_enforced(self) -> None:
        body = "signal_code,observed_at,value_numeric\n"
        # MAX_ROWS+1 data rows.
        body += "\n".join(f"soil_ph,2026-05-18T08:00:00+00:00,{i}" for i in range(MAX_ROWS + 1))
        result = parse_csv(body)
        # The MAX_ROWS+1th row triggers; everything up to MAX_ROWS may
        # have parsed already so we just assert the limit error fired.
        assert any("row limit" in e.message.lower() for e in result.errors)


# ---------- service orchestration ----------


@pytest.mark.asyncio
class TestImportObservationsCsv:
    async def test_too_large_raises_413(self) -> None:
        repo = AsyncMock()
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(CsvImportTooLargeError):
            await impl.import_observations_csv(
                farm_id=uuid4(),
                csv_bytes=b"X" * (5 * 1024 * 1024 + 1),
                recorded_by=uuid4(),
                tenant_schema="t_x",
                tenant_id=uuid4(),
            )
        repo.insert_observation.assert_not_called()

    async def test_non_utf8_decoded_as_422(self) -> None:
        repo = AsyncMock()
        impl = _impl_with_mocked_repo(repo)
        with pytest.raises(CsvImportFailedError) as exc_info:
            await impl.import_observations_csv(
                farm_id=uuid4(),
                # \xff is invalid UTF-8.
                csv_bytes=b"signal_code,observed_at\nsoil\xff_ph,2026-01-01\n",
                recorded_by=uuid4(),
                tenant_schema="t_x",
                tenant_id=uuid4(),
            )
        errors = exc_info.value.extras["errors"]
        assert any("UTF-8" in e["message"] for e in errors)

    async def test_unknown_code_rejected_atomically(self) -> None:
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=None)
        impl = _impl_with_mocked_repo(repo)
        body = b"signal_code,observed_at,value_numeric\n" b"unknown,2026-05-18T08:00:00+00:00,6.7\n"
        with pytest.raises(CsvImportFailedError) as exc_info:
            await impl.import_observations_csv(
                farm_id=uuid4(),
                csv_bytes=body,
                recorded_by=uuid4(),
                tenant_schema="t_x",
                tenant_id=uuid4(),
            )
        errors = exc_info.value.extras["errors"]
        assert any(e["field"] == "signal_code" for e in errors)
        repo.insert_observation.assert_not_called()

    async def test_value_kind_mismatch_rejected(self) -> None:
        defn = _numeric_defn("soil_ph")
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=defn)
        impl = _impl_with_mocked_repo(repo)
        # Row passes shape (one value set) but value_categorical on a
        # numeric def fails business rules.
        body = (
            b"signal_code,observed_at,value_categorical\n"
            b"soil_ph,2026-05-18T08:00:00+00:00,green\n"
        )
        with pytest.raises(CsvImportFailedError):
            await impl.import_observations_csv(
                farm_id=uuid4(),
                csv_bytes=body,
                recorded_by=uuid4(),
                tenant_schema="t_x",
                tenant_id=uuid4(),
            )
        repo.insert_observation.assert_not_called()

    async def test_happy_path_inserts_all_and_audits(self) -> None:
        ph = _numeric_defn("soil_ph")
        scout = _categorical_defn("scout_severity", allowed=["low", "high"])
        repo = AsyncMock()
        # Each call to get_definition resolves the relevant code.
        repo.get_definition = AsyncMock(
            side_effect=lambda *, code: {"soil_ph": ph, "scout_severity": scout}.get(code)
        )
        repo.insert_observation = AsyncMock()
        impl = _impl_with_mocked_repo(repo)
        body = (
            b"signal_code,observed_at,value_numeric,value_categorical\n"
            b"soil_ph,2026-05-18T08:00:00+00:00,6.7,\n"
            b"scout_severity,2026-05-18T09:00:00+00:00,,high\n"
        )
        out = await impl.import_observations_csv(
            farm_id=uuid4(),
            csv_bytes=body,
            recorded_by=uuid4(),
            tenant_schema="t_x",
            tenant_id=uuid4(),
        )
        assert out == {"rows_imported": 2}
        assert repo.insert_observation.await_count == 2
        # Audit emitted once with the row count + codes.
        audit_call = impl._audit.record.await_args  # type: ignore[attr-defined]
        assert audit_call.kwargs["event_type"] == "signals.observations_csv_imported"
        assert audit_call.kwargs["details"]["rows_imported"] == 2
        assert audit_call.kwargs["details"]["signal_codes"] == ["scout_severity", "soil_ph"]

    async def test_mixed_errors_combined_in_one_report(self) -> None:
        # One row has a shape error (bad date), another references an
        # unknown code. The error report should carry both.
        repo = AsyncMock()
        repo.get_definition = AsyncMock(return_value=None)  # everything unknown
        impl = _impl_with_mocked_repo(repo)
        body = (
            b"signal_code,observed_at,value_numeric\n"
            b"soil_ph,not-a-date,6.7\n"
            b"unknown,2026-05-18T08:00:00+00:00,3.2\n"
        )
        with pytest.raises(CsvImportFailedError) as exc_info:
            await impl.import_observations_csv(
                farm_id=uuid4(),
                csv_bytes=body,
                recorded_by=uuid4(),
                tenant_schema="t_x",
                tenant_id=uuid4(),
            )
        errors = exc_info.value.extras["errors"]
        # Shape error (row 2) + business error (row 3).
        rows = {e["row_number"] for e in errors}
        assert rows == {2, 3}


# ---------- CsvRowError dataclass smoke ----------


class TestCsvRowError:
    def test_is_frozen(self) -> None:
        err = CsvRowError(row_number=2, field="x", message="y")
        with pytest.raises((AttributeError, TypeError)):
            err.message = "z"  # type: ignore[misc]
