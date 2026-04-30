"""Cross-schema FK consistency check for `public.farm_scopes`.

Per ARCHITECTURE.md § 5: the FK from `public.farm_scopes.farm_id` into
each `tenant_<id>.farms` table is *logical* — the database can't enforce
it across schemas. This module is the periodic backstop: every hour
(see `workers/beat/main.py`), scan all active `farm_scopes` and audit
any that point at a farm that no longer exists in its tenant.

We never delete the orphaned scope. The audit row is the signal; ops or
a future janitor decides whether to revoke. That keeps this job
side-effect-free as a defense-in-depth check.

The scan groups by tenant schema so we issue at most one query per
tenant rather than one per scope. Schema names go through
`sanitize_tenant_schema()` before any interpolation; a malformed schema
short-circuits with an audit log entry rather than failing the whole run.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema

_AUDIT_EVENT_TYPE = "farms.farm_scope_orphan_detected"


async def run_farm_scope_consistency_check(
    *,
    audit_service: AuditService | None = None,
) -> dict[str, int]:
    """Scan once and audit any orphans. Return a count summary.

    The summary shape is `{ "scopes_checked": N, "orphans_detected": M,
    "schemas_skipped": K }`. Workers log it; tests assert against it.
    """
    audit = audit_service or get_audit_service()
    log = get_logger(__name__)

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        scopes = await _load_active_scopes(session)

    if not scopes:
        return {"scopes_checked": 0, "orphans_detected": 0, "schemas_skipped": 0}

    by_schema: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped_schemas = 0
    for scope in scopes:
        try:
            safe = sanitize_tenant_schema(scope["schema_name"])
        except ValueError:
            skipped_schemas += 1
            log.warning(
                "farm_scope_consistency.invalid_schema",
                schema_name=scope["schema_name"],
                farm_scope_id=str(scope["farm_scope_id"]),
            )
            continue
        by_schema[safe].append(scope)

    orphans_detected = 0
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        for schema, schema_scopes in by_schema.items():
            farm_ids = [s["farm_id"] for s in schema_scopes]
            existing = await _existing_farms_in_schema(session, schema=schema, farm_ids=farm_ids)
            for scope in schema_scopes:
                if scope["farm_id"] in existing:
                    continue
                orphans_detected += 1
                await audit.record(
                    tenant_schema=schema,
                    event_type=_AUDIT_EVENT_TYPE,
                    actor_user_id=None,
                    actor_kind="system",
                    subject_kind="farm_scope_orphan",
                    subject_id=scope["farm_scope_id"],
                    farm_id=scope["farm_id"],
                    details={
                        "membership_id": str(scope["membership_id"]),
                        "tenant_id": str(scope["tenant_id"]),
                        "role": scope["role"],
                        "schema_name": schema,
                    },
                )

    log.info(
        "farm_scope_consistency.completed",
        scopes_checked=len(scopes),
        orphans_detected=orphans_detected,
        schemas_skipped=skipped_schemas,
        schemas_scanned=len(by_schema),
    )
    return {
        "scopes_checked": len(scopes),
        "orphans_detected": orphans_detected,
        "schemas_skipped": skipped_schemas,
    }


async def _load_active_scopes(session: AsyncSession) -> list[dict[str, Any]]:
    """All non-revoked farm_scopes joined to their tenant's schema_name."""
    stmt = text(
        """
        SELECT
            fs.id            AS farm_scope_id,
            fs.farm_id       AS farm_id,
            fs.membership_id AS membership_id,
            fs.role          AS role,
            t.id             AS tenant_id,
            t.schema_name    AS schema_name
        FROM public.farm_scopes fs
        JOIN public.tenant_memberships tm ON tm.id = fs.membership_id
        JOIN public.tenants t              ON t.id = tm.tenant_id
        WHERE fs.revoked_at IS NULL
          AND tm.status = 'active'
          AND t.status = 'active'
        """
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "farm_scope_id": r.farm_scope_id,
            "farm_id": r.farm_id,
            "membership_id": r.membership_id,
            "role": r.role,
            "tenant_id": r.tenant_id,
            "schema_name": r.schema_name,
        }
        for r in rows
    ]


async def _existing_farms_in_schema(
    session: AsyncSession, *, schema: str, farm_ids: list[UUID]
) -> set[UUID]:
    """Return the subset of `farm_ids` that exist (and aren't soft-deleted) in `schema`.

    `schema` is interpolated as a literal — caller MUST have already
    passed it through `sanitize_tenant_schema()`.
    """
    if not farm_ids:
        return set()
    stmt = text(
        f"SELECT id FROM {schema}.farms "  # noqa: S608  -- schema is sanitized
        "WHERE deleted_at IS NULL AND id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=PG_UUID(as_uuid=True), expanding=True))
    rows = (await session.execute(stmt, {"ids": farm_ids})).all()
    return {r.id for r in rows}
