"""Custom (tenant-defined) report columns — crop attributes and signals.

The six V1 reports only ever showed first-class columns: the block name, the
index numbers, the irrigation counters. Everything a tenant *defines itself* —
crop attributes (``public.crop_attribute_definitions`` →
``block_crop_attribute_values``) and custom signals
(``public.signal_definitions`` → ``signal_observations``) — was invisible in
every report, even though those are the fields the agronomist actually keyed in.

This module is the one place that knows how to:

1. **Offer** the columns available on a farm (:func:`list_custom_fields`), so
   the column picker is data-driven rather than a hardcoded list, and
2. **Resolve** the picked columns to a value per block
   (:func:`load_custom_values`), in the typed form both sources already store —
   no CAST, no re-parsing of an ISO string (the #331/#332/#335 family).

A column is addressed by a ``source:code`` **ref key** (``crop_attribute:brix``,
``signal:trap_count``). One string is what the query param carries, what the
row dict is keyed by, and what the FE uses as its column id — so no report has
to hold a parallel source/code pair.

Two rules the callers must not re-derive:

* **Crop attributes are as-of-now.** ``block_crop_attribute_values`` holds the
  current value of the current assignment. There is an as-of-period-end history
  in ``block_crop_attribute_value_log``; a report that starts caring has to go
  through the log, not through this loader.
* **Signals are windowed.** A signal column shows the latest observation
  **inside the report period**, not the latest ever — otherwise a 30-day report
  would print a number from last season and nothing on the page would say so.
  ``observed_at`` rides along on every signal value for exactly that reason.

Only block-grained reports can carry these columns: both sources key on a
block. The farm-grained weather summary and the operations timeline are
deliberately not wired up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text as SAText

from .schemas import CustomFieldDef, CustomFieldOption, CustomFieldValue

# The two sources a report column may come from. `crop_attribute` resolves
# against the block's current crop assignment; `signal` against the latest
# in-window observation on the block.
CROP_ATTRIBUTE = "crop_attribute"
SIGNAL = "signal"
CUSTOM_FIELD_SOURCES: tuple[str, ...] = (CROP_ATTRIBUTE, SIGNAL)

# Cap on how many custom columns one report may carry. A picker that let the
# user tick every definition in a large catalog would widen the table past
# anything printable, for no gain over picking the handful that matter.
MAX_CUSTOM_FIELDS = 12


@dataclass(frozen=True, slots=True)
class CustomFieldRef:
    """A parsed ``source:code`` column reference."""

    source: str
    code: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.code}"


def parse_field_refs(raw: str | None) -> list[CustomFieldRef]:
    """``"crop_attribute:brix,signal:trap_count"`` → refs, order preserved.

    Unknown sources and malformed entries are dropped rather than raising. The
    param is a display preference that outlives the definition it names: it is
    persisted by the FE and pasted into shared report URLs, so a 422 here would
    break a bookmark rather than tell anybody anything. Duplicates collapse to
    the first occurrence.

    >>> [r.key for r in parse_field_refs("signal:x, crop_attribute:y ,junk")]
    ['signal:x', 'crop_attribute:y']
    >>> parse_field_refs(None)
    []
    """
    if not raw:
        return []
    seen: set[str] = set()
    refs: list[CustomFieldRef] = []
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry or ":" not in entry:
            continue
        source, _, code = entry.partition(":")
        source = source.strip()
        code = code.strip()
        if source not in CUSTOM_FIELD_SOURCES or not code:
            continue
        ref = CustomFieldRef(source=source, code=code)
        if ref.key in seen:
            continue
        seen.add(ref.key)
        refs.append(ref)
        if len(refs) >= MAX_CUSTOM_FIELDS:
            break
    return refs


def _codes(refs: list[CustomFieldRef], source: str) -> list[str]:
    return [ref.code for ref in refs if ref.source == source]


# --- Catalog ----------------------------------------------------------------


async def list_custom_fields(session: AsyncSession, *, farm_id: UUID) -> list[CustomFieldDef]:
    """Every custom column offerable on ``farm_id``, both sources.

    Farm-scoped on purpose. The flat platform catalog
    (``GET /crops/attribute-definitions``) lists every definition for every
    crop on the platform; offering that as report columns would fill the picker
    with fields no block on this farm can ever hold a value for.
    """
    attributes = await _select_farm_crop_attributes(session, farm_id=farm_id)
    signals = await _select_farm_signals(session, farm_id=farm_id)
    return attributes + signals


async def _select_farm_crop_attributes(
    session: AsyncSession, *, farm_id: UUID
) -> list[CustomFieldDef]:
    """Reportable attribute definitions that resolve for a crop on this farm.

    The join is a **prefix match** against the crop paths currently on the
    farm, so a definition on ``mango`` is offerable to a
    ``mango.alphonso.short`` block. Where two levels define the same ``code``
    the deepest row wins — the same deepest-wins rule
    ``farms.crop_attributes.resolve_definitions`` applies, expressed here as
    ``ORDER BY length(d.path) DESC`` because the value rows are already keyed
    by the resolved ``definition_code``.

    ``is_reportable`` is honoured: an attribute the platform marked as not for
    reporting never reaches the picker.
    """
    sql = text(
        """
        WITH farm_paths AS (
            SELECT DISTINCT bc.crop_path AS crop_path
            FROM block_crops bc
            JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
            WHERE b.farm_id = :farm_id
              AND bc.deleted_at IS NULL
              AND bc.is_current IS TRUE
              AND bc.crop_path IS NOT NULL
              AND bc.crop_path <> ''
        )
        SELECT DISTINCT ON (d.code)
               d.code, d.name_en, d.name_ar, d.value_type,
               d.unit_en, d.unit_ar, d.options, d.decimal_places
        FROM public.crop_attribute_definitions d
        JOIN farm_paths fp
          ON fp.crop_path = d.path
          OR fp.crop_path LIKE d.path || '.%'
        WHERE d.deleted_at IS NULL
          AND d.is_active IS TRUE
          AND d.is_reportable IS TRUE
        ORDER BY d.code, length(d.path) DESC
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    rows = (await session.execute(sql, {"farm_id": farm_id})).mappings().all()
    out = [
        CustomFieldDef(
            key=f"{CROP_ATTRIBUTE}:{row['code']}",
            source=CROP_ATTRIBUTE,
            code=row["code"],
            name_en=row["name_en"],
            name_ar=row["name_ar"],
            value_type=row["value_type"],
            unit_en=row["unit_en"],
            unit_ar=row["unit_ar"],
            decimal_places=row["decimal_places"],
            options=_attribute_options(row["options"]),
        )
        for row in rows
    ]
    out.sort(key=lambda d: d.name_en.lower())
    return out


def _attribute_options(raw: Any) -> list[CustomFieldOption] | None:
    """``options`` JSONB → the picker's option list, or None for a non-select.

    Defensive about the row shape: the column is JSONB, so a hand-written seed
    can put anything in it, and a malformed entry should cost that one option
    rather than the whole report.
    """
    if not raw:
        return None
    options = [
        CustomFieldOption(
            code=str(entry["code"]),
            name_en=str(entry.get("name_en") or entry["code"]),
            name_ar=(str(entry["name_ar"]) if entry.get("name_ar") else None),
        )
        for entry in raw
        if isinstance(entry, dict) and entry.get("code")
    ]
    return options or None


async def _select_farm_signals(session: AsyncSession, *, farm_id: UUID) -> list[CustomFieldDef]:
    """Signal definitions this farm can show a column for.

    Two-tier resolution as in ``signals.repository``: platform rows
    (``tenant_id IS NULL``) plus this tenant's, one row per ``code``, the
    tenant's winning a collision.

    A definition qualifies on **either** of two grounds, and the second is not
    a nicety:

    1. An active assignment names the farm, names a block on the farm, or is
       tenant-wide (both NULL). This is what the entry surfaces read.
    2. The farm already holds an observation of it.

    Ground 2 exists because an observation does **not** require an assignment.
    ``signal_observations`` has no foreign key to ``signal_assignments`` and
    nothing on the write path checks one, so a signal can be recorded — by CSV
    import, by a template submission, by the API — against a definition that
    was never assigned, or whose assignment was later retired. Found on prod
    the day this shipped: ``fruit_tss_brix`` on Bashier Elkhier had 145
    observations across 36 blocks and no assignment row at all, so the picker
    offered eight crop attributes and not the one signal the farm actually
    uses. The data was there and the column was unreachable.

    The tell for this shape of bug is always the same: the rows exist and the
    read that is keyed on a different table says the farm has nothing.
    """
    sql = text(
        """
        SELECT DISTINCT ON (d.code)
               d.code, d.name, d.value_kind, d.unit, d.categorical_values
        FROM public.signal_definitions d
        WHERE d.deleted_at IS NULL
          AND d.is_active IS TRUE
          AND (d.tenant_id IS NULL OR d.tenant_id = (
                SELECT x.id FROM public.tenants x
                 WHERE replace(x.id::text, '-', '')
                       = replace(current_schema(), 'tenant_', '')))
          AND (
            EXISTS (
                SELECT 1 FROM signal_assignments a
                 WHERE a.signal_definition_id = d.id
                   AND a.deleted_at IS NULL
                   AND a.is_active IS TRUE
                   AND (
                         (a.farm_id IS NULL AND a.block_id IS NULL)
                      OR (a.farm_id = :farm_id)
                      OR (a.block_id IN (
                             SELECT b.id FROM blocks b
                              WHERE b.farm_id = :farm_id AND b.deleted_at IS NULL))
                   )
            )
            OR EXISTS (
                SELECT 1 FROM signal_observations o
                 WHERE o.signal_definition_id = d.id
                   AND o.farm_id = :farm_id
            )
          )
        ORDER BY d.code, d.tenant_id NULLS LAST
        """
    ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))

    rows = (await session.execute(sql, {"farm_id": farm_id})).mappings().all()
    out = [
        CustomFieldDef(
            key=f"{SIGNAL}:{row['code']}",
            source=SIGNAL,
            code=row["code"],
            name_en=row["name"],
            # Signal definitions carry a single `name` — there is no Arabic
            # column on that catalog — so the FE falls back to name_en.
            name_ar=None,
            value_type=row["value_kind"],
            unit_en=row["unit"],
            unit_ar=row["unit"],
            decimal_places=None,
            options=[
                CustomFieldOption(code=value, name_en=value, name_ar=None)
                for value in (row["categorical_values"] or [])
            ]
            or None,
        )
        for row in rows
    ]
    out.sort(key=lambda d: d.name_en.lower())
    return out


# --- Values -----------------------------------------------------------------


async def load_custom_values(
    session: AsyncSession,
    *,
    farm_id: UUID,
    refs: list[CustomFieldRef],
    since: datetime,
    until: datetime,
) -> dict[UUID, dict[str, CustomFieldValue]]:
    """``{block_id: {ref_key: value}}`` for the picked columns.

    At most two queries however many columns were picked, and none at all when
    nothing was picked — so a report nobody has customised pays nothing for the
    feature.
    """
    if not refs:
        return {}
    out: dict[UUID, dict[str, CustomFieldValue]] = {}

    attribute_codes = _codes(refs, CROP_ATTRIBUTE)
    if attribute_codes:
        for block_id, value in await _select_attribute_values(
            session, farm_id=farm_id, codes=attribute_codes
        ):
            out.setdefault(block_id, {})[value.key] = value

    signal_codes = _codes(refs, SIGNAL)
    if signal_codes:
        for block_id, value in await _select_signal_values(
            session, farm_id=farm_id, codes=signal_codes, since=since, until=until
        ):
            out.setdefault(block_id, {})[value.key] = value

    return out


async def _select_attribute_values(
    session: AsyncSession, *, farm_id: UUID, codes: list[str]
) -> list[tuple[UUID, CustomFieldValue]]:
    """Current-assignment attribute values for the whole farm in one pass."""
    sql = text(
        """
        SELECT bc.block_id,
               v.definition_code AS code,
               v.value_numeric, v.value_text, v.value_boolean,
               v.value_date, v.value_option, v.value_options
        FROM block_crops bc
        JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
        JOIN block_crop_attribute_values v
          ON v.block_crop_id = bc.id AND v.deleted_at IS NULL
        WHERE b.farm_id = :farm_id
          AND bc.deleted_at IS NULL
          AND bc.is_current IS TRUE
          AND v.definition_code = ANY(:codes)
        """
    ).bindparams(
        bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
        bindparam("codes", type_=PG_ARRAY(SAText())),
    )

    rows = (await session.execute(sql, {"farm_id": farm_id, "codes": codes})).mappings().all()
    return [
        (
            row["block_id"],
            CustomFieldValue(
                key=f"{CROP_ATTRIBUTE}:{row['code']}",
                source=CROP_ATTRIBUTE,
                code=row["code"],
                value_numeric=row["value_numeric"],
                # A single-select stores its chosen option code in
                # `value_option`; both land in `value_text` so the FE has one
                # place to read a scalar string from. The option list on the
                # definition is what turns the code back into a label.
                value_text=row["value_text"] or row["value_option"],
                value_boolean=row["value_boolean"],
                value_date=row["value_date"],
                value_options=row["value_options"],
                observed_at=None,
            ),
        )
        for row in rows
    ]


async def _select_signal_values(
    session: AsyncSession, *, farm_id: UUID, codes: list[str], since: datetime, until: datetime
) -> list[tuple[UUID, CustomFieldValue]]:
    """Latest in-window observation per (block, signal code).

    ``block_id IS NULL`` rows are farm-level observations. They are skipped
    rather than broadcast onto every block: a column repeating one farm-wide
    reading down 40 rows reads as 40 measurements.
    """
    sql = text(
        """
        SELECT DISTINCT ON (o.block_id, d.code)
               o.block_id, d.code, o.time AS observed_at,
               o.value_numeric, o.value_categorical, o.value_event, o.value_boolean
        FROM signal_observations o
        JOIN public.signal_definitions d ON d.id = o.signal_definition_id
        WHERE o.farm_id = :farm_id
          AND o.block_id IS NOT NULL
          AND d.code = ANY(:codes)
          AND o.time >= :since
          AND o.time < :until
        ORDER BY o.block_id, d.code, o.time DESC
        """
    ).bindparams(
        bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
        bindparam("codes", type_=PG_ARRAY(SAText())),
    )

    params: dict[str, Any] = {
        "farm_id": farm_id,
        "codes": codes,
        "since": since,
        "until": until,
    }
    rows = (await session.execute(sql, params)).mappings().all()
    return [
        (
            row["block_id"],
            CustomFieldValue(
                key=f"{SIGNAL}:{row['code']}",
                source=SIGNAL,
                code=row["code"],
                value_numeric=row["value_numeric"],
                value_text=row["value_categorical"] or row["value_event"],
                value_boolean=row["value_boolean"],
                value_date=None,
                value_options=None,
                observed_at=row["observed_at"],
            ),
        )
        for row in rows
    ]
