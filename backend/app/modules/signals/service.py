"""Signals service — public Protocol + concrete impl + factory.

Three responsibilities:

  * **Definition catalog**: per-tenant CRUD on what kinds of signals
    exist. Codes are the stable identifier ConditionContext predicates
    look up by.
  * **Assignments**: scope a definition to a farm, a block, or
    tenant-wide. The latest-observation snapshot loader joins through
    these so a rule "applies" to a block iff there's an active
    assignment that covers it.
  * **Observations**: validated against the definition's `value_kind`
    and bounds before inserting. Geopoint values are stored as PostGIS
    `geometry(Point,4326)`; numeric / categorical / event / boolean
    are typed columns. Photo upload is a two-step presigned-PUT flow
    (`init_attachment_upload` → client uploads → observation INSERT
    references the resulting key).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.signals.errors import (
    AttachmentMissingError,
    AttachmentNotPermittedError,
    InvalidSignalValueError,
    SignalAssignmentNotFoundError,
    SignalDefinitionNotFoundError,
)
from app.modules.signals.repository import SignalsRepository
from app.modules.signals.schemas import GeopointModel
from app.shared.db.ids import uuid7
from app.shared.storage.client import (
    PresignedUpload,
    StorageClient,
    StorageObjectMissingError,
    get_storage_client,
)


class SignalsService(Protocol):
    async def list_definitions(
        self, *, include_inactive: bool = False
    ) -> tuple[dict[str, Any], ...]: ...

    async def get_definition(self, *, definition_id: UUID) -> dict[str, Any]: ...

    async def create_definition(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        value_kind: str,
        unit: str | None,
        categorical_values: list[str] | None,
        value_min: Decimal | None,
        value_max: Decimal | None,
        attachment_allowed: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def update_definition(
        self,
        *,
        definition_id: UUID,
        updates: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def delete_definition(
        self,
        *,
        definition_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

    async def list_assignments(self, *, definition_id: UUID) -> tuple[dict[str, Any], ...]: ...

    async def create_assignment(
        self,
        *,
        definition_id: UUID,
        farm_id: UUID | None,
        block_id: UUID | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def delete_assignment(
        self,
        *,
        assignment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

    async def init_attachment_upload(
        self,
        *,
        signal_definition_id: UUID,
        farm_id: UUID,
        content_type: str,
        content_length: int,
        filename: str,
        tenant_id: UUID,
    ) -> dict[str, Any]: ...

    async def create_observation(
        self,
        *,
        definition_id: UUID,
        time: datetime | None,
        farm_id: UUID,
        block_id: UUID | None,
        value_numeric: Decimal | None,
        value_categorical: str | None,
        value_event: str | None,
        value_boolean: bool | None,
        value_geopoint: GeopointModel | None,
        attachment_s3_key: str | None,
        notes: str | None,
        recorded_by: UUID,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def list_observations(
        self,
        *,
        signal_definition_id: UUID | None = None,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]: ...


class SignalsServiceImpl:
    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        audit_service: AuditService | None = None,
        storage: StorageClient | None = None,
    ) -> None:
        self._tenant = tenant_session
        self._repo = SignalsRepository(tenant_session)
        self._audit = audit_service or get_audit_service()
        self._storage = storage or get_storage_client()
        self._log = get_logger(__name__)

    # ---- Definitions --------------------------------------------------

    async def list_definitions(
        self, *, include_inactive: bool = False
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_definitions(include_inactive=include_inactive)

    async def get_definition(self, *, definition_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_definition(definition_id=definition_id)
        if row is None:
            raise SignalDefinitionNotFoundError(definition_id)
        return row

    async def create_definition(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        value_kind: str,
        unit: str | None,
        categorical_values: list[str] | None,
        value_min: Decimal | None,
        value_max: Decimal | None,
        attachment_allowed: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        if value_kind == "categorical" and not categorical_values:
            raise InvalidSignalValueError(
                detail="Categorical signals require non-empty categorical_values."
            )
        if value_kind != "categorical" and categorical_values:
            raise InvalidSignalValueError(
                detail="categorical_values is only valid for value_kind='categorical'."
            )
        if value_min is not None and value_max is not None and value_min > value_max:
            raise InvalidSignalValueError(detail="value_min must be ≤ value_max.")

        definition_id = uuid7()
        row = await self._repo.insert_definition(
            definition_id=definition_id,
            code=code,
            name=name,
            description=description,
            value_kind=value_kind,
            unit=unit,
            categorical_values=categorical_values,
            value_min=value_min,
            value_max=value_max,
            attachment_allowed=attachment_allowed,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.definition_created",
            actor_user_id=actor_user_id,
            subject_kind="signal_definition",
            subject_id=definition_id,
            farm_id=None,
            details={"code": code, "value_kind": value_kind},
        )
        return row

    async def update_definition(
        self,
        *,
        definition_id: UUID,
        updates: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        existing = await self._repo.get_definition(definition_id=definition_id)
        if existing is None:
            raise SignalDefinitionNotFoundError(definition_id)
        if (
            updates.get("value_min") is not None
            and updates.get("value_max") is not None
            and updates["value_min"] > updates["value_max"]
        ):
            raise InvalidSignalValueError(detail="value_min must be ≤ value_max.")
        out = await self._repo.update_definition(
            definition_id=definition_id, updates=updates, actor_user_id=actor_user_id
        )
        if out is None:
            raise SignalDefinitionNotFoundError(definition_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.definition_updated",
            actor_user_id=actor_user_id,
            subject_kind="signal_definition",
            subject_id=definition_id,
            farm_id=None,
            details={"code": existing["code"], "fields": sorted(updates.keys())},
        )
        return out

    async def delete_definition(
        self,
        *,
        definition_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        existing = await self._repo.get_definition(definition_id=definition_id)
        if existing is None:
            raise SignalDefinitionNotFoundError(definition_id)
        deleted = await self._repo.soft_delete_definition(
            definition_id=definition_id, actor_user_id=actor_user_id
        )
        if not deleted:
            return
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.definition_deleted",
            actor_user_id=actor_user_id,
            subject_kind="signal_definition",
            subject_id=definition_id,
            farm_id=None,
            details={"code": existing["code"]},
        )

    # ---- Assignments --------------------------------------------------

    async def list_assignments(self, *, definition_id: UUID) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_assignments(definition_id=definition_id)

    async def create_assignment(
        self,
        *,
        definition_id: UUID,
        farm_id: UUID | None,
        block_id: UUID | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        if (await self._repo.get_definition(definition_id=definition_id)) is None:
            raise SignalDefinitionNotFoundError(definition_id)
        # `(farm_id IS NULL AND block_id IS NULL)` ⇒ tenant-wide is
        # explicitly allowed; the data_model § 9.3 constraint says so.
        assignment_id = uuid7()
        row = await self._repo.insert_assignment(
            assignment_id=assignment_id,
            definition_id=definition_id,
            farm_id=farm_id,
            block_id=block_id,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.assignment_created",
            actor_user_id=actor_user_id,
            subject_kind="signal_assignment",
            subject_id=assignment_id,
            farm_id=farm_id,
            details={
                "signal_definition_id": str(definition_id),
                "block_id": str(block_id) if block_id else None,
            },
        )
        return row

    async def delete_assignment(
        self,
        *,
        assignment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        deleted = await self._repo.soft_delete_assignment(
            assignment_id=assignment_id, actor_user_id=actor_user_id
        )
        if not deleted:
            raise SignalAssignmentNotFoundError(assignment_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.assignment_deleted",
            actor_user_id=actor_user_id,
            subject_kind="signal_assignment",
            subject_id=assignment_id,
            farm_id=None,
            details={},
        )

    # ---- Attachment upload --------------------------------------------

    def _attachment_key(
        self,
        *,
        tenant_id: UUID,
        farm_id: UUID,
        definition_id: UUID,
        attachment_id: UUID,
        filename: str,
    ) -> str:
        # Layout mirrors `app.shared.storage.keys.build_attachment_key`
        # but slimmer — observations don't carry a separate `attachments`
        # row, just a key on the observation itself.
        from app.shared.storage.keys import _SAFE_FILENAME_RE  # internal helper

        safe = _SAFE_FILENAME_RE.sub("_", filename).strip("._-") or "file"
        return (
            f"tenants/{tenant_id}/signals/{definition_id}/farms/{farm_id}/"
            f"{attachment_id}/{safe}"
        )

    async def init_attachment_upload(
        self,
        *,
        signal_definition_id: UUID,
        farm_id: UUID,
        content_type: str,
        content_length: int,
        filename: str,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        defn = await self._repo.get_definition(definition_id=signal_definition_id)
        if defn is None:
            raise SignalDefinitionNotFoundError(signal_definition_id)
        if not defn["attachment_allowed"]:
            raise AttachmentNotPermittedError(code=defn["code"])
        attachment_id = uuid4()
        key = self._attachment_key(
            tenant_id=tenant_id,
            farm_id=farm_id,
            definition_id=signal_definition_id,
            attachment_id=attachment_id,
            filename=filename,
        )
        upload: PresignedUpload = self._storage.presign_upload(
            key=key, content_type=content_type, content_length=content_length
        )
        return {
            "attachment_s3_key": key,
            "upload_url": upload.url,
            "upload_headers": upload.headers,
            "expires_at": upload.expires_at,
        }

    # ---- Observations -------------------------------------------------

    def _validate_value(self, *, defn: dict[str, Any], request_values: dict[str, Any]) -> None:
        kind = defn["value_kind"]
        # Exactly one value column must be set, matching the row-level CHECK.
        provided = [k for k, v in request_values.items() if v is not None]
        if len(provided) != 1:
            raise InvalidSignalValueError(
                detail=(
                    "Exactly one of value_numeric / value_categorical / value_event / "
                    "value_boolean / value_geopoint must be set."
                )
            )
        column_for_kind = {
            "numeric": "value_numeric",
            "categorical": "value_categorical",
            "event": "value_event",
            "boolean": "value_boolean",
            "geopoint": "value_geopoint",
        }[kind]
        if provided[0] != column_for_kind:
            raise InvalidSignalValueError(
                detail=(
                    f"Definition expects {column_for_kind!r} for value_kind={kind!r}; "
                    f"got {provided[0]!r}."
                )
            )
        if kind == "numeric":
            value = request_values["value_numeric"]
            if defn["value_min"] is not None and value < defn["value_min"]:
                raise InvalidSignalValueError(
                    detail=f"value_numeric below value_min ({defn['value_min']})."
                )
            if defn["value_max"] is not None and value > defn["value_max"]:
                raise InvalidSignalValueError(
                    detail=f"value_numeric above value_max ({defn['value_max']})."
                )
        elif kind == "categorical":
            allowed = defn["categorical_values"] or []
            if request_values["value_categorical"] not in allowed:
                raise InvalidSignalValueError(detail=f"value_categorical must be one of {allowed}.")

    async def create_observation(
        self,
        *,
        definition_id: UUID,
        time: datetime | None,
        farm_id: UUID,
        block_id: UUID | None,
        value_numeric: Decimal | None,
        value_categorical: str | None,
        value_event: str | None,
        value_boolean: bool | None,
        value_geopoint: GeopointModel | None,
        attachment_s3_key: str | None,
        notes: str | None,
        recorded_by: UUID,
        tenant_schema: str,
    ) -> dict[str, Any]:
        defn = await self._repo.get_definition(definition_id=definition_id)
        if defn is None:
            raise SignalDefinitionNotFoundError(definition_id)
        self._validate_value(
            defn=defn,
            request_values={
                "value_numeric": value_numeric,
                "value_categorical": value_categorical,
                "value_event": value_event,
                "value_boolean": value_boolean,
                "value_geopoint": value_geopoint,
            },
        )
        if attachment_s3_key is not None:
            if not defn["attachment_allowed"]:
                raise AttachmentNotPermittedError(code=defn["code"])
            try:
                self._storage.head_object(key=attachment_s3_key)
            except StorageObjectMissingError as exc:
                raise AttachmentMissingError(key=attachment_s3_key) from exc

        observation_id = uuid7()
        observation_time = time or datetime.now(UTC)
        wkt = (
            f"POINT({value_geopoint.longitude} {value_geopoint.latitude})"
            if value_geopoint is not None
            else None
        )
        await self._repo.insert_observation(
            observation_id=observation_id,
            time=observation_time,
            signal_definition_id=definition_id,
            farm_id=farm_id,
            block_id=block_id,
            value_numeric=value_numeric,
            value_categorical=value_categorical,
            value_event=value_event,
            value_boolean=value_boolean,
            value_geopoint_wkt=wkt,
            attachment_s3_key=attachment_s3_key,
            notes=notes,
            recorded_by=recorded_by,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.observation_recorded",
            actor_user_id=recorded_by,
            subject_kind="signal_observation",
            subject_id=observation_id,
            farm_id=farm_id,
            details={
                "signal_definition_id": str(definition_id),
                "code": defn["code"],
                "block_id": str(block_id) if block_id else None,
                "has_attachment": attachment_s3_key is not None,
            },
        )
        # Re-read so the response carries the joined `signal_code` + GeoJSON.
        rows = await self._repo.list_observations(
            signal_definition_id=definition_id, farm_id=farm_id, limit=1
        )
        return _enrich_observation(rows[0], storage=self._storage) if rows else {}

    async def list_observations(
        self,
        *,
        signal_definition_id: UUID | None = None,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        rows = await self._repo.list_observations(
            signal_definition_id=signal_definition_id,
            farm_id=farm_id,
            block_id=block_id,
            since=since,
            until=until,
            limit=limit,
        )
        return tuple(_enrich_observation(r, storage=self._storage) for r in rows)


def _enrich_observation(row: dict[str, Any], *, storage: StorageClient) -> dict[str, Any]:
    """Map repository row → API shape: rename geopoint, attach a
    short-lived presigned download URL when an attachment is set."""
    out = dict(row)
    geo = out.pop("value_geopoint_geojson", None)
    if isinstance(geo, dict) and geo.get("type") == "Point":
        coords = geo.get("coordinates") or []
        if len(coords) == 2:
            out["value_geopoint"] = {"longitude": coords[0], "latitude": coords[1]}
        else:
            out["value_geopoint"] = None
    else:
        out["value_geopoint"] = None
    key = out.get("attachment_s3_key")
    if key:
        out["attachment_download_url"] = storage.presign_download(key=key).url
    else:
        out["attachment_download_url"] = None
    return out


def get_signals_service(*, tenant_session: AsyncSession) -> SignalsServiceImpl:
    return SignalsServiceImpl(tenant_session=tenant_session)


def _check(impl: SignalsServiceImpl) -> SignalsService:
    return impl
