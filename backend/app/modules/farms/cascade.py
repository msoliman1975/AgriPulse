"""Cross-module cascade helpers for block / farm inactivation.

When the user inactivates a block (or farm, which fans out to its
blocks), several downstream tables need to be reconciled so the
inactive entity stops generating new noise:

* alerts.alerts                  — open ones are resolved
* irrigation.irrigation_schedules — future pending rows skipped
* plans.plan_activities           — future scheduled rows skipped
* weather.weather_subscriptions   — active subs deactivated
* imagery.imagery_aoi_subscriptions — active subs deactivated

Each helper is idempotent and runs against the caller's tenant
session — the farms service shares a single transaction with the
cascade so the entity write and the side effects either all commit or
all roll back.

Two flavours per cascade:

  * ``preview_*``  — returns the counts that *would* be affected. Used
    to populate the confirm-modal numbers.
  * ``apply_*``    — performs the writes and returns the actual
    affected counts (typically equal to the preview taken inside the
    same transaction, modulo concurrent modifications between the two
    calls).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CascadeCounts:
    """Per-cascade tally used by both preview and apply paths."""

    alerts_resolved: int = 0
    irrigation_skipped: int = 0
    plan_activities_skipped: int = 0
    weather_subs_deactivated: int = 0
    imagery_subs_deactivated: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "alerts_resolved": self.alerts_resolved,
            "irrigation_skipped": self.irrigation_skipped,
            "plan_activities_skipped": self.plan_activities_skipped,
            "weather_subs_deactivated": self.weather_subs_deactivated,
            "imagery_subs_deactivated": self.imagery_subs_deactivated,
        }


def _empty(block_ids: Iterable[UUID]) -> bool:
    return not list(block_ids)


async def preview_block_cascade(
    *,
    session: AsyncSession,
    block_ids: Iterable[UUID],
    cutoff: date | None = None,
) -> CascadeCounts:
    """Return the counts the cascade would touch without writing anything."""
    ids = list(block_ids)
    if not ids:
        return CascadeCounts()
    cutoff_date = cutoff or datetime.now(UTC).date()

    alerts_n = await _scalar_count(
        session,
        text(
            """
            SELECT count(*) FROM alerts
            WHERE block_id = ANY(:block_ids)
              AND status IN ('open', 'acknowledged', 'snoozed')
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids},
    )
    irrig_n = await _scalar_count(
        session,
        text(
            """
            SELECT count(*) FROM irrigation_schedules
            WHERE block_id = ANY(:block_ids)
              AND status = 'pending'
              AND scheduled_for >= :cutoff
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids, "cutoff": cutoff_date},
    )
    acts_n = await _scalar_count(
        session,
        text(
            """
            SELECT count(*) FROM plan_activities
            WHERE block_id = ANY(:block_ids)
              AND status IN ('scheduled', 'in_progress')
              AND scheduled_date >= :cutoff
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids, "cutoff": cutoff_date},
    )
    weather_n = await _scalar_count(
        session,
        text(
            """
            SELECT count(*) FROM weather_subscriptions
            WHERE block_id = ANY(:block_ids) AND is_active = TRUE
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids},
    )
    imagery_n = await _scalar_count(
        session,
        text(
            """
            SELECT count(*) FROM imagery_aoi_subscriptions
            WHERE block_id = ANY(:block_ids) AND is_active = TRUE
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids},
    )
    return CascadeCounts(
        alerts_resolved=alerts_n,
        irrigation_skipped=irrig_n,
        plan_activities_skipped=acts_n,
        weather_subs_deactivated=weather_n,
        imagery_subs_deactivated=imagery_n,
    )


async def apply_block_cascade(
    *,
    session: AsyncSession,
    block_ids: Iterable[UUID],
    actor_user_id: UUID | None,
    cutoff: date | None = None,
    reason_code: str = "block_inactivated",
) -> CascadeCounts:
    """Run the cascade. Idempotent: re-running on the same block_ids is a no-op."""
    ids = list(block_ids)
    if not ids:
        return CascadeCounts()
    cutoff_date = cutoff or datetime.now(UTC).date()

    alerts_n = await _execute_rowcount(
        session,
        text(
            """
            UPDATE alerts
            SET status = 'resolved',
                resolved_at = now(),
                resolved_by = :actor,
                snoozed_until = NULL,
                updated_by = :actor
            WHERE block_id = ANY(:block_ids)
              AND status IN ('open', 'acknowledged', 'snoozed')
            """
        ).bindparams(
            bindparam("actor", type_=PG_UUID(as_uuid=True)),
            bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
        ),
        {"actor": actor_user_id, "block_ids": ids},
    )
    irrig_n = await _execute_rowcount(
        session,
        text(
            """
            UPDATE irrigation_schedules
            SET status = 'skipped',
                updated_by = :actor
            WHERE block_id = ANY(:block_ids)
              AND status = 'pending'
              AND scheduled_for >= :cutoff
            """
        ).bindparams(
            bindparam("actor", type_=PG_UUID(as_uuid=True)),
            bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
        ),
        {"actor": actor_user_id, "block_ids": ids, "cutoff": cutoff_date},
    )
    acts_n = await _execute_rowcount(
        session,
        text(
            """
            UPDATE plan_activities
            SET status = 'skipped',
                updated_by = :actor
            WHERE block_id = ANY(:block_ids)
              AND status IN ('scheduled', 'in_progress')
              AND scheduled_date >= :cutoff
            """
        ).bindparams(
            bindparam("actor", type_=PG_UUID(as_uuid=True)),
            bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
        ),
        {"actor": actor_user_id, "block_ids": ids, "cutoff": cutoff_date},
    )
    weather_n = await _execute_rowcount(
        session,
        text(
            """
            UPDATE weather_subscriptions
            SET is_active = FALSE,
                updated_at = now()
            WHERE block_id = ANY(:block_ids) AND is_active = TRUE
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids},
    )
    imagery_n = await _execute_rowcount(
        session,
        text(
            """
            UPDATE imagery_aoi_subscriptions
            SET is_active = FALSE,
                updated_at = now()
            WHERE block_id = ANY(:block_ids) AND is_active = TRUE
            """
        ).bindparams(bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True)))),
        {"block_ids": ids},
    )
    # `reason_code` is informational for now — wired into audit details
    # by the caller; no separate "reasons" table exists yet.
    del reason_code
    return CascadeCounts(
        alerts_resolved=alerts_n,
        irrigation_skipped=irrig_n,
        plan_activities_skipped=acts_n,
        weather_subs_deactivated=weather_n,
        imagery_subs_deactivated=imagery_n,
    )


async def _scalar_count(session: AsyncSession, stmt: Any, params: dict[str, Any]) -> int:
    row = (await session.execute(stmt, params)).scalar_one_or_none()
    return int(row or 0)


async def _execute_rowcount(session: AsyncSession, stmt: Any, params: dict[str, Any]) -> int:
    result = await session.execute(stmt, params)
    return int(cast("CursorResult[Any]", result).rowcount or 0)
