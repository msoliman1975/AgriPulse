"""Wire shapes for the farm timeline.

Every event is one shape regardless of which table it came from, so the
rail and the scrubber render generically. What differs per kind lives in
``code`` (the enum-ish value the frontend translates) and ``detail`` (free
text nobody can translate).

Bilingual text is carried as two fields rather than resolved server-side.
Alerts and recommendations already store both languages; a caller that
switches language must not have to refetch.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# The seven datapoint families the replay carries. `stage` is block-scope
# only: blocks on one farm run different plans, so a farm-wide stage row
# would be a lie about 34 of 35 blocks.
EventKind = Literal[
    "stage",
    "signal",
    "activity",
    "visit",
    "flag",
    "alert",
    "recommendation",
]

ALL_KINDS: tuple[str, ...] = (
    "stage",
    "signal",
    "activity",
    "visit",
    "flag",
    "alert",
    "recommendation",
)

# Which capability gates each kind. The endpoint itself is gated on
# `farm.read`; a kind the caller cannot read is dropped from the payload
# and named in `omitted_kinds`, rather than 403-ing the whole screen.
# A Scout holds farm scopes and no tenant role, so most of these are
# denied for them — the timeline still has to render.
KIND_CAPABILITY: dict[str, str] = {
    "stage": "block.read",
    "signal": "signal.read",
    "activity": "plan.read",
    "visit": "scouting.visit.read",
    "flag": "scouting.visit.read",
    "alert": "alert.read",
    "recommendation": "recommendation.read",
}


class TimelineEvent(BaseModel):
    """One datapoint on one day."""

    model_config = ConfigDict(from_attributes=True)

    kind: EventKind
    # Text, not UUID: a signal observation's identity is (time, id) and a
    # few sources hand back composite keys. The frontend only ever uses
    # this as a React key and a deep-link segment.
    id: str
    at: datetime
    # The UTC calendar day this lands on. Derived in SQL with an explicit
    # `AT TIME ZONE 'UTC'`, because `EXTRACT`/`::date` on a timestamptz
    # follows the session TimeZone and would bucket differently per pod.
    day: date

    block_id: UUID | None = None
    block_name: str | None = None
    block_name_ar: str | None = None
    block_code: str | None = None

    # The enum-ish value the frontend translates: activity_type, rule_code,
    # stage code, action_type, signal definition code. Null when the source
    # has none.
    code: str | None = None
    title_en: str
    title_ar: str | None = None
    detail: str | None = None
    # Raw from the source table — info / warning / critical, or the visit's
    # own vocabulary. The frontend maps it to a marker severity.
    severity: str | None = None
    # GeoJSON Point, or null when the row is block-scoped rather than
    # located. A null point draws no mark; the block outline carries it.
    point: dict[str, Any] | None = None


class TimelineDay(BaseModel):
    """Per-day counts, for the scrubber's event ticks."""

    model_config = ConfigDict(from_attributes=True)

    day: date
    counts: dict[str, int]
    total: int


class TimelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    farm_id: UUID
    block_id: UUID | None = None
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    events: list[TimelineEvent]
    days: list[TimelineDay]
    # Kinds the caller has no capability for. Named so the UI can say
    # "you cannot see alerts" instead of showing an empty lane that reads
    # as "nothing happened".
    omitted_kinds: list[str]
    # True when any one kind hit its row cap. The window is the fix, and
    # the UI has to say so rather than quietly showing a partial day.
    truncated: bool
