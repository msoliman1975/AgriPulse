"""Manifest-driven purge engine.

Both halves of a purge — the impact preview an admin confirms against, and the
DELETEs that follow — are generated from :mod:`app.shared.purge.registry`. That
is deliberate: a preview computed by different code from the delete is a preview
that can lie.

Transaction shape
-----------------
Everything in :meth:`PurgeEngine.delete` runs inside the caller's transaction, so
a failure anywhere rolls the whole thing back and a dry run is just a rollback.
Two things cannot participate:

* object-storage deletes — S3 has no transactions, so keys are *collected*
  inside the transaction and handed back for the caller to delete after commit;
* ``refresh_continuous_aggregate`` — Timescale forbids it inside a transaction
  block, so it is likewise deferred (see :meth:`refresh_caggs`).

Both are therefore ordered after the commit, which is the safe direction: an
orphaned object costs storage, whereas deleting objects for a transaction that
then rolls back would lose data that still has rows pointing at it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.shared.purge.registry import (
    BLOCK_CAGGS,
    BLOCK_OWNED,
    FARM_OWNED,
    TENANT_PUBLIC_OWNED,
    OwnedTable,
    ordered,
)

logger = logging.getLogger(__name__)

_IDS = bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True)))


@dataclass
class PurgeReport:
    """What a purge counted or did, per table."""

    # table name -> row count. Zero-count tables are omitted so the UI's
    # "what will be deleted" list stays readable.
    rows: dict[str, int] = field(default_factory=dict)
    # Object-storage keys owned by the deleted rows, gathered pre-delete.
    storage_keys: list[str] = field(default_factory=list)
    # Time span of deleted block_index_aggregates rows, bounding the CAGG
    # refresh so it does not recompute the tenant's entire history.
    cagg_range: tuple[datetime, datetime] | None = None

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())

    def merge(self, other: PurgeReport) -> None:
        for table, n in other.rows.items():
            self.rows[table] = self.rows.get(table, 0) + n
        self.storage_keys.extend(other.storage_keys)
        if other.cagg_range is not None:
            if self.cagg_range is None:
                self.cagg_range = other.cagg_range
            else:
                self.cagg_range = (
                    min(self.cagg_range[0], other.cagg_range[0]),
                    max(self.cagg_range[1], other.cagg_range[1]),
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": dict(sorted(self.rows.items())),
            "total_rows": self.total_rows,
            "storage_objects": len(self.storage_keys),
        }


class PurgeEngine:
    """Executes the manifest against one tenant session.

    The session must already have ``search_path`` pointing at the target tenant
    schema (public tables in the manifest are schema-qualified, so they resolve
    either way).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # -- block ---------------------------------------------------------------

    async def expand_blocks(self, block_ids: list[UUID]) -> list[UUID]:
        """Add descendant pivot sectors to ``block_ids``.

        ``blocks.parent_unit_id`` is RESTRICT, so a pivot cannot be deleted while
        its sectors exist. Purging a pivot means purging its sectors — that is
        what the admin asked for, and the preview says so.
        """
        if not block_ids:
            return []
        rows = await self._s.execute(
            text(
                """
                WITH RECURSIVE tree AS (
                    SELECT id FROM blocks WHERE id = ANY(:ids)
                    UNION
                    SELECT b.id FROM blocks b JOIN tree t ON b.parent_unit_id = t.id
                )
                SELECT id FROM tree
                """
            ).bindparams(_IDS),
            {"ids": block_ids},
        )
        return [r[0] for r in rows]

    async def preview_blocks(self, block_ids: list[UUID]) -> PurgeReport:
        return await self._count(BLOCK_OWNED, block_ids)

    async def delete_blocks(self, block_ids: list[UUID]) -> PurgeReport:
        """Delete everything owned by ``block_ids``, then the block rows.

        Callers pass ids already expanded by :meth:`expand_blocks`.
        """
        if not block_ids:
            return PurgeReport()
        report = await self._capture_cagg_range(block_ids)
        report.merge(await self._delete(BLOCK_OWNED, block_ids))

        # Sectors before their parent pivots (parent_unit_id is RESTRICT).
        deleted = await self._rowcount(
            text(
                """
                WITH RECURSIVE tree AS (
                    SELECT id, parent_unit_id, 0 AS depth
                      FROM blocks WHERE id = ANY(:ids)
                    UNION ALL
                    SELECT b.id, b.parent_unit_id, t.depth + 1
                      FROM blocks b JOIN tree t ON b.parent_unit_id = t.id
                )
                DELETE FROM blocks WHERE id IN (SELECT id FROM tree)
                """
            ).bindparams(_IDS),
            {"ids": block_ids},
        )
        report.rows["blocks"] = report.rows.get("blocks", 0) + deleted
        return report

    # -- farm ----------------------------------------------------------------

    async def farm_block_ids(self, farm_ids: list[UUID]) -> list[UUID]:
        if not farm_ids:
            return []
        rows = await self._s.execute(
            text("SELECT id FROM blocks WHERE farm_id = ANY(:ids)").bindparams(_IDS),
            {"ids": farm_ids},
        )
        return [r[0] for r in rows]

    async def preview_farms(self, farm_ids: list[UUID]) -> PurgeReport:
        report = await self._count(BLOCK_OWNED, await self.farm_block_ids(farm_ids))
        report.merge(await self._count(FARM_OWNED, farm_ids))
        blocks = await self._scalar(
            text("SELECT count(*) FROM blocks WHERE farm_id = ANY(:ids)").bindparams(_IDS),
            {"ids": farm_ids},
        )
        if blocks:
            report.rows["blocks"] = blocks
        return report

    async def delete_farms(self, farm_ids: list[UUID]) -> PurgeReport:
        """Purge child blocks first (blocks.farm_id is RESTRICT), then the farm."""
        if not farm_ids:
            return PurgeReport()
        report = await self.delete_blocks(await self.farm_block_ids(farm_ids))
        report.merge(await self._delete(FARM_OWNED, farm_ids))
        report.rows["resources_archived"] = await self._archive_farmless_resources()
        report.rows["farms"] = await self._rowcount(
            text("DELETE FROM farms WHERE id = ANY(:ids)").bindparams(_IDS),
            {"ids": farm_ids},
        )
        return report

    async def _archive_farmless_resources(self) -> int:
        """Archive workers and equipment the purge left with no farm at all.

        Since W2-A a resource is tenant-level: the farm link lives in
        ``resource_farms``, which the manifest has just emptied for the purged
        farms. Anything still linked elsewhere is shared and must survive
        untouched.

        What is left over is archived rather than deleted, for the same reason
        every other retirement in this codebase is: ``activity_resources`` rows
        on *other* farms name this resource, and a hard delete would cascade
        them away — erasing who did the work, on farms that were not purged.
        Archived rows keep their name so historical assignments still read.
        """
        return await self._rowcount(
            text(
                """
                UPDATE resources r
                   SET archived_at = now(), updated_at = now()
                 WHERE r.archived_at IS NULL
                   AND NOT EXISTS (
                         SELECT 1 FROM resource_farms rf WHERE rf.resource_id = r.id
                       )
                """
            ),
            {},
        )

    # -- tenant (public-schema residue only) ---------------------------------

    async def preview_tenant_public(self, tenant_ids: list[UUID]) -> PurgeReport:
        return await self._count(TENANT_PUBLIC_OWNED, tenant_ids)

    async def delete_tenant_public(self, tenant_ids: list[UUID]) -> PurgeReport:
        """Delete the tenant's public-schema rows, then the tenant row.

        The tenant *schema* is dropped separately by the caller; this is the
        residue that DROP SCHEMA cannot reach and that nothing cleaned up before.
        """
        if not tenant_ids:
            return PurgeReport()
        report = await self._delete(TENANT_PUBLIC_OWNED, tenant_ids)
        report.rows["tenants"] = await self._rowcount(
            text("DELETE FROM public.tenants WHERE id = ANY(:ids)").bindparams(_IDS),
            {"ids": tenant_ids},
        )
        return report

    # -- continuous aggregates ----------------------------------------------

    @staticmethod
    def cagg_names() -> tuple[str, ...]:
        return tuple(view for view, _ in BLOCK_CAGGS)

    async def _capture_cagg_range(self, block_ids: list[UUID]) -> PurgeReport:
        """Bound the post-commit CAGG refresh to the deleted block's data span."""
        report = PurgeReport()
        row = (
            await self._s.execute(
                text(
                    "SELECT min(time), max(time) FROM block_index_aggregates "
                    "WHERE block_id = ANY(:ids)"
                ).bindparams(_IDS),
                {"ids": block_ids},
            )
        ).one_or_none()
        if row is not None and row[0] is not None:
            report.cagg_range = (row[0], row[1])
        return report

    # -- shared --------------------------------------------------------------

    async def _count(self, group: tuple[OwnedTable, ...], ids: list[UUID]) -> PurgeReport:
        report = PurgeReport()
        if not ids:
            return report
        for owned in ordered(group):
            n = await self._scalar(
                text(
                    f"SELECT count(*) FROM {owned.qualified()} WHERE {owned.predicate()}"  # noqa: S608
                ).bindparams(_IDS),
                {"ids": ids},
            )
            if n:
                report.rows[owned.table] = report.rows.get(owned.table, 0) + n
        return report

    async def _delete(self, group: tuple[OwnedTable, ...], ids: list[UUID]) -> PurgeReport:
        report = PurgeReport()
        if not ids:
            return report
        for owned in ordered(group):
            if owned.storage_key_column is not None:
                report.storage_keys.extend(await self._collect_keys(owned, ids))
            n = await self._rowcount(
                text(
                    f"DELETE FROM {owned.qualified()} WHERE {owned.predicate()}"  # noqa: S608
                ).bindparams(_IDS),
                {"ids": ids},
            )
            if n:
                report.rows[owned.table] = report.rows.get(owned.table, 0) + n
        return report

    async def _collect_keys(self, owned: OwnedTable, ids: list[UUID]) -> list[str]:
        col = owned.storage_key_column
        rows = await self._s.execute(
            text(
                f"SELECT {col} FROM {owned.qualified()} "  # noqa: S608
                f"WHERE ({owned.predicate()}) AND {col} IS NOT NULL"
            ).bindparams(_IDS),
            {"ids": ids},
        )
        return [r[0] for r in rows]

    async def _scalar(self, stmt: Any, params: dict[str, Any]) -> int:
        return int((await self._s.execute(stmt, params)).scalar_one_or_none() or 0)

    async def _rowcount(self, stmt: Any, params: dict[str, Any]) -> int:
        result = await self._s.execute(stmt, params)
        return int(getattr(result, "rowcount", 0) or 0)


async def refresh_caggs(
    *,
    engine_url: str,
    tenant_schema: str,
    window: tuple[datetime, datetime] | None,
) -> list[str]:
    """Re-materialise the block index aggregates after a purge.

    Both CAGGs run with ``materialized_only = false``, so a purged block keeps
    appearing in every chart that reads them until the already-materialised
    buckets are recomputed. ``refresh_continuous_aggregate`` is a procedure that
    cannot run inside a transaction block, hence the dedicated autocommit
    connection rather than reusing the caller's session.

    ``window`` bounds the work to the purged block's data span. Passing None
    skips the refresh entirely — correct when the purge deleted no aggregate
    rows, which is the common case for a block that never had imagery.
    """
    if window is None:
        return []
    start, end = window
    refreshed: list[str] = []
    engine = create_async_engine(engine_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for view, _source in BLOCK_CAGGS:
                try:
                    await conn.execute(
                        text(
                            f'CALL refresh_continuous_aggregate(\'"{tenant_schema}"."{view}"\', '
                            ":start, :end)"
                        ),
                        {"start": start, "end": end},
                    )
                    refreshed.append(view)
                except Exception:
                    # A failed refresh leaves stale aggregate rows, not lost
                    # data. Surface it on the receipt rather than failing a
                    # purge whose DB work has already committed.
                    logger.warning(
                        "cagg_refresh_failed", extra={"view": view, "schema": tenant_schema}
                    )
    finally:
        await engine.dispose()
    return refreshed
