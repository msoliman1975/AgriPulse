"""Composition for the farm timeline.

Turns seven differently-shaped tables into one list of events and one
per-day count map, and drops the kinds the caller has no capability for.

The seven reads are awaited in sequence on ONE session, not gathered. An
``AsyncSession`` is not safe for concurrent use, and seven sequential
index lookups over a 90-day window cost far less than seven connections
out of a 15-slot pool — the fan-out shape that exhausted it in #311. If
this ever needs to be parallel it needs its own sessions, not a ``gather``
over this one.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import RequestContext
from app.shared.rbac.check import has_capability

from .repository import ROW_CAP, TimelineRepository, get_timeline_repository
from .schemas import ALL_KINDS, KIND_CAPABILITY, TimelineDay, TimelineEvent, TimelineResponse

# How far a window may span. A year of one farm's events is the most a
# person can read; beyond that the row caps start deciding what is shown,
# which is worse than being told the window is too wide.
MAX_WINDOW_DAYS = 366


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _trim_number(value: str) -> str:
    """Drop the trailing zeros a NUMERIC(14,4) brings with it.

    `value_numeric::text` renders 6.4 as "6.4000", because the column keeps
    four decimal places whether or not the reading has them. Every test
    asserted on the structure of the payload and passed; the line was still
    wrong to read on the page. Only trailing zeros AFTER a decimal point are
    touched, so an integer reading stays "28" and a scale reading like
    "0.1200" becomes "0.12" without ever turning 120 into 12.
    """
    if "." not in value:
        return value
    try:
        float(value)
    except ValueError:
        # Not a number at all — a categorical value that happens to contain
        # a dot. Return it untouched rather than trimming somebody's text.
        return value
    return value.rstrip("0").rstrip(".")


def _signal_title(row: dict[str, Any]) -> str:
    """A definition name, its value, and its unit — every part optional.

    Composed from data rather than translated, because the definition name
    and the categorical value are tenant-authored strings that exist in one
    language only. A definition the join missed falls back to the code, and
    then to an empty title the frontend replaces with the kind's own label.
    """
    name = _text(row.get("definition_name")) or _text(row.get("code")) or ""
    value = _text(row.get("value_text"))
    if value is None:
        return name
    value = _trim_number(value)
    unit = _text(row.get("unit"))
    return f"{name}: {value} {unit}".rstrip() if unit else f"{name}: {value}"


class TimelineService:
    def __init__(self, repo: TimelineRepository) -> None:
        self._repo = repo

    async def block_belongs_to_farm(self, *, farm_id: UUID, block_id: UUID) -> bool:
        """Whether the block is on the farm the URL names. See the repository."""
        return await self._repo.block_belongs_to_farm(farm_id=farm_id, block_id=block_id)

    async def get_timeline(
        self,
        *,
        farm_id: UUID,
        block_id: UUID | None,
        from_date: date,
        to_date: date,
        context: RequestContext,
    ) -> TimelineResponse:
        # Half-open [from 00:00 UTC, to+1 00:00 UTC) so the last day is
        # whole. Real datetimes, tz-aware, so asyncpg binds a timestamptz
        # rather than a string the server has to guess a zone for.
        from_ts = datetime.combine(from_date, time.min, tzinfo=UTC)
        to_ts = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        params = {
            "farm_id": farm_id,
            "block_id": block_id,
            "from_ts": from_ts,
            "to_ts": to_ts,
        }

        allowed, omitted = self._split_kinds(farm_id=farm_id, context=context, block_id=block_id)

        events: list[TimelineEvent] = []
        truncated = False

        for kind in allowed:
            rows = await self._read(kind, params)
            if len(rows) >= ROW_CAP:
                truncated = True
            events.extend(self._to_events(kind, rows))

        # One stable order for the rail and for the day buckets: by
        # instant, then by kind, then by id. Without the tiebreakers two
        # events recorded in the same second reorder between requests and
        # the rail visibly reshuffles on every refetch.
        events.sort(key=lambda e: (e.at, e.kind, e.id))

        return TimelineResponse(
            farm_id=farm_id,
            block_id=block_id,
            **{"from": from_date, "to": to_date},
            events=events,
            days=self._day_counts(events),
            omitted_kinds=list(omitted),
            truncated=truncated,
        )

    # ---- kinds ------------------------------------------------------------

    def _split_kinds(
        self, *, farm_id: UUID, context: RequestContext, block_id: UUID | None
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Which kinds this caller may read, and which were dropped.

        Dropping rather than 403-ing is the point. A Scout holds farm
        scopes and no tenant role, so several of these are denied for
        them; the replay still has to render the parts they can see.

        ``stage`` is not "denied" in farm scope — it does not apply. Blocks
        on one farm run different plans, so a farm-wide stage row would be
        untrue about every block but one. It is left out of both lists.
        """
        allowed: list[str] = []
        omitted: list[str] = []
        for kind in ALL_KINDS:
            if kind == "stage" and block_id is None:
                continue
            if has_capability(context, KIND_CAPABILITY[kind], farm_id=farm_id):
                allowed.append(kind)
            else:
                omitted.append(kind)
        return tuple(allowed), tuple(omitted)

    async def _read(self, kind: str, params: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        reader = {
            "stage": self._repo.stages,
            "signal": self._repo.signals,
            "activity": self._repo.activities,
            "visit": self._repo.visits,
            "flag": self._repo.flags,
            "alert": self._repo.alerts,
            "recommendation": self._repo.recommendations,
        }[kind]
        return await reader(**params)

    # ---- row -> event -----------------------------------------------------

    def _to_events(self, kind: str, rows: tuple[dict[str, Any], ...]) -> list[TimelineEvent]:
        return [self._to_event(kind, r) for r in rows]

    def _to_event(self, kind: str, row: dict[str, Any]) -> TimelineEvent:
        # Per kind: which column is the human title, which is the free-text
        # detail, and whether the row carries a point at all. Only alerts
        # and recommendations store both languages; everything else has one
        # tenant-authored string, which is returned as-is under title_en and
        # rendered unchanged in either locale.
        title_en = ""
        title_ar: str | None = None
        detail: str | None = None
        severity = _text(row.get("severity"))

        if kind == "signal":
            title_en = _signal_title(row)
            detail = _text(row.get("notes"))
        elif kind == "flag":
            title_en = _text(row.get("note")) or ""
            detail = _text(row.get("status"))
        elif kind == "activity":
            title_en = _text(row.get("product_name")) or ""
            detail = _text(row.get("notes")) or _text(row.get("dosage"))
        elif kind == "visit":
            title_en = _text(row.get("title")) or ""
            detail = _text(row.get("summary_note")) or _text(row.get("outcome"))
        elif kind == "alert":
            title_en = _text(row.get("diagnosis_en")) or ""
            title_ar = _text(row.get("diagnosis_ar"))
            detail = _text(row.get("rule_code"))
        elif kind == "recommendation":
            title_en = _text(row.get("text_en")) or ""
            title_ar = _text(row.get("text_ar"))
            detail = _text(row.get("tree_code"))
        elif kind == "stage":
            # The stage code IS the title; the frontend translates it and
            # falls back to the raw code for a tenant-authored stage.
            title_en = _text(row.get("code")) or ""
            detail = _text(row.get("notes")) or _text(row.get("source"))

        return TimelineEvent(
            kind=kind,
            id=str(row["id"]),
            at=row["at"],
            day=row["day"],
            block_id=row.get("block_id"),
            block_name=_text(row.get("block_name")),
            block_code=_text(row.get("block_code")),
            code=_text(row.get("code")),
            title_en=title_en,
            title_ar=title_ar,
            detail=detail,
            severity=severity,
            point=row.get("point"),
        )

    # ---- day buckets ------------------------------------------------------

    def _day_counts(self, events: list[TimelineEvent]) -> list[TimelineDay]:
        """Counts per day, for the scrubber's ticks.

        Only days that HAVE events appear. The frontend builds one frame
        per calendar day across the whole window and looks each day up
        here, so an empty day costs nothing to send and would only pad the
        payload.
        """
        buckets: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in events:
            buckets[e.day][e.kind] += 1
        return [
            TimelineDay(day=d, counts=dict(counts), total=sum(counts.values()))
            for d, counts in sorted(buckets.items())
        ]


def get_timeline_service(session: AsyncSession) -> TimelineService:
    return TimelineService(get_timeline_repository(session))
