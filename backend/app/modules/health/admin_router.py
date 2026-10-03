"""Platform-admin endpoints for the block health definition.

Mounted at /api/v1/admin/health-definitions. Two of the four tiers are
platform data and are edited here (public migration 0095):

  GET  /platform               the platform default, plus the platform's
                               rollup rule from `public.platform_defaults`
  PUT  /platform               replace the platform default (all 7 keys)
  GET  /crops                  every crop row
  GET  /crops/{crop_path}      one path: its own row and what it inherits
  PUT  /crops/{crop_path}      replace that path's row; `{}` removes it

`platform.read` is enough to read. Writing the platform default needs
`platform.manage_defaults`, the capability the other platform defaults use;
writing a crop row needs `platform.manage_crops`, the catalogue's.

The platform's rollup rule (`health.cell_rollup`, `health.cell_share_pct`)
is NOT written here. It is a `platform_defaults` key that a tenant can
override, and it keeps its one writer: PUT /api/v1/admin/defaults/{key}.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.audit import get_audit_service
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.health_definition import HealthDefinitionError, parse_definition
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/health-definitions", tags=["admin-health-definitions"])

_TYPE_BASE = "https://agripulse.cloud/problems"

# The keys the platform row holds. All of them, every time: the platform is
# the tier nothing sits under, so a key it leaves out would fall back to a
# value that exists only in code. `cell_rollup` is absent on purpose; see
# the module docstring.
PLATFORM_KEYS: frozenset[str] = frozenset(
    {
        "severity_map",
        "counted_statuses",
        "snoozed_as",
        "cell_critical_share",
        "recommendation_floor",
        "stale_after_hours",
        "no_tree_coverage",
    }
)

# A crop row may name any of the platform's keys, and also the rollup rule:
# a crop whose cells behave differently can say so.
CROP_KEYS: frozenset[str] = PLATFORM_KEYS | {"cell_rollup"}

_ROLLUP_KEY = "health.cell_rollup"
_SHARE_KEY = "health.cell_share_pct"


# ---- Errors -----------------------------------------------------------------


class InvalidHealthBodyError(APIError):
    """A body `parse_definition` refuses, or a key this tier does not hold."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            status_code=422,
            title="Invalid health definition",
            detail=detail,
            type_=f"{_TYPE_BASE}/invalid-health-definition",
        )


class UnknownCropPathError(APIError):
    """A path no crop, variety or strain has. A row for it would reach no block."""

    def __init__(self, *, crop_path: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Crop path not found",
            detail=f"No crop, variety or strain has the path {crop_path!r}.",
            type_=f"{_TYPE_BASE}/crop-path-not-found",
            extras={"crop_path": crop_path},
        )


class PlatformRowMissingError(APIError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Platform health definition missing",
            detail="public.health_definition_platform has no row. Run public migration 0095.",
            type_=f"{_TYPE_BASE}/health-definition-platform-missing",
        )


# ---- Schemas ----------------------------------------------------------------


class DefinitionRequest(BaseModel):
    """`definition` stays a plain dict. Three keys take null as a real value,
    so "sent as null" and "not sent" must survive to the validator."""

    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    notes: str | None = Field(default=None, max_length=2000)


class PlatformRollup(BaseModel):
    cell_rollup: str
    cell_share_pct: int | None


class PlatformDefinitionResponse(BaseModel):
    definition: dict[str, Any]
    version: int
    notes: str | None
    updated_at: datetime
    updated_by: Any | None
    rollup: PlatformRollup


class CropDefinitionResponse(BaseModel):
    crop_path: str
    definition: dict[str, Any]
    version: int
    notes: str | None
    updated_at: datetime
    updated_by: Any | None


class InheritedValue(BaseModel):
    value: Any
    #: "platform", or the crop path whose row set it.
    source: str


class CropPathView(BaseModel):
    """One path as the catalogue's Health tab shows it."""

    crop_path: str
    own: CropDefinitionResponse | None
    #: Every key, as this path would read it WITHOUT its own row.
    inherited: dict[str, InheritedValue]


# ---- Validation -------------------------------------------------------------


def check_platform_body(body: dict[str, Any]) -> None:
    """Every platform key, and nothing else, and a body the resolver accepts."""
    unknown = sorted(set(body) - PLATFORM_KEYS)
    if "cell_rollup" in unknown:
        raise InvalidHealthBodyError(
            detail="cell_rollup is set by the platform default health.cell_rollup, not here."
        )
    if unknown:
        raise InvalidHealthBodyError(
            detail=f"Unknown key(s) {unknown}; allowed keys are {sorted(PLATFORM_KEYS)}."
        )
    missing = sorted(PLATFORM_KEYS - set(body))
    if missing:
        raise InvalidHealthBodyError(
            detail=f"The platform default must name every key; missing {missing}."
        )
    _parse(body)


def check_crop_body(body: dict[str, Any]) -> None:
    """A partial body: any subset of the crop keys, and one the resolver accepts."""
    unknown = sorted(set(body) - CROP_KEYS)
    if unknown:
        raise InvalidHealthBodyError(
            detail=f"Unknown key(s) {unknown}; allowed keys are {sorted(CROP_KEYS)}."
        )
    _parse(body)


def _parse(body: dict[str, Any]) -> None:
    # `parse_definition` is the resolver's own gate, so a body that passes
    # here cannot fail when a block is read.
    try:
        parse_definition(body)
    except HealthDefinitionError as exc:
        raise InvalidHealthBodyError(detail=str(exc)) from exc


def inherited_for(
    crop_path: str,
    *,
    platform: dict[str, Any],
    crops: dict[str, dict[str, Any]],
) -> dict[str, InheritedValue]:
    """What ``crop_path`` reads from the tiers above it, key by key.

    The same walk `service.CropHealthDefinitions` does: platform first, then
    each shallower path, split on "." and compared whole. The path's own row
    is left out, because this is what it would read without one.
    """
    out = {k: InheritedValue(value=v, source="platform") for k, v in platform.items()}
    segments = crop_path.split(".")
    for depth in range(1, len(segments)):
        ancestor = ".".join(segments[:depth])
        for key, value in crops.get(ancestor, {}).items():
            out[key] = InheritedValue(value=value, source=ancestor)
    return out


# ---- Reads ------------------------------------------------------------------


async def _platform_row(session: AsyncSession) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT definition, version, notes, updated_at, updated_by
                    FROM public.health_definition_platform
                    WHERE id = 1
                    """
                )
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise PlatformRowMissingError()
    return dict(row)


async def _platform_rollup(session: AsyncSession) -> PlatformRollup:
    rows = (
        await session.execute(
            text("SELECT key, value FROM public.platform_defaults WHERE key IN (:r, :s)"),
            {"r": _ROLLUP_KEY, "s": _SHARE_KEY},
        )
    ).all()
    by_key = {str(r.key): r.value for r in rows}
    share = by_key.get(_SHARE_KEY)
    return PlatformRollup(
        cell_rollup=str(by_key.get(_ROLLUP_KEY, "worst")),
        cell_share_pct=int(share) if share is not None else None,
    )


async def _crop_rows(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT crop_path, definition, version, notes, updated_at, updated_by
                    FROM public.crop_health_definitions
                    ORDER BY crop_path
                    """
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _crop_path_exists(session: AsyncSession, crop_path: str) -> bool:
    """Three tables, because the depth decides which one holds the path.

    This is the check a foreign key would do, and cannot: there is no single
    column to point at. Without it a typed-wrong path saves a row that
    reaches no block.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT 1 FROM public.crops WHERE code = :p
                UNION ALL
                SELECT 1 FROM public.crop_varieties WHERE path = :p
                UNION ALL
                SELECT 1 FROM public.crop_variety_strains WHERE path = :p
                LIMIT 1
                """
            ),
            {"p": crop_path},
        )
    ).first()
    return row is not None


# ---- Routes -----------------------------------------------------------------


@router.get("/platform", response_model=PlatformDefinitionResponse)
async def get_platform_definition(
    context: RequestContext = Depends(requires_capability("platform.read")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    del context
    row = await _platform_row(session)
    return {**row, "rollup": await _platform_rollup(session)}


@router.put("/platform", response_model=PlatformDefinitionResponse)
async def put_platform_definition(
    payload: DefinitionRequest,
    context: RequestContext = Depends(requires_capability("platform.manage_defaults")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    check_platform_body(payload.definition)
    before = await _platform_row(session)
    await session.execute(
        text(
            """
            UPDATE public.health_definition_platform
               SET definition = CAST(:definition AS jsonb),
                   notes      = :notes,
                   version    = version + 1,
                   updated_at = public.app_now(),
                   updated_by = :actor
             WHERE id = 1
            """
        ),
        {
            "definition": json.dumps(payload.definition),
            "notes": payload.notes,
            "actor": context.user_id,
        },
    )
    await get_audit_service().record_archive(
        event_type="platform.health_definition_updated",
        actor_user_id=context.user_id,
        subject_kind="health_definition_platform",
        subject_id=None,
        details={"old": before["definition"], "new": payload.definition},
    )
    row = await _platform_row(session)
    return {**row, "rollup": await _platform_rollup(session)}


@router.get("/crops", response_model=list[CropDefinitionResponse])
async def list_crop_definitions(
    context: RequestContext = Depends(requires_capability("platform.read")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    return await _crop_rows(session)


@router.get("/crops/{crop_path}", response_model=CropPathView)
async def get_crop_definition(
    crop_path: str,
    context: RequestContext = Depends(requires_capability("platform.read")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> CropPathView:
    del context
    return await _crop_view(session, crop_path)


@router.put("/crops/{crop_path}", response_model=CropPathView)
async def put_crop_definition(
    crop_path: str,
    payload: DefinitionRequest,
    context: RequestContext = Depends(requires_capability("platform.manage_crops")),
    session: AsyncSession = Depends(get_admin_db_session),
) -> CropPathView:
    if not await _crop_path_exists(session, crop_path):
        raise UnknownCropPathError(crop_path=crop_path)
    check_crop_body(payload.definition)

    before = {r["crop_path"]: r for r in await _crop_rows(session)}.get(crop_path)
    if not payload.definition:
        # An empty body means "inherit everything". Deleting the row says
        # that; keeping an empty one would show a version for a row that
        # decides nothing.
        await session.execute(
            text("DELETE FROM public.crop_health_definitions WHERE crop_path = :p"),
            {"p": crop_path},
        )
    else:
        await session.execute(
            text(
                """
                INSERT INTO public.crop_health_definitions
                       (crop_path, definition, version, notes, updated_by)
                VALUES (:p, CAST(:definition AS jsonb), 1, :notes, :actor)
                ON CONFLICT (crop_path) DO UPDATE
                   SET definition    = EXCLUDED.definition,
                       notes         = EXCLUDED.notes,
                       version       = public.crop_health_definitions.version + 1,
                       updated_by    = EXCLUDED.updated_by,
                       source_path   = NULL,
                       compiled_hash = NULL,
                       updated_at    = public.app_now()
                """
            ),
            {
                "p": crop_path,
                "definition": json.dumps(payload.definition),
                "notes": payload.notes,
                "actor": context.user_id,
            },
        )
    await get_audit_service().record_archive(
        event_type="platform.crop_health_definition_updated",
        actor_user_id=context.user_id,
        subject_kind="crop_health_definition",
        subject_id=None,
        details={
            "crop_path": crop_path,
            "old": before["definition"] if before else None,
            "new": payload.definition or None,
        },
    )
    return await _crop_view(session, crop_path)


async def _crop_view(session: AsyncSession, crop_path: str) -> CropPathView:
    platform = (await _platform_row(session))["definition"]
    rollup = await _platform_rollup(session)
    platform = {**platform, "cell_rollup": rollup.cell_rollup}
    if rollup.cell_rollup == "share" and rollup.cell_share_pct is not None:
        # The resolver reads the share percent as the critical-cell share
        # under this rule (`service.platform_rollup`), so the view does too.
        platform["cell_critical_share"] = rollup.cell_share_pct / 100
    rows = await _crop_rows(session)
    by_path = {r["crop_path"]: dict(r["definition"] or {}) for r in rows}
    own = next((r for r in rows if r["crop_path"] == crop_path), None)
    return CropPathView(
        crop_path=crop_path,
        own=CropDefinitionResponse(**own) if own else None,
        inherited=inherited_for(crop_path, platform=platform, crops=by_path),
    )
