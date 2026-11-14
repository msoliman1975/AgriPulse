"""Crop reference values routes (D18, D23).

  GET    /api/v1/reference-values/keys                  the keys, units and bounds
  GET    /api/v1/reference-values/{crop_path}           own rows + resolved (inherited)
  PUT    /api/v1/admin/reference-values/{crop_path}/{key}    set   platform.manage_crops
  DELETE /api/v1/admin/reference-values/{crop_path}/{key}    clear platform.manage_crops

Reads are open to every signed-in user: they are published agronomy, and
growers see them beside their blocks. Writes are audited.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.audit import get_audit_service
from app.modules.reference_values.keys import BY_KEY, KEYS, plants_per_ha, resolve
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(tags=["reference-values"])


class ReferenceKeyResponse(BaseModel):
    key: str
    group: str
    unit: str
    lower: float
    upper: float


class ReferenceRow(BaseModel):
    crop_path: str
    key: str
    value: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    note: str | None = None


class ResolvedValue(BaseModel):
    value: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    note: str | None = None
    from_path: str


class ReferenceView(BaseModel):
    crop_path: str
    own: list[ReferenceRow]
    resolved: dict[str, ResolvedValue]
    plants_per_ha: float | None = None


class ReferenceValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _shape(self) -> ReferenceValueRequest:
        if self.value is None and self.value_min is None and self.value_max is None:
            raise ValueError("give a value, a range, or both")
        if (
            self.value_min is not None
            and self.value_max is not None
            and self.value_min > self.value_max
        ):
            raise ValueError("value_min is above value_max")
        return self


def _problem(code: int, title: str, detail: str, slug: str) -> APIError:
    return APIError(
        status_code=code,
        title=title,
        detail=detail,
        type_=f"https://agripulse.cloud/problems/{slug}",
    )


async def _rows_for(session: AsyncSession, crop_path: str) -> list[dict[str, Any]]:
    segments = [s for s in crop_path.split(".") if s]
    chain = [".".join(segments[: i + 1]) for i in range(len(segments))]
    rows = await session.execute(
        text(
            "SELECT crop_path, key, value, value_min, value_max, note "
            "FROM public.crop_reference_values WHERE crop_path = ANY(:chain) "
            "ORDER BY crop_path, key"
        ),
        {"chain": chain},
    )
    return [dict(r._mapping) for r in rows]


async def _crop_path_exists(session: AsyncSession, crop_path: str) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1 FROM public.crops WHERE code = :p
                UNION ALL SELECT 1 FROM public.crop_varieties WHERE path = :p
                UNION ALL SELECT 1 FROM public.crop_variety_strains WHERE path = :p
                LIMIT 1
                """
            ),
            {"p": crop_path},
        )
    ).first()
    return row is not None


async def view_for(session: AsyncSession, crop_path: str) -> dict[str, Any]:
    rows = await _rows_for(session, crop_path)
    resolved = resolve(crop_path, rows)
    return {
        "crop_path": crop_path,
        "own": [r for r in rows if r["crop_path"] == crop_path],
        "resolved": resolved,
        "plants_per_ha": plants_per_ha(resolved),
    }


@router.get("/api/v1/reference-values/keys", response_model=list[ReferenceKeyResponse])
async def list_keys(
    context: RequestContext = Depends(get_current_context),
) -> list[dict[str, Any]]:
    del context
    return [k.as_dict() for k in KEYS]


@router.get("/api/v1/reference-values/{crop_path}", response_model=ReferenceView)
async def get_reference_values(
    crop_path: str,
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    del context
    return await view_for(session, crop_path)


@router.put("/api/v1/admin/reference-values/{crop_path}/{key}", response_model=ReferenceView)
async def put_reference_value(
    crop_path: str,
    key: str,
    payload: ReferenceValueRequest,
    context: RequestContext = Depends(requires_capability("platform.manage_crops")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    spec = BY_KEY.get(key)
    if spec is None:
        raise _problem(
            422,
            "Unknown reference key",
            f"{key!r} is not a reference key.",
            "reference-key-unknown",
        )
    if not await _crop_path_exists(session, crop_path):
        raise _problem(
            404,
            "Unknown crop path",
            f"No crop, variety or strain has path {crop_path!r}.",
            "crop-path-unknown",
        )
    for number in (payload.value, payload.value_min, payload.value_max):
        if number is not None and not (spec.lower <= float(number) <= spec.upper):
            raise _problem(
                422,
                "Reference value out of range",
                f"{key} takes {spec.lower} to {spec.upper} {spec.unit}.",
                "reference-value-out-of-range",
            )
    await session.execute(
        text(
            """
            INSERT INTO public.crop_reference_values
                   (crop_path, key, value, value_min, value_max, note, updated_by)
            VALUES (:p, :k, :v, :lo, :hi, :note, :actor)
            ON CONFLICT (crop_path, key) DO UPDATE
               SET value = EXCLUDED.value, value_min = EXCLUDED.value_min,
                   value_max = EXCLUDED.value_max, note = EXCLUDED.note,
                   updated_by = EXCLUDED.updated_by
            """
        ),
        {
            "p": crop_path,
            "k": key,
            "v": payload.value,
            "lo": payload.value_min,
            "hi": payload.value_max,
            "note": payload.note,
            "actor": context.user_id,
        },
    )
    await get_audit_service().record_archive(
        event_type="platform.reference_value_set",
        actor_user_id=context.user_id,
        subject_kind="crop_reference_value",
        subject_id=None,
        details={"crop_path": crop_path, "key": key, **payload.model_dump(mode="json")},
    )
    return await view_for(session, crop_path)


@router.delete(
    "/api/v1/admin/reference-values/{crop_path}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_reference_value(
    crop_path: str,
    key: str,
    context: RequestContext = Depends(requires_capability("platform.manage_crops")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> Response:
    removed = (
        await session.execute(
            text(
                "DELETE FROM public.crop_reference_values "
                "WHERE crop_path = :p AND key = :k RETURNING value, value_min, value_max"
            ),
            {"p": crop_path, "k": key},
        )
    ).first()
    if removed is None:
        raise _problem(
            404, "Reference value not set", f"{crop_path} sets no {key}.", "reference-value-not-set"
        )
    await get_audit_service().record_archive(
        event_type="platform.reference_value_cleared",
        actor_user_id=context.user_id,
        subject_kind="crop_reference_value",
        subject_id=None,
        details={"crop_path": crop_path, "key": key, "was": [str(x) for x in removed]},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
