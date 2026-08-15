"""Purge service — preview, submit, and run hard deletes.

Covers ``block``, ``farm`` and ``tenant_data`` (wipe a tenant's farms and blocks
but keep the tenant, its Keycloak group, users, settings and integration keys).
Whole-tenant purge stays in :mod:`app.modules.tenancy.service`, which owns the
status machine, the Keycloak teardown and the schema drop; it calls into the
same shared manifest and reclaimer so both paths delete the same things.

Archive first, then purge
-------------------------
A block or farm must already be archived (``deleted_at IS NOT NULL``) before it
can be purged, and ``tenant_data`` requires the tenant to be suspended or
pending-delete. The cooling-off step is cheap, reversible, and means an
irreversible action is never one click away from a live entity.

Two sessions
------------
Job and receipt bookkeeping runs on its own session, committed as it goes. The
deletes run on a second session in a single transaction. They have to be
separate: a dry run rolls the work session back, and the whole point is that the
job row and its measured counts survive that rollback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.purge.repository import PurgeConflictError, PurgeRepository
from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema
from app.shared.purge.engine import PurgeEngine, PurgeReport, refresh_caggs
from app.shared.purge.imagery import ImageryReclaimer, ReclaimPlan
from app.shared.purge.scanner import scan_tenant_schema

logger = logging.getLogger(__name__)

PurgeKind = Literal["block", "farm", "tenant_data"]

# Above either of these a purge is queued to a worker instead of run in the
# request. Both are deliberately low: a request that deletes 200 R2 objects
# serially is already past the point where a browser should be holding it open.
INLINE_MAX_ROWS = 50_000
INLINE_MAX_OBJECTS = 200


class PurgeError(Exception):
    """Base for purge failures that map to a 4xx."""


class TargetNotFoundError(PurgeError):
    pass


class NotArchivedError(PurgeError):
    """Archive-first: the entity must be archived before it can be purged."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"{kind} must be archived before it can be purged")
        self.kind = kind


class ConfirmationMismatchError(PurgeError):
    pass


@dataclass
class Target:
    """A resolved purge target plus everything the preview needs to describe it."""

    kind: str
    id: UUID
    label: str
    confirmation_phrase: str
    tenant_id: UUID
    tenant_schema: str
    tenant_slug: str | None
    archived: bool
    blocking: list[dict[str, str]] = field(default_factory=list)


class PurgeService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self._repo = PurgeRepository(session)

    # -- resolution ----------------------------------------------------------

    async def resolve(self, *, kind: str, target_id: UUID, tenant_id: UUID) -> Target:
        tenant = await self._tenant(tenant_id)
        schema = sanitize_tenant_schema(tenant["schema_name"])

        if kind == "tenant_data":
            # The tenant-level analogue of archive-first: take the tenant out of
            # service before wiping every farm it owns.
            archived = tenant["status"] in ("suspended", "pending_delete")
            return Target(
                kind=kind,
                id=tenant_id,
                label=tenant["name"] or tenant["slug"],
                confirmation_phrase=tenant["slug"],
                tenant_id=tenant_id,
                tenant_schema=schema,
                tenant_slug=tenant["slug"],
                archived=archived,
                blocking=(
                    []
                    if archived
                    else [
                        {
                            "reason": "tenant_not_suspended",
                            "detail": "Suspend the tenant before wiping its data.",
                        }
                    ]
                ),
            )

        table = "blocks" if kind == "block" else "farms"
        label_col = "code" if kind == "block" else "name"
        row = await self._one(
            schema,
            f"SELECT id, {label_col} AS label, name, deleted_at "  # noqa: S608
            f"FROM {table} WHERE id = :id",
            {"id": str(target_id)},
        )
        if row is None:
            raise TargetNotFoundError(f"{kind} {target_id} not found in this tenant")

        archived = row["deleted_at"] is not None
        label = row["label"] or row["name"] or str(target_id)
        return Target(
            kind=kind,
            id=target_id,
            label=label,
            confirmation_phrase=label,
            tenant_id=tenant_id,
            tenant_schema=schema,
            tenant_slug=tenant["slug"],
            archived=archived,
            blocking=(
                []
                if archived
                else [
                    {
                        "reason": "not_archived",
                        "detail": f"Archive the {kind} first — purge is not reversible.",
                    }
                ]
            ),
        )

    # -- preview -------------------------------------------------------------

    async def preview(self, *, kind: str, target_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        """Impact report. Read-only and safe to call as often as the UI likes."""
        target = await self.resolve(kind=kind, target_id=target_id, tenant_id=tenant_id)
        return await self.preview_for(target)

    async def preview_for(self, target: Target) -> dict[str, Any]:
        """Impact report for an already-resolved target.

        Split from :meth:`preview` so ``submit`` — which has to resolve the
        target anyway to check the confirmation phrase — does not resolve it a
        second time and re-open a session to do so.
        """
        async with _work_session(target.tenant_schema) as work:
            engine = PurgeEngine(work)
            report, plan = await self._plan(engine, target, work)
        return {
            "kind": target.kind,
            "id": str(target.id),
            "label": target.label,
            "confirmation_phrase": target.confirmation_phrase,
            "tenant_id": str(target.tenant_id),
            "tenant_slug": target.tenant_slug,
            "archived": target.archived,
            "blocking": target.blocking,
            "db_rows": [
                {"table": t, "rows": n} for t, n in sorted(report.rows.items(), key=_by_rows)
            ],
            "total_rows": report.total_rows,
            "storage": {
                "attachment_objects": len(report.storage_keys),
                "imagery_objects": len(plan.object_keys),
                "imagery_objects_kept_shared": len(plan.shared_keys_kept),
            },
            "pgstac": {"items": len(plan.items), "collections": len(plan.collections)},
        }

    async def _plan(
        self, engine: PurgeEngine, target: Target, work: AsyncSession
    ) -> tuple[PurgeReport, ReclaimPlan]:
        """Count rows and plan imagery reclamation for a target. No writes."""
        farm_ids, block_ids = await _target_ids(engine, target.kind, target.id, work)
        plan = await ImageryReclaimer(work).plan_for_blocks(
            tenant_schema=target.tenant_schema, block_ids=block_ids
        )
        if target.kind == "block":
            report = await engine.preview_blocks(block_ids)
            report.rows["blocks"] = len(block_ids)
        else:
            report = await engine.preview_farms(farm_ids)
            if farm_ids:
                report.rows["farms"] = len(farm_ids)
        return report, plan

    # -- submit --------------------------------------------------------------

    async def submit(
        self,
        *,
        kind: str,
        target_id: UUID,
        tenant_id: UUID,
        confirmation: str,
        reason: str | None,
        dry_run: bool,
        actor_id: UUID | None,
        actor_email: str | None,
    ) -> dict[str, Any]:
        """Validate, record a job, and either run it inline or queue it.

        Returns the job row. A completed inline job already has its receipt.
        """
        target = await self.resolve(kind=kind, target_id=target_id, tenant_id=tenant_id)
        if confirmation != target.confirmation_phrase:
            raise ConfirmationMismatchError(
                f"confirmation must match {target.confirmation_phrase!r}"
            )
        # A dry run writes nothing, so it may rehearse a live entity — that is
        # how an admin finds out what archiving would commit them to.
        if not target.archived and not dry_run:
            raise NotArchivedError(kind)

        preview = await self.preview_for(target)

        # The job row is written on its own session and committed immediately.
        # It must be visible to the runner (which opens fresh sessions) and must
        # survive the work session's rollback on a dry run — neither is true if
        # it shares the request's transaction.
        factory = AsyncSessionLocal()
        async with factory() as book, book.begin():
            job = await PurgeRepository(book).create_job(
                kind=kind,
                target_id=target_id,
                target_label=target.label,
                tenant_id=target.tenant_id,
                tenant_schema=target.tenant_schema,
                tenant_slug=target.tenant_slug,
                preview=preview,
                dry_run=dry_run,
                reason=reason,
                created_by=actor_id,
                created_by_email=actor_email,
            )
        job_id = UUID(str(job["id"]))

        if _fits_inline(preview):
            await run_job(job_id)
            async with factory() as book, book.begin():
                repo = PurgeRepository(book)
                refreshed = await repo.get_job(job_id)
                if refreshed is not None:
                    refreshed["receipt"] = await repo.get_receipt_for_job(job_id)
                    return refreshed
            return job

        from celery import current_app as celery_current_app

        celery_current_app.send_task("purge.run_job", kwargs={"job_id": str(job_id)}, queue="heavy")
        return job

    # -- reads ---------------------------------------------------------------

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        job = await self._repo.get_job(job_id)
        if job is None:
            return None
        job["receipt"] = await self._repo.get_receipt_for_job(job_id)
        return job

    async def list_jobs(
        self, *, tenant_id: UUID | None, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        return await self._repo.list_jobs(tenant_id=tenant_id, status=status, limit=limit)

    async def list_receipts(self, *, limit: int) -> list[dict[str, Any]]:
        return await self._repo.list_receipts(limit=limit)

    async def list_tenant_entities(self, tenant_id: UUID) -> dict[str, Any]:
        """Farms and blocks of one tenant, for the platform Data tab.

        Platform admins have no farm/block UI anywhere else — every existing
        farm surface is tenant-scoped and resolves its tenant from the JWT.
        """
        tenant = await self._tenant(tenant_id)
        schema = sanitize_tenant_schema(tenant["schema_name"])
        async with _work_session(schema) as work:
            rows = (
                await work.execute(
                    text(
                        """
                        SELECT f.id AS farm_id, f.name AS farm_name, f.code AS farm_code,
                               f.deleted_at AS farm_deleted_at,
                               b.id AS block_id, b.name AS block_name, b.code AS block_code,
                               b.deleted_at AS block_deleted_at, b.unit_type
                          FROM farms f
                          LEFT JOIN blocks b ON b.farm_id = f.id
                         ORDER BY f.name NULLS LAST, b.code NULLS LAST
                        """
                    )
                )
            ).mappings()
            farms: dict[UUID, dict[str, Any]] = {}
            for r in rows:
                farm = farms.setdefault(
                    r["farm_id"],
                    {
                        "id": str(r["farm_id"]),
                        "name": r["farm_name"],
                        "code": r["farm_code"],
                        "archived": r["farm_deleted_at"] is not None,
                        "blocks": [],
                    },
                )
                if r["block_id"] is not None:
                    farm["blocks"].append(
                        {
                            "id": str(r["block_id"]),
                            "name": r["block_name"],
                            "code": r["block_code"],
                            "unit_type": r["unit_type"],
                            "archived": r["block_deleted_at"] is not None,
                        }
                    )
        return {
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant["slug"],
            "tenant_status": tenant["status"],
            "farms": list(farms.values()),
        }

    # -- helpers -------------------------------------------------------------

    async def _tenant(self, tenant_id: UUID) -> dict[str, Any]:
        row = (
            await self._s.execute(
                text(
                    "SELECT id, name, slug, schema_name, status FROM public.tenants "
                    "WHERE id = :id"
                ),
                {"id": str(tenant_id)},
            )
        ).mappings()
        found = row.one_or_none()
        if found is None:
            raise TargetNotFoundError(f"tenant {tenant_id} not found")
        return dict(found)

    async def _one(self, schema: str, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        async with _work_session(schema) as work:
            row = (await work.execute(text(sql), params)).mappings().one_or_none()
            return dict(row) if row else None


async def _target_ids(
    engine: PurgeEngine, kind: str, target_id: UUID, work: AsyncSession
) -> tuple[list[UUID], list[UUID]]:
    """The ``(farm_ids, block_ids)`` a purge of this kind touches.

    Defined once and used by both the preview and the delete. When these two
    derived their own id sets they could drift, and a preview that counts a
    different set of rows than the delete removes is precisely the failure this
    feature cannot have.
    """
    if kind == "block":
        return [], await engine.expand_blocks([target_id])
    if kind == "farm":
        return [target_id], await engine.farm_block_ids([target_id])
    # tenant_data — every farm in the tenant.
    farm_ids = [r[0] for r in await work.execute(text("SELECT id FROM farms"))]
    return farm_ids, await engine.farm_block_ids(farm_ids)


# --- execution --------------------------------------------------------------


async def run_job(job_id: UUID) -> dict[str, Any]:
    """Execute one purge job end to end and write its receipt.

    Phase order is forced by what can and cannot be rolled back. Everything
    reversible happens inside one transaction; the irreversible outside-the-
    database work (object deletes, STAC deletes, aggregate refresh) happens only
    after that transaction has committed. Getting this backwards would delete
    COGs for a purge that then rolled back, losing data whose rows still exist.
    """
    factory = AsyncSessionLocal()
    async with factory() as book, book.begin():
        repo = PurgeRepository(book)
        job = await repo.get_job(job_id)
        if job is None:
            raise TargetNotFoundError(f"purge job {job_id} not found")
        await repo.mark_running(job_id)

    schema = sanitize_tenant_schema(str(job["tenant_schema"]))
    kind = str(job["kind"])
    target_id = UUID(str(job["target_id"]))
    dry_run = bool(job["dry_run"])
    errors: list[str] = []
    deleted: dict[str, Any] = {}

    try:
        report, plan = await _run_db_phase(schema, kind, target_id, dry_run)
        deleted["db_rows"] = dict(sorted(report.rows.items()))
        deleted["total_rows"] = report.total_rows
        await _record(job_id, "db_rows", {"tables": len(report.rows), "rows": report.total_rows})

        if dry_run:
            # Nothing after this point is reversible, so a rehearsal stops here
            # with real measured counts and an untouched system.
            deleted["dry_run"] = True
            deleted["storage_objects_planned"] = len(report.storage_keys) + len(plan.object_keys)
            deleted["stac_items_planned"] = len(plan.items)
            verification = {"skipped": "dry run"}
        else:
            reclaim, storage_deleted = await _run_external_phase(
                schema=schema, report=report, plan=plan
            )
            errors.extend(reclaim.errors)
            deleted["storage_objects"] = storage_deleted + reclaim.objects_deleted
            deleted["objects_kept_shared"] = reclaim.objects_kept_shared
            deleted["stac_items"] = reclaim.stac_items_deleted
            deleted["stac_collections"] = reclaim.stac_collections_deleted
            await _record(job_id, "storage", {"objects": deleted["storage_objects"]})

            refreshed = await refresh_caggs(
                engine_url=str(get_settings().database_url),
                tenant_schema=schema,
                window=report.cagg_range,
            )
            deleted["caggs_refreshed"] = refreshed
            await _record(job_id, "cagg_refresh", {"views": refreshed})

            verification = await _verify(schema)
            await _record(job_id, "verify", verification)

        status = "succeeded"
    except Exception as exc:
        logger.exception("purge_job_failed", extra={"job_id": str(job_id)})
        async with factory() as book, book.begin():
            await PurgeRepository(book).finish_job(job_id, status="failed", error=str(exc))
        raise

    async with factory() as book, book.begin():
        repo = PurgeRepository(book)
        fresh = await repo.get_job(job_id) or job
        await repo.create_receipt(
            job=fresh,
            job_id=job_id,
            actor_user_id=(UUID(str(fresh["created_by"])) if fresh.get("created_by") else None),
            actor_email=fresh.get("created_by_email"),
            deleted=deleted,
            verification=verification,
            errors=errors,
        )
        await repo.finish_job(job_id, status=status, error=None)
    return deleted


async def _run_db_phase(
    schema: str, kind: str, target_id: UUID, dry_run: bool
) -> tuple[PurgeReport, ReclaimPlan]:
    """All DB work in one transaction; rolled back wholesale for a dry run."""
    factory = AsyncSessionLocal()
    async with factory() as work:
        await work.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        engine = PurgeEngine(work)
        farm_ids, block_ids = await _target_ids(engine, kind, target_id, work)

        # Planned before the delete: after it, the aoi_hash values that decide
        # which COGs are safe to remove no longer exist.
        plan = await ImageryReclaimer(work).plan_for_blocks(
            tenant_schema=schema, block_ids=block_ids
        )

        report = (
            await engine.delete_blocks(block_ids)
            if kind == "block"
            else await engine.delete_farms(farm_ids)
        )

        if dry_run:
            await work.rollback()
        else:
            await work.commit()
        return report, plan


async def _run_external_phase(
    *, schema: str, report: PurgeReport, plan: ReclaimPlan
) -> tuple[Any, int]:
    """Object-storage and STAC cleanup. Runs only after the DB commit."""
    del schema
    from app.shared.storage.client import get_storage_client

    storage = get_storage_client()
    storage_deleted = 0
    for key in report.storage_keys:
        try:
            storage.delete_object(key=key)
            storage_deleted += 1
        except Exception:
            logger.warning("purge_object_delete_failed", extra={"key": key})

    factory = AsyncSessionLocal()
    async with factory() as pub, pub.begin():
        reclaim = await ImageryReclaimer(pub).execute(plan, storage=storage)
    return reclaim, storage_deleted


async def _verify(schema: str) -> dict[str, Any]:
    """Independent re-scan. A purge that leaves orphans reports itself failed.

    No ``begin()``: the scanner runs its counting on its own AUTOCOMMIT
    connection so each batch's chunk locks are released immediately, and
    wrapping the call in a transaction here would only hold a second, idle one
    open for the length of the scan.
    """
    factory = AsyncSessionLocal()
    async with factory() as pub:
        return (await scan_tenant_schema(pub, schema)).as_dict()


async def _record(job_id: UUID, phase: str, detail: dict[str, Any]) -> None:
    factory = AsyncSessionLocal()
    async with factory() as book, book.begin():
        await PurgeRepository(book).set_phase(job_id, phase, detail)


def _fits_inline(preview: dict[str, Any]) -> bool:
    objects = preview["storage"]["attachment_objects"] + preview["storage"]["imagery_objects"]
    return int(preview["total_rows"]) <= INLINE_MAX_ROWS and objects <= INLINE_MAX_OBJECTS


def _by_rows(item: tuple[str, int]) -> tuple[int, str]:
    # Biggest tables first — that is what an admin scans the impact list for.
    return (-item[1], item[0])


class _WorkSession:
    """Read-only tenant-scoped session for previews and lookups."""

    def __init__(self, schema: str) -> None:
        self._schema = sanitize_tenant_schema(schema)
        self._ctx: Any = None

    async def __aenter__(self) -> AsyncSession:
        factory = AsyncSessionLocal()
        self._ctx = factory()
        session: AsyncSession = await self._ctx.__aenter__()
        await session.execute(text(f'SET LOCAL search_path TO "{self._schema}", public'))
        return session

    async def __aexit__(self, *exc: Any) -> None:
        await self._ctx.__aexit__(*exc)


def _work_session(schema: str) -> _WorkSession:
    return _WorkSession(schema)


def get_purge_service(session: AsyncSession) -> PurgeService:
    return PurgeService(session)


__all__ = [
    "ConfirmationMismatchError",
    "NotArchivedError",
    "PurgeConflictError",
    "PurgeError",
    "PurgeService",
    "TargetNotFoundError",
    "get_purge_service",
    "run_job",
]
