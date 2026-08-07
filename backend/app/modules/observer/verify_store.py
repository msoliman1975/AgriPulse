"""Persistence for Observer's own two tables (tenant migration 0060).

Kept separate from ``repository.py`` on purpose: that module is a read-only
window onto other modules' pipeline tables, and this one owns rows. Mixing
them would blur the boundary the whole design rests on — Observer reads the
pipeline and writes only its own findings.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Statuses that still occupy a farm — the partial unique index uses the same
# set, so this constant and the migration must agree.
ACTIVE_STATUSES = ("queued", "running")

_RUN_COLS = """
    id, farm_id, block_ids, product_id, window_from, window_to,
    mode, status, progress, error, created_by_email,
    created_at, started_at, completed_at
"""


class VerifyRunConflictError(Exception):
    """The farm already has a verification in flight."""

    def __init__(self, existing: dict[str, Any]) -> None:
        super().__init__("a verification run is already in progress for this farm")
        self.existing = existing


class VerifyStore:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ---- runs ------------------------------------------------------------

    async def active_for_farm(self, farm_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(
                    f"""
                    SELECT {_RUN_COLS} FROM observer_verify_runs
                     WHERE farm_id = :fid AND status IN ('queued', 'running')
                     LIMIT 1
                    """  # noqa: S608 - only the _RUN_COLS constant interpolates
                ),
                {"fid": str(farm_id)},
            )
        ).mappings()
        found = row.first()
        return dict(found) if found else None

    async def create_run(
        self,
        *,
        farm_id: UUID,
        block_ids: list[UUID] | None,
        product_id: UUID | None,
        window_from: datetime,
        window_to: datetime,
        mode: str,
        created_by_email: str | None,
    ) -> dict[str, Any]:
        """Claim the farm and create a queued run.

        The partial unique index is the real guard; this pre-check exists to
        turn the race's loser into a clean 409 with the existing run's id
        rather than an integrity error the operator cannot act on.
        """
        existing = await self.active_for_farm(farm_id)
        if existing is not None:
            raise VerifyRunConflictError(existing)

        row = (
            await self._s.execute(
                text(
                    f"""
                    INSERT INTO observer_verify_runs (
                        farm_id, block_ids, product_id,
                        window_from, window_to, mode, created_by_email
                    ) VALUES (
                        :fid, :bids, :pid, :wfrom, :wto, :mode, :email
                    )
                    RETURNING {_RUN_COLS}
                    """
                ).bindparams(
                    bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    bindparam("pid", type_=PG_UUID(as_uuid=True)),
                    bindparam("bids", type_=ARRAY(PG_UUID(as_uuid=True))),
                ),
                {
                    "fid": farm_id,
                    "bids": block_ids,
                    "pid": product_id,
                    # Real datetimes, never isoformat strings: the columns are
                    # timestamptz and asyncpg types the parameter from the
                    # Python object. A string here is the DataError family.
                    "wfrom": window_from,
                    "wto": window_to,
                    "mode": mode,
                    "email": created_by_email,
                },
            )
        ).mappings()
        return dict(row.one())

    async def list_runs(self, *, farm_id: UUID | None, limit: int) -> list[dict[str, Any]]:
        where = "WHERE farm_id = :fid" if farm_id else ""
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT {_RUN_COLS} FROM observer_verify_runs
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """  # noqa: S608 - _RUN_COLS + a closed-set WHERE clause
                ),
                {"fid": str(farm_id) if farm_id else None, "limit": limit},
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        rows = (
            await self._s.execute(
                text(f"SELECT {_RUN_COLS} FROM observer_verify_runs WHERE id = :rid"),  # noqa: S608
                {"rid": str(run_id)},
            )
        ).mappings()
        found = rows.first()
        return dict(found) if found else None

    async def mark_running(self, run_id: UUID, *, total: int) -> None:
        await self._s.execute(
            text(
                """
                UPDATE observer_verify_runs
                   SET status = 'running',
                       started_at = COALESCE(started_at, now()),
                       progress = CAST(:progress AS jsonb)
                 WHERE id = :rid AND status = 'queued'
                """
            ),
            {
                "rid": str(run_id),
                # jsonb needs the value as text plus an explicit cast — the
                # driver cannot type a dict, and `jsonb_build_object` with a
                # bind is the shape that has broken here before.
                "progress": json.dumps(
                    {"scenes_total": total, "scenes_done": 0, "match": 0, "drift": 0, "error": 0}
                ),
            },
        )

    async def bump_progress(self, run_id: UUID, *, verdict: str) -> None:
        """Increment the done counter and the bucket this verdict falls in.

        Done in SQL rather than read-modify-write so a worker crash between
        the two halves cannot leave the counters disagreeing with the rows in
        `observer_verifications`.
        """
        bucket = verdict if verdict in ("match", "drift") else "error"
        await self._s.execute(
            text(
                """
                UPDATE observer_verify_runs
                   SET progress = jsonb_set(
                           jsonb_set(
                               progress,
                               '{scenes_done}',
                               to_jsonb(COALESCE((progress->>'scenes_done')::int, 0) + 1)
                           ),
                           ARRAY[CAST(:bucket AS text)],
                           to_jsonb(
                               COALESCE((progress->>CAST(:bucket AS text))::int, 0) + 1
                           )
                       )
                 WHERE id = :rid
                """
            ),
            {"rid": str(run_id), "bucket": bucket},
        )

    async def finish_run(self, run_id: UUID, *, status: str, error: str | None) -> None:
        await self._s.execute(
            text(
                """
                UPDATE observer_verify_runs
                   SET status = :status,
                       error = :error,
                       completed_at = now()
                 WHERE id = :rid
                """
            ),
            {"rid": str(run_id), "status": status, "error": error},
        )

    async def cancel_run(self, run_id: UUID) -> dict[str, Any] | None:
        """Release a run that is still queued or running.

        Returns None when there was nothing to cancel, so the caller can tell
        "no such run" from "already finished" — retrying helps in neither
        case, but they mean very different things to an operator.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    UPDATE observer_verify_runs
                       SET status = 'cancelled', completed_at = now()
                     WHERE id = :rid AND status IN ('queued', 'running')
                    RETURNING {_RUN_COLS}
                    """  # noqa: S608 - only the _RUN_COLS constant interpolates
                ),
                {"rid": str(run_id)},
            )
        ).mappings()
        found = rows.first()
        return dict(found) if found else None

    async def is_cancelled(self, run_id: UUID) -> bool:
        """Checked between scenes so a cancel takes effect without a kill."""
        row = (
            await self._s.execute(
                text("SELECT status FROM observer_verify_runs WHERE id = :rid"),
                {"rid": str(run_id)},
            )
        ).first()
        return row is not None and str(row[0]) == "cancelled"

    # ---- results ---------------------------------------------------------

    async def insert_verification(
        self,
        *,
        run_id: UUID | None,
        job_id: UUID | None,
        block_id: UUID,
        product_id: UUID,
        scene_time: datetime,
        scene_id: str,
        mode: str,
        verdict: str,
        per_index: dict[str, Any],
        calc_version_stored: str | None,
        error: str | None,
        duration_ms: int | None,
    ) -> dict[str, Any]:
        row = (
            await self._s.execute(
                text(
                    """
                    INSERT INTO observer_verifications (
                        run_id, job_id, block_id, product_id, scene_time,
                        scene_id, mode, verdict, per_index,
                        calc_version_stored, error, duration_ms
                    ) VALUES (
                        :run_id, :job_id, :block_id, :product_id, :scene_time,
                        :scene_id, :mode, :verdict, CAST(:per_index AS jsonb),
                        :calc_version, :error, :duration_ms
                    )
                    RETURNING id, run_id, job_id, block_id, product_id,
                              scene_time, scene_id, mode, verdict, per_index,
                              calc_version_stored, error, duration_ms, created_at
                    """
                ).bindparams(
                    bindparam("run_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("job_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("block_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("product_id", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "block_id": block_id,
                    "product_id": product_id,
                    "scene_time": scene_time,
                    "scene_id": scene_id,
                    "mode": mode,
                    "verdict": verdict,
                    "per_index": json.dumps(per_index),
                    "calc_version": calc_version_stored,
                    "error": error,
                    "duration_ms": duration_ms,
                },
            )
        ).mappings()
        return dict(row.one())

    async def list_verifications(
        self, *, run_id: UUID, verdict: str | None, limit: int
    ) -> list[dict[str, Any]]:
        clause = "AND verdict = :verdict" if verdict else ""
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT id, run_id, job_id, block_id, product_id, scene_time,
                           scene_id, mode, verdict, per_index,
                           calc_version_stored, error, duration_ms, created_at
                      FROM observer_verifications
                     WHERE run_id = :rid
                       {clause}
                     ORDER BY scene_time DESC
                     LIMIT :limit
                    """
                ),
                {"rid": str(run_id), "verdict": verdict, "limit": limit},
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def latest_for_scene(
        self, *, block_id: UUID, product_id: UUID, scene_time: datetime
    ) -> dict[str, Any] | None:
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT id, run_id, job_id, block_id, product_id, scene_time,
                           scene_id, mode, verdict, per_index,
                           calc_version_stored, error, duration_ms, created_at
                      FROM observer_verifications
                     WHERE block_id = :bid AND product_id = :pid
                       AND scene_time = :st
                     ORDER BY created_at DESC, id DESC
                     LIMIT 1
                    """
                ),
                {"bid": str(block_id), "pid": str(product_id), "st": scene_time},
            )
        ).mappings()
        found = rows.first()
        return dict(found) if found else None
