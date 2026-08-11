"""FastAPI routes for the resources module.

Mounted under /api/v1 by the app factory. Endpoints:

  POST   /farms/{farm_id}/resources            — create worker or equipment
  GET    /farms/{farm_id}/resources            — list (filter by kind / archived)
  GET    /resources/{resource_id}              — fetch one
  PATCH  /resources/{resource_id}              — edit metadata or archive flag
  POST   /activities/{activity_id}/resources/{resource_id}    — attach
  DELETE /activities/{activity_id}/resources/{resource_id}    — detach

RBAC:
  * Reads use ``resource.read``.
  * Writes (create / update / attach / detach) use ``resource.manage``.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plans.errors import ActivityNotFoundError
from app.modules.plans.service import PlansServiceImpl, get_plans_service
from app.modules.resources.errors import ResourceNotFoundError
from app.modules.resources.schemas import (
    ResourceCreateRequest,
    ResourceFarmsRequest,
    ResourceResponse,
    ResourceUpdateRequest,
)
from app.modules.resources.service import (
    ResourcesServiceImpl,
    get_resources_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["resources"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> ResourcesServiceImpl:
    return get_resources_service(tenant_session=tenant_session)


def _plans(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> PlansServiceImpl:
    return get_plans_service(tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


@router.post(
    "/farms/{farm_id}/resources",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a worker or equipment resource on this farm.",
)
async def create_resource(
    farm_id: UUID,
    payload: ResourceCreateRequest,
    context: RequestContext = Depends(
        requires_capability("resource.manage", farm_id_param="farm_id")
    ),
    service: ResourcesServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    return await service.create(
        farm_id=farm_id,
        kind=payload.kind,
        name=payload.name,
        role=payload.role,
        equipment_type=payload.equipment_type,
        phone=payload.phone,
        membership_id=payload.membership_id,
        actor_user_id=context.user_id,
    )


@router.get(
    "/farms/{farm_id}/resources",
    response_model=list[ResourceResponse],
    summary="List workers + equipment on this farm.",
)
async def list_resources(
    farm_id: UUID,
    kind: str | None = Query(default=None, pattern="^(worker|equipment)$"),
    include_archived: bool = Query(default=False),
    context: RequestContext = Depends(
        requires_capability("resource.read", farm_id_param="farm_id")
    ),
    service: ResourcesServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list(farm_id=farm_id, kind=kind, include_archived=include_archived)
    return list(rows)


async def _authorize(
    context: RequestContext,
    service: ResourcesServiceImpl,
    resource: dict[str, Any],
    *,
    capability: str,
    on: Literal["any", "all"],
) -> None:
    """Authorize against the availability set, not the vestigial ``farm_id``.

    A tenant-level resource has no single owning farm, so "can this person
    touch it" splits in two:

    * ``any`` — reading, and being offered in a picker. Holding the capability
      on one farm the resource serves is enough.
    * ``all`` — editing the shared record. Name, phone, role and archived
      state are the same bytes for every farm, so a manager of one farm
      changing them rewrites the others' data. Requires the capability on
      *every* farm in the set.

    A tenant- or platform-level grant satisfies both without enumerating
    anything: it resolves before the farm branch. That is checked first, and
    is why an empty availability set does not lock a tenant admin out of a
    resource nobody can otherwise reach.

    Denials are 404, not 403, matching the rest of this module: whether a
    resource exists on a farm you cannot see is itself not your business.
    """
    if has_capability(context, capability):
        return
    farm_ids = await service.farm_ids_for(resource_id=resource["id"])
    if not farm_ids:
        # Stranded by a farm purge. Only a tenant-level grant reaches it,
        # and that was checked above.
        raise ResourceNotFoundError(resource["id"])
    checks = (has_capability(context, capability, farm_id=f) for f in farm_ids)
    if not (any(checks) if on == "any" else all(checks)):
        raise ResourceNotFoundError(resource["id"])


@router.get(
    "/resources",
    response_model=list[ResourceResponse],
    summary="The tenant-wide roster of workers and equipment.",
)
async def list_tenant_resources(
    kind: str | None = Query(default=None, pattern="^(worker|equipment)$"),
    include_archived: bool = Query(default=False),
    # Tenant-scoped on purpose: this is the whole roster across every farm,
    # which is a different question from "who is on my farm" and is not
    # answerable from a single farm's grant.
    context: RequestContext = Depends(requires_capability("resource.read")),
    service: ResourcesServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list(farm_id=None, kind=kind, include_archived=include_archived)
    by_resource = await service.farm_ids_for_many(resource_ids=[r["id"] for r in rows])
    # Availability travels with each row so the People page can render the
    # farm-by-role matrix without a request per person.
    return [{**r, "farm_ids": list(by_resource.get(r["id"], ()))} for r in rows]


@router.put(
    "/resources/{resource_id}/farms",
    response_model=list[UUID],
    summary="Replace the farms a resource is available on.",
)
async def set_resource_farms(
    resource_id: UUID,
    payload: ResourceFarmsRequest,
    context: RequestContext = Depends(get_current_context),
    service: ResourcesServiceImpl = Depends(_service),
) -> list[UUID]:
    _ensure_tenant(context)
    existing = await service.get(resource_id=resource_id)
    # Both sides of the change have to be authorized. Requiring it on the
    # farms being *added* stops someone lending a worker onto a farm they
    # have no business staffing; requiring it on the current set stops them
    # quietly removing a farm they do not manage from a shared record.
    await _authorize(context, service, existing, capability="resource.manage", on="all")
    for farm_id in payload.farm_ids:
        if not has_capability(context, "resource.manage", farm_id=farm_id):
            raise ResourceNotFoundError(resource_id)
    return list(await service.set_farms(resource_id=resource_id, farm_ids=payload.farm_ids))


@router.get(
    "/resources/{resource_id}",
    response_model=ResourceResponse,
    summary="Fetch a single resource.",
)
async def get_resource(
    resource_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: ResourcesServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    resource = await service.get(resource_id=resource_id)
    await _authorize(context, service, resource, capability="resource.read", on="any")
    return resource


@router.patch(
    "/resources/{resource_id}",
    response_model=ResourceResponse,
    summary="Update resource fields or archive/restore.",
)
async def update_resource(
    resource_id: UUID,
    payload: ResourceUpdateRequest,
    context: RequestContext = Depends(get_current_context),
    service: ResourcesServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    existing = await service.get(resource_id=resource_id)
    # Editing the record itself — name, phone, role, archive — is the strict
    # case: these fields are shared by every farm the resource serves, so a
    # farm-A manager renaming a worker would be rewriting farm B's data.
    await _authorize(context, service, existing, capability="resource.manage", on="all")
    return await service.update(
        resource_id=resource_id,
        changes=payload.model_dump(exclude_unset=True),
        actor_user_id=context.user_id,
    )


@router.post(
    "/activities/{activity_id}/resources/{resource_id}",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a resource to an activity.",
)
async def attach_resource(
    activity_id: UUID,
    resource_id: UUID,
    context: RequestContext = Depends(get_current_context),
    plans: PlansServiceImpl = Depends(_plans),
    service: ResourcesServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    activity = await plans.get_activity(activity_id=activity_id)
    if activity is None:
        raise ActivityNotFoundError(activity_id)
    if not has_capability(context, "resource.manage", farm_id=activity["farm_id"]):
        raise ResourceNotFoundError(resource_id)
    return await service.attach(
        activity_id=activity_id,
        resource_id=resource_id,
        actor_user_id=context.user_id,
        # The activity's farm is the one the resource has to serve.
        farm_id=activity["farm_id"],
    )


@router.delete(
    "/activities/{activity_id}/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a resource from an activity.",
)
async def detach_resource(
    activity_id: UUID,
    resource_id: UUID,
    context: RequestContext = Depends(get_current_context),
    plans: PlansServiceImpl = Depends(_plans),
    service: ResourcesServiceImpl = Depends(_service),
) -> Response:
    _ensure_tenant(context)
    activity = await plans.get_activity(activity_id=activity_id)
    if activity is None:
        raise ActivityNotFoundError(activity_id)
    if not has_capability(context, "resource.manage", farm_id=activity["farm_id"]):
        raise ResourceNotFoundError(resource_id)
    await service.detach(activity_id=activity_id, resource_id=resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
