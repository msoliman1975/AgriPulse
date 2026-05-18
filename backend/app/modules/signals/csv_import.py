"""Signals CSV import — pure-Python parser + per-row shape validator.

D4 in [[project-custom-signals-plan]]: V1 ingestion is web form + CSV
import; the latter is **strict** — any row that fails validation
rejects the whole batch, the operator fixes the file and re-uploads.
This module covers shape (column presence, type coercion, conflicting
value columns) only; the service layer is responsible for the
business-rule validation that needs a SignalDefinition row (value_min
/max bounds, categorical-membership, etc.) — those errors funnel back
into the same CsvRowError list.

Expected CSV schema (header row is required, column order doesn't
matter):

  signal_code             required, str
  observed_at             required, ISO-8601 timestamp
  block_id                optional, UUID; null = farm-level observation
  value_numeric           optional, Decimal — one of these four must be
  value_categorical       optional, str       non-null (matching the
  value_event             optional, str       referenced SignalDefinition's
  value_boolean           optional, bool      value_kind). Geopoint values
                                              are out of scope for CSV V1.
  notes                   optional, str

Unknown columns are ignored (forwards-compat). Empty cells in a known
column are treated as NULL.

Limits enforced by the parser (DoS guard for the multipart endpoint):

  MAX_BYTES  — refuse files larger than 5 MB (~50k typical rows)
  MAX_ROWS   — refuse parsed files with more than 5,000 rows
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

MAX_BYTES: Final[int] = 5 * 1024 * 1024
MAX_ROWS: Final[int] = 5_000

REQUIRED_COLUMNS: Final[tuple[str, ...]] = ("signal_code", "observed_at")
VALUE_COLUMNS: Final[tuple[str, ...]] = (
    "value_numeric",
    "value_categorical",
    "value_event",
    "value_boolean",
)
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (
    "block_id",
    "notes",
    *VALUE_COLUMNS,
)
KNOWN_COLUMNS: Final[frozenset[str]] = frozenset(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)


@dataclass(frozen=True, slots=True)
class CsvRowError:
    """One validation problem. ``row_number`` is 1-based with the
    header at row 1, so the first data row is row 2 — matches how a
    spreadsheet would display the row to the operator."""

    row_number: int
    field: str | None
    message: str


@dataclass(frozen=True, slots=True)
class ParsedCsvRow:
    """Shape-validated row. The service layer still has to confirm
    the value column matches the referenced definition's value_kind
    + bounds + categorical-membership."""

    row_number: int
    signal_code: str
    observed_at: datetime
    block_id: UUID | None = None
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = None
    value_boolean: bool | None = None
    notes: str | None = None


@dataclass
class CsvParseResult:
    """The two outputs the service consumes. Either rows OR errors is
    typically non-empty; callers should check errors first."""

    rows: list[ParsedCsvRow] = field(default_factory=list)
    errors: list[CsvRowError] = field(default_factory=list)


def parse_csv(text: str) -> CsvParseResult:
    """Parse the CSV body + shape-validate every row.

    Caller decides what to do with non-empty ``errors``; in the strict
    flow the service layer rejects the batch as soon as any error is
    present.
    """
    result = CsvParseResult()

    if not text.strip():
        result.errors.append(CsvRowError(row_number=1, field=None, message="CSV body is empty."))
        return result

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        result.errors.append(
            CsvRowError(row_number=1, field=None, message="CSV has no header row.")
        )
        return result

    headers = {h.strip() for h in reader.fieldnames}
    missing = [col for col in REQUIRED_COLUMNS if col not in headers]
    if missing:
        result.errors.append(
            CsvRowError(
                row_number=1,
                field=None,
                message=f"Missing required column(s): {', '.join(missing)}.",
            )
        )
        return result

    for index, raw in enumerate(reader, start=2):
        if index - 1 > MAX_ROWS:
            result.errors.append(
                CsvRowError(
                    row_number=index,
                    field=None,
                    message=(
                        f"File exceeds the {MAX_ROWS}-row limit. Split into "
                        f"smaller files and re-upload."
                    ),
                )
            )
            return result
        _parse_one_row(raw, row_number=index, into=result)

    return result


def _parse_one_row(  # noqa: PLR0912  # one row, one validator — splitting just adds ceremony
    raw: dict[str, str | None], *, row_number: int, into: CsvParseResult
) -> None:
    """Coerce a single CSV row. Errors accumulate in ``into.errors``;
    a valid row appends to ``into.rows``."""

    def _add_error(field_name: str | None, message: str) -> None:
        into.errors.append(CsvRowError(row_number=row_number, field=field_name, message=message))

    cleaned = {k: _clean(v) for k, v in raw.items() if k in KNOWN_COLUMNS}

    signal_code = cleaned.get("signal_code")
    if not signal_code:
        _add_error("signal_code", "Required value is missing.")

    observed_at_raw = cleaned.get("observed_at")
    observed_at: datetime | None = None
    if not observed_at_raw:
        _add_error("observed_at", "Required value is missing.")
    else:
        try:
            observed_at = datetime.fromisoformat(observed_at_raw)
        except ValueError:
            _add_error(
                "observed_at",
                f"Could not parse {observed_at_raw!r} as ISO-8601 timestamp.",
            )

    block_id_raw = cleaned.get("block_id")
    block_id: UUID | None = None
    if block_id_raw:
        try:
            block_id = UUID(block_id_raw)
        except ValueError:
            _add_error("block_id", f"Could not parse {block_id_raw!r} as a UUID.")

    value_numeric: Decimal | None = None
    if (raw_num := cleaned.get("value_numeric")) is not None:
        try:
            value_numeric = Decimal(raw_num)
        except (InvalidOperation, ValueError):
            _add_error("value_numeric", f"Could not parse {raw_num!r} as a number.")

    value_boolean: bool | None = None
    if (raw_bool := cleaned.get("value_boolean")) is not None:
        normalised = raw_bool.lower()
        if normalised in {"true", "1", "yes", "y", "t"}:
            value_boolean = True
        elif normalised in {"false", "0", "no", "n", "f"}:
            value_boolean = False
        else:
            _add_error("value_boolean", f"Could not parse {raw_bool!r} as a boolean.")

    value_categorical = cleaned.get("value_categorical")
    value_event = cleaned.get("value_event")
    notes = cleaned.get("notes")

    # Exactly-one-value check (matches the DB-row CHECK constraint).
    # Boolean False / numeric 0 are legitimate values; check None-ness,
    # not truthiness.
    set_values = sum(
        1 for v in (value_numeric, value_categorical, value_event, value_boolean) if v is not None
    )
    if set_values == 0:
        _add_error(
            None,
            "No value column populated; exactly one of "
            "value_numeric/value_categorical/value_event/value_boolean is required.",
        )
    elif set_values > 1:
        _add_error(
            None,
            "Multiple value columns populated; exactly one of "
            "value_numeric/value_categorical/value_event/value_boolean is allowed.",
        )

    if signal_code and observed_at is not None and set_values == 1:
        into.rows.append(
            ParsedCsvRow(
                row_number=row_number,
                signal_code=signal_code,
                observed_at=observed_at,
                block_id=block_id,
                value_numeric=value_numeric,
                value_categorical=value_categorical,
                value_event=value_event,
                value_boolean=value_boolean,
                notes=notes,
            )
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
