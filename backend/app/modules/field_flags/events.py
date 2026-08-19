"""Public event types for field flags.

Versioned per ARCHITECTURE.md § 6.1 — bumping the suffix is a breaking schema
change for subscribers.

Only `critical` raises this. The two lower severities are found on the map,
which is where a supervisor already looks; announcing every flag would
reproduce the alert bombardment this platform has spent a release undoing.

The payload carries everything a notification needs to render, for the same
reason the scouting and alert events do: a sync subscriber runs on its own
connection and cannot read the not-yet-committed row.
"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class FieldFlagRaisedV1(Event):
    event_name: ClassVar[str] = "field_flags.raised.v1"

    flag_id: UUID
    farm_id: UUID
    block_id: UUID
    severity: str
    # First line of the note — the title every surface shows.
    title: str
    raised_by_user_id: UUID
    tenant_schema: str | None = None
