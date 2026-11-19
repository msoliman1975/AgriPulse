"""Open a build farm's active window before the span the replay walks.

Every sweep asks which blocks exist on its day: `active_from <= today` and
`active_to` unset or later. A farm drawn in the app today gets today as its
`active_from`, so a replay of the two years before it finds no block on any
day and the engine evaluates nothing, while steps that do not check the
window (the grid anomaly sweep) still run. The first Medjool rebuild did
exactly that: 105 weeks of `blocks_processed: 0`.

The API sets `active_from` only when a farm or block is created. This moves
it earlier for one build farm and its live blocks, and never later: a block
already active before the date keeps its own. It runs behind the same build
tenant guard as the rest of the package, and writes an audit row.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.logging import get_logger
from app.shared.db.session import sanitize_tenant_schema

_log = get_logger(__name__)

AUDIT_EVENT = "demo_history.active_window_opened"


async def open_active_window(
    session_factory: Any, tenant_schema: str, farm_code: str, active_from: date
) -> dict[str, Any]:
    """Move the farm's and its blocks' `active_from` back to `active_from`."""
    safe = sanitize_tenant_schema(tenant_schema)
    async with session_factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        farm_id = (
            await session.execute(
                text("SELECT id FROM farms WHERE code = :c AND deleted_at IS NULL"),
                {"c": farm_code},
            )
        ).scalar_one_or_none()
        if farm_id is None:
            raise ValueError(f"no farm with code {farm_code} in {tenant_schema}")
        farms = await session.execute(
            text("UPDATE farms SET active_from = :d WHERE id = :f AND active_from > :d").bindparams(
                bindparam("f", type_=PG_UUID(as_uuid=True))
            ),
            {"f": farm_id, "d": active_from},
        )
        blocks = await session.execute(
            text(
                "UPDATE blocks SET active_from = :d "
                "WHERE farm_id = :f AND deleted_at IS NULL AND active_from > :d"
            ).bindparams(bindparam("f", type_=PG_UUID(as_uuid=True))),
            {"f": farm_id, "d": active_from},
        )
        counts = {
            "active_from": active_from.isoformat(),
            "farms": int(getattr(farms, "rowcount", 0) or 0),
            "blocks": int(getattr(blocks, "rowcount", 0) or 0),
        }
        await session.execute(
            text(
                """
                INSERT INTO audit_events
                    (time, id, event_type, actor_user_id, actor_kind, subject_kind,
                     subject_id, farm_id, details)
                VALUES (clock_timestamp(), :id, :ev, NULL, 'system', 'farm',
                        :farm, :farm, CAST(:details AS jsonb))
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": uuid4(), "ev": AUDIT_EVENT, "farm": farm_id, "details": json.dumps(counts)},
        )
    _log.info("demo_history_active_window_opened", **counts)
    return counts


__all__ = ["AUDIT_EVENT", "open_active_window"]
