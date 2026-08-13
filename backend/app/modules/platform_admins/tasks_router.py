"""Run an allowlisted background task on demand, for one tenant.

Mounted at ``/api/v1/admin/tasks``.

  GET  /                     — what may be run, and the params each accepts
  POST /{task_name}:run      — dispatch for one tenant, returns a task id
  GET  /runs/{task_id}       — state of a dispatched run

Everything here is gated on ``platform.run_tasks``, held by nothing but
PlatformAdmin's wildcard. It is deliberately not folded into
``platform.manage_tenants``: this reaches into the worker fleet, and an
operator who administers tenant records has no need of it.

Why it exists
-------------
Periodic work is dispatched by name from Beat and nothing can invoke it
directly. An operator whose sweep was missed can only wait for the next cycle,
and the simulation harness cannot make a freshly seeded tenant produce
recommendations at all — its whole time model is backdated data plus an
explicit trigger (``docs/testing/org-simulation-harness.md``).

The safety properties live in :mod:`app.modules.platform_admins.task_registry`:
a literal allowlist rather than a name passthrough, and ``tenant_schema``
supplied here from the resolved tenant so a caller can never aim a task at a
tenant other than the one named in the request body.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import get_audit_service
from app.modules.platform_admins.task_registry import BY_NAME, TRIGGERABLE, TriggerableTask
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, sanitize_tenant_schema
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/tasks", tags=["admin-tasks"])

_CAP = "platform.run_tasks"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Either identifies the tenant. Slug is what an operator has to hand and
    # what the harness carries in its run state; id is what the UI has.
    tenant_slug: str | None = None
    tenant_id: UUID | None = None
    # Extra kwargs for the task, validated against its registry entry.
    params: dict[str, str] = Field(default_factory=dict)


class RunAccepted(BaseModel):
    task_id: str
    task_name: str
    queue: str
    tenant_slug: str
    tenant_schema: str


class RunState(BaseModel):
    task_id: str
    state: str
    ready: bool
    successful: bool | None = None
    result: Any = None
    error: str | None = None


@router.get("")
async def list_triggerable(
    context: RequestContext = Depends(requires_capability(_CAP)),
) -> dict[str, Any]:
    """What may be run, so a caller does not have to read the source.

    Sweeps are absent by design — see the registry docstring.
    """
    del context
    return {"tasks": [t.as_dict() for t in TRIGGERABLE]}


@router.post("/{task_name}:run", status_code=status.HTTP_202_ACCEPTED)
async def run_task(
    task_name: str,
    body: RunRequest,
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> RunAccepted:
    task = BY_NAME.get(task_name)
    if task is None:
        # Names the allowlist rather than 404-ing blankly: the whole point of
        # the endpoint is that the set is small and knowable.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{task_name} is not triggerable; allowed: {sorted(BY_NAME)}",
        )

    tenant = await _resolve_tenant(session, body)
    kwargs = _build_kwargs(task, tenant["schema_name"], body.params)

    from celery import current_app as celery_current_app

    async_result = celery_current_app.send_task(task.name, kwargs=kwargs, queue=task.queue)

    await get_audit_service().record_archive(
        event_type="platform.task_triggered",
        actor_user_id=context.user_id,
        subject_kind="tenant",
        subject_id=tenant["id"],
        details={
            "task_name": task.name,
            "queue": task.queue,
            "tenant_slug": tenant["slug"],
            "task_id": str(async_result.id),
            "params": dict(body.params),
        },
    )

    return RunAccepted(
        task_id=str(async_result.id),
        task_name=task.name,
        queue=task.queue,
        tenant_slug=tenant["slug"],
        tenant_schema=tenant["schema_name"],
    )


@router.get("/runs/{task_id}", response_model=RunState)
async def get_run(
    task_id: str,
    context: RequestContext = Depends(requires_capability(_CAP)),
) -> RunState:
    """State of a dispatched run, so a caller can block instead of sleeping.

    A task id Celery has never seen reports ``PENDING`` rather than 404 —
    that is Celery's model, not an oversight: the result backend has no
    record of a task until a worker picks it up.
    """
    del context
    from celery import current_app as celery_current_app

    result = celery_current_app.AsyncResult(task_id)
    ready = bool(result.ready())
    successful: bool | None = None
    payload: Any = None
    error: str | None = None
    if ready:
        successful = bool(result.successful())
        if successful:
            payload = result.result
        else:
            error = str(result.result)
    return RunState(
        task_id=task_id,
        state=str(result.state),
        ready=ready,
        successful=successful,
        result=payload,
        error=error,
    )


# --- helpers ---------------------------------------------------------------


async def _resolve_tenant(session: AsyncSession, body: RunRequest) -> dict[str, Any]:
    if (body.tenant_slug is None) == (body.tenant_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide exactly one of tenant_slug or tenant_id",
        )
    if body.tenant_slug is not None:
        sql = "SELECT id, slug, schema_name, status FROM public.tenants WHERE slug = :key"
        key: Any = body.tenant_slug
    else:
        sql = "SELECT id, slug, schema_name, status FROM public.tenants WHERE id = :key"
        key = body.tenant_id
    row = (await session.execute(text(sql), {"key": key})).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    if row["status"] != "active":
        # A suspended or pending-delete tenant is out of service; running its
        # sweeps would write rows into a tenant an operator has deliberately
        # stopped.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tenant is {row['status']}, not active",
        )
    tenant = dict(row)
    # Belt and braces: the schema name comes from our own table, but it is
    # about to be interpolated into a task kwarg that becomes a search_path.
    tenant["schema_name"] = sanitize_tenant_schema(str(tenant["schema_name"]))
    return tenant


def _build_kwargs(
    task: TriggerableTask, tenant_schema: str, params: dict[str, str]
) -> dict[str, Any]:
    unknown = sorted(set(params) - task.accepted_params)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{task.name} does not accept {unknown}; "
            f"accepted: {sorted(task.accepted_params)}",
        )
    missing = sorted(set(task.required_params) - set(params))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{task.name} requires {missing}",
        )
    return {"tenant_schema": tenant_schema, **params}
