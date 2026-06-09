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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

MAX_BYTES: Final[int] = 5 * 1024 * 1024
MAX_ROWS: Final[int] = 5_000
# CS-12: ?bulk_mode=true backfill ceilings (tenant-admin gated).
MAX_BYTES_BULK: Final[int] = 50 * 1024 * 1024
MAX_ROWS_BULK: Final[int] = 50_000

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
    # CS-12: location capture + attachment + templated-row columns.
    "location_mode",
    "location_point_lat",
    "location_point_lon",
    "attachment_s3_key",
    "template_code",
    "template_member_position",
)
KNOWN_COLUMNS: Final[frozenset[str]] = frozenset(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)

_LOCATION_MODES: Final[frozenset[str]] = frozenset({"entity", "point_in_entity", "free_point"})


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
    # CS-12 additive columns. location_point_* are floats here; the
    # service renders them as WKT. template_* drive group assembly.
    location_mode: str = "entity"
    location_point_lat: float | None = None
    location_point_lon: float | None = None
    attachment_s3_key: str | None = None
    template_code: str | None = None
    template_member_position: int | None = None


@dataclass
class CsvParseResult:
    """The two outputs the service consumes. Either rows OR errors is
    typically non-empty; callers should check errors first."""

    rows: list[ParsedCsvRow] = field(default_factory=list)
    errors: list[CsvRowError] = field(default_factory=list)


def parse_csv(text: str, *, max_rows: int = MAX_ROWS) -> CsvParseResult:
    """Parse the CSV body + shape-validate every row.

    Caller decides what to do with non-empty ``errors``; in the strict
    flow the service layer rejects the batch as soon as any error is
    present. ``max_rows`` defaults to 5,000; the ``bulk_mode`` import path
    raises it to support backfills.
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
        if index - 1 > max_rows:
            result.errors.append(
                CsvRowError(
                    row_number=index,
                    field=None,
                    message=(
                        f"File exceeds the {max_rows}-row limit. Split into "
                        f"smaller files and re-upload."
                    ),
                )
            )
            return result
        _parse_one_row(raw, row_number=index, into=result)

    return result


def _parse_one_row(  # noqa: PLR0912, PLR0915  # one row, one validator — splitting just adds ceremony
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

    # CS-12: location / attachment / template columns (extracted to keep
    # this validator a manageable length).
    location_mode, lat, lon = _parse_location(cleaned, _add_error)
    attachment_s3_key = cleaned.get("attachment_s3_key")
    template_code, template_member_position = _parse_template_ref(cleaned, _add_error)

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
                location_mode=location_mode,
                location_point_lat=lat,
                location_point_lon=lon,
                attachment_s3_key=attachment_s3_key,
                template_code=template_code,
                template_member_position=template_member_position,
            )
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_coord(
    raw: str | None,
    field_name: str,
    limit: float,
    add_error: Callable[[str | None, str], None],
) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except ValueError:
        add_error(field_name, f"Could not parse {raw!r} as a number.")
        return None
    if v < -limit or v > limit:
        add_error(field_name, f"Must be between -{limit:g} and {limit:g}.")
        return None
    return v


def _parse_location(
    cleaned: dict[str, str | None],
    add_error: Callable[[str | None, str], None],
) -> tuple[str, float | None, float | None]:
    """(location_mode, lat, lon) with CS-10 coherence rules enforced."""
    location_mode = cleaned.get("location_mode") or "entity"
    if location_mode not in _LOCATION_MODES:
        add_error("location_mode", "Must be one of entity, point_in_entity, free_point.")
        location_mode = "entity"

    lat = _parse_coord(cleaned.get("location_point_lat"), "location_point_lat", 90.0, add_error)
    lon = _parse_coord(cleaned.get("location_point_lon"), "location_point_lon", 180.0, add_error)
    if (lat is None) != (lon is None):
        add_error(
            "location_point_lat",
            "Provide both location_point_lat and location_point_lon, or neither.",
        )
    if location_mode in {"point_in_entity", "free_point"} and (lat is None or lon is None):
        add_error(
            "location_mode",
            f"location_mode={location_mode!r} requires location_point_lat + location_point_lon.",
        )
    if location_mode == "entity" and (lat is not None or lon is not None):
        add_error("location_mode", "location_mode=entity must not carry a location point.")
    return location_mode, lat, lon


def _parse_template_ref(
    cleaned: dict[str, str | None],
    add_error: Callable[[str | None, str], None],
) -> tuple[str | None, int | None]:
    """(template_code, template_member_position) — both-or-neither."""
    template_code = cleaned.get("template_code")
    member_pos_raw = cleaned.get("template_member_position")
    position: int | None = None
    if member_pos_raw is not None:
        try:
            position = int(member_pos_raw)
            if position < 0:
                add_error("template_member_position", "Must be >= 0.")
                position = None
        except ValueError:
            add_error(
                "template_member_position",
                f"Could not parse {member_pos_raw!r} as an integer.",
            )
    if template_code and position is None and member_pos_raw is None:
        add_error("template_member_position", "Required when template_code is set.")
    if member_pos_raw is not None and not template_code:
        add_error("template_code", "Required when template_member_position is set.")
    return template_code, position


@dataclass(frozen=True, slots=True)
class TemplatedGroup:
    """A set of CSV rows that together form one template observation —
    same template + observed_at + block + location, one row per member."""

    template_code: str
    observed_at: datetime
    block_id: UUID | None
    location_mode: str
    location_point_lat: float | None
    location_point_lon: float | None
    rows: tuple[ParsedCsvRow, ...]


def group_rows(
    rows: list[ParsedCsvRow],
) -> tuple[list[ParsedCsvRow], list[TemplatedGroup], list[CsvRowError]]:
    """Split shape-valid rows into flat rows + templated groups (CS-12).

    Rows carrying a ``template_code`` are grouped by
    (template_code, observed_at, block_id, location_mode, lat, lon) — so a
    file may freely mix flat rows and several template submissions. The
    only intra-group rule enforced here is that member positions are
    unique; membership-in-template + value-kind checks are the service's
    job (they need the catalog). Errors are returned, not raised.
    """
    flat: list[ParsedCsvRow] = []
    grouped: dict[
        tuple[str, datetime, UUID | None, str, float | None, float | None],
        list[ParsedCsvRow],
    ] = {}
    for row in rows:
        if not row.template_code:
            flat.append(row)
            continue
        key = (
            row.template_code,
            row.observed_at,
            row.block_id,
            row.location_mode,
            row.location_point_lat,
            row.location_point_lon,
        )
        grouped.setdefault(key, []).append(row)

    groups: list[TemplatedGroup] = []
    errors: list[CsvRowError] = []
    for key, member_rows in grouped.items():
        seen_positions: dict[int, int] = {}
        for r in member_rows:
            pos = r.template_member_position
            if pos is None:
                continue  # already flagged in _parse_one_row
            if pos in seen_positions:
                errors.append(
                    CsvRowError(
                        row_number=r.row_number,
                        field="template_member_position",
                        message=(
                            f"Duplicate member position {pos} in template "
                            f"{key[0]!r} group (also row {seen_positions[pos]})."
                        ),
                    )
                )
            else:
                seen_positions[pos] = r.row_number
        groups.append(
            TemplatedGroup(
                template_code=key[0],
                observed_at=key[1],
                block_id=key[2],
                location_mode=key[3],
                location_point_lat=key[4],
                location_point_lon=key[5],
                rows=tuple(member_rows),
            )
        )
    return flat, groups, errors
