"""Platform defaults admin endpoints.

Mounted at /api/v1/admin/defaults. PlatformAdmin only (capability:
`platform.manage_defaults` for writes; `platform.read` is enough for
reads since defaults are non-sensitive).

  GET   /api/v1/admin/defaults                 â€” list all keys
  PUT   /api/v1/admin/defaults/{key}           â€” update one value
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import get_audit_service
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability
from app.shared.settings import (
    SettingNotFoundError,
    SettingsRepository,
    describe,
    invalidate_defaults_cache,
    validate_value,
)

router = APIRouter(prefix="/api/v1/admin/defaults", tags=["admin-defaults"])


class PlatformDefaultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    value_schema: Literal["string", "number", "boolean", "object", "array"]
    description: str | None
    category: str
    updated_at: datetime
    updated_by: object | None  # UUID | None
    #: Range / choices the value must satisfy, or None when unconstrained.
    #: The editor mirrors these client-side so bad values never round-trip.
    constraint: dict[str, Any] | None = None


class UpdateDefaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any = Field(description="Pre-validated against the row's value_schema.")


@router.get("", response_model=list[PlatformDefaultResponse])
async def list_defaults(
    context: RequestContext = Depends(requires_capability("platform.read")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    repo = SettingsRepository(public_session=public_session)
    return [_with_constraint(row) for row in await repo.list_defaults()]


def _with_constraint(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "constraint": describe(row["key"])}


@router.put("/{key}", response_model=PlatformDefaultResponse)
async def update_default(
    key: str,
    payload: UpdateDefaultRequest,
    context: RequestContext = Depends(requires_capability("platform.manage_defaults")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    audit = get_audit_service()
    repo = SettingsRepository(public_session=public_session)
    existing = await repo.get_default(key=key)
    if existing is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=404,
            title="Platform default not found",
            detail=f"No platform default with key {key!r}.",
            type_="https://agripulse.cloud/problems/platform-default-not-found",
        )
    # Raises SettingValueError -> 400 via the global handler in core.errors.
    validate_value(key=key, value=payload.value, value_schema=existing["value_schema"])
    updated = await repo.update_default_value(
        key=key,
        value_json=json.dumps(payload.value),
        actor_user_id=context.user_id,
    )
    if not updated:
        raise SettingNotFoundError(key)

    # Invalidate the in-process cache so the next resolver read sees
    # the new value without waiting the 60s TTL.
    invalidate_defaults_cache()

    await audit.record_archive(
        event_type="platform.platform_default_updated",
        actor_user_id=context.user_id,
        subject_kind="platform_default",
        subject_id=None,
        details={
            "key": key,
            "old_value": existing["value"],
            "new_value": payload.value,
        },
    )
    after = await repo.get_default(key=key)
    assert after is not None
    return _with_constraint(after)
