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
from app.modules.signals.csv_import import (
    MAX_BYTES as CSV_MAX_BYTES,
)
from app.modules.signals.csv_import import (
    CsvRowError,
    parse_csv,
)
from app.modules.signals.errors import (
    AttachmentMissingError,
    AttachmentNotPermittedError,
    CsvImportFailedError,
    CsvImportTooLargeError,
    InvalidSignalValueError,
    SignalAssignmentNotFoundError,
    SignalDefinitionNotFoundError,
    SignalObservationNotFoundError,
    SignalTemplateMembersInvalidError,
    SignalTemplateNotFoundError,
)
from app.modules.signals.repository import SignalsRepository
from app.modules.signals.schemas import (
    GeopointModel,
    SignalTemplateDefinitionMember,
    SignalTemplateObservationMemberSubmission,
    _coerce_aggregation_for_value_kind,
)
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
        aggregation: str,
        aggregation_window_days: int | None,
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

    # ---- Templates (CS-2/3) ----

    async def list_templates(
        self, *, include_inactive: bool = False
    ) -> tuple[dict[str, Any], ...]: ...

    async def get_template(
        self, *, template_id: UUID
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]: ...

    async def create_template(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        members: tuple[SignalTemplateDefinitionMember, ...],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]: ...

    async def update_template(
        self,
        *,
        template_id: UUID,
        updates: dict[str, Any],
        members: tuple[SignalTemplateDefinitionMember, ...] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]: ...

    async def delete_template(
        self,
        *,
        template_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None: ...

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
        location_mode: str = "entity",
        location_point: GeopointModel | None = None,
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
        template_observation_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]: ...

    async def create_template_observation(
        self,
        *,
        template_id: UUID,
        farm_id: UUID,
        block_id: UUID | None,
        observed_at: datetime | None,
        location_mode: str,
        location_point: GeopointModel | None,
        members: tuple[SignalTemplateObservationMemberSubmission, ...],
        recorded_by: UUID,
        tenant_schema: str,
    ) -> dict[str, Any]: ...


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
        aggregation: str,
        aggregation_window_days: int | None,
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
        # CS-1 D3 — non-numeric value_kinds always use `latest`. The
        # schema-layer coercion runs here (not in the Pydantic model)
        # because the relevant value_kind comes from the request body
        # alongside the aggregation field.
        coerced_aggregation = _coerce_aggregation_for_value_kind(value_kind, aggregation)
        if coerced_aggregation == "latest" and aggregation_window_days is not None:
            # Window only meaningful for non-latest rules; clamp instead
            # of erroring so non-numeric defs (which always coerce to
            # latest) don't 400 when a UI sends a window unconditionally.
            aggregation_window_days = None

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
            aggregation=coerced_aggregation,
            aggregation_window_days=aggregation_window_days,
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
        # CS-1 D3 — if the caller is changing aggregation, coerce
        # against the existing value_kind (kind itself isn't updatable
        # per SignalDefinitionUpdateRequest). Window-day cleanup mirrors
        # create_definition: `latest` always has window = NULL.
        if "aggregation" in updates and updates["aggregation"] is not None:
            updates["aggregation"] = _coerce_aggregation_for_value_kind(
                str(existing["value_kind"]), updates["aggregation"]
            )
            if updates["aggregation"] == "latest":
                updates["aggregation_window_days"] = None
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

    # ---- Observation delete (CS-11) -----------------------------------

    async def get_observation(self, *, observation_id: UUID) -> dict[str, Any] | None:
        """Lookup used by the delete route to resolve farm_id (for the
        farm-scoped capability check) before deleting."""
        return await self._repo.get_observation(observation_id=observation_id)

    async def get_template_observation_farm(
        self, *, template_observation_id: UUID
    ) -> UUID | None:
        return await self._repo.get_template_observation_farm(
            template_observation_id=template_observation_id
        )

    async def delete_observation(
        self,
        *,
        observation_id: UUID,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        deleted = await self._repo.delete_observation(observation_id=observation_id)
        if deleted == 0:
            raise SignalObservationNotFoundError(observation_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.observation_deleted",
            actor_user_id=actor_user_id,
            subject_kind="signal_observation",
            subject_id=observation_id,
            farm_id=farm_id,
            details={"deleted_count": deleted},
        )

    async def delete_template_observation(
        self,
        *,
        template_observation_id: UUID,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> int:
        """Delete every sibling in a templated group. Returns count deleted."""
        deleted = await self._repo.delete_observations_by_template(
            template_observation_id=template_observation_id
        )
        if deleted == 0:
            raise SignalObservationNotFoundError(template_observation_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.template_observation_deleted",
            actor_user_id=actor_user_id,
            subject_kind="signal_observation",
            subject_id=template_observation_id,
            farm_id=farm_id,
            details={"deleted_count": deleted},
        )
        return deleted

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
        # CS-5 — location_mode/point now reach the single-shot route too
        # (previously only validated on the template-submission endpoint).
        # Defaults preserve the pre-CS-1 API shape: callers who don't pass
        # location_* get the historical entity-mode behaviour.
        location_mode: str = "entity",
        location_point: GeopointModel | None = None,
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
        self._validate_location_presence(location_mode=location_mode, location_point=location_point)
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
        location_point_wkt = (
            f"POINT({location_point.longitude} {location_point.latitude})"
            if location_point is not None
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
            location_mode=location_mode,
            location_point_wkt=location_point_wkt,
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
        template_observation_id: UUID | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        rows = await self._repo.list_observations(
            signal_definition_id=signal_definition_id,
            farm_id=farm_id,
            block_id=block_id,
            since=since,
            until=until,
            template_observation_id=template_observation_id,
            limit=limit,
        )
        return tuple(_enrich_observation(r, storage=self._storage) for r in rows)

    # ---- Templates (CS-2/3) -------------------------------------------

    async def list_templates(self, *, include_inactive: bool = False) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_templates(include_inactive=include_inactive)

    async def get_template(
        self, *, template_id: UUID
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        tpl = await self._repo.get_template(template_id=template_id)
        if tpl is None:
            raise SignalTemplateNotFoundError(template_id)
        members = await self._repo.get_template_members(template_id=template_id)
        return tpl, members

    async def create_template(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        members: tuple[SignalTemplateDefinitionMember, ...],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        self._validate_template_members(members)
        await self._assert_all_definitions_exist(members)

        template_id = uuid7()
        repo_members = tuple((m.signal_definition_id, m.position, m.is_required) for m in members)
        tpl = await self._repo.insert_template(
            template_id=template_id,
            code=code,
            name=name,
            description=description,
            members=repo_members,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.template_created",
            actor_user_id=actor_user_id,
            subject_kind="signal_template",
            subject_id=template_id,
            farm_id=None,
            details={"code": code, "member_count": len(members)},
        )
        member_rows = await self._repo.get_template_members(template_id=template_id)
        return tpl, member_rows

    async def update_template(
        self,
        *,
        template_id: UUID,
        updates: dict[str, Any],
        members: tuple[SignalTemplateDefinitionMember, ...] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        existing = await self._repo.get_template(template_id=template_id)
        if existing is None:
            raise SignalTemplateNotFoundError(template_id)

        repo_members: tuple[tuple[UUID, int, bool], ...] | None = None
        if members is not None:
            if len(members) == 0:
                # The UX layer should never send an empty member list
                # (would leave the template unusable); reject explicitly
                # so we don't accidentally write a half-defined template.
                raise SignalTemplateMembersInvalidError(
                    detail="Template member list cannot be empty on update."
                )
            self._validate_template_members(members)
            await self._assert_all_definitions_exist(members)
            repo_members = tuple(
                (m.signal_definition_id, m.position, m.is_required) for m in members
            )

        out = await self._repo.update_template(
            template_id=template_id,
            updates=updates,
            members=repo_members,
            actor_user_id=actor_user_id,
        )
        if out is None:
            raise SignalTemplateNotFoundError(template_id)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.template_updated",
            actor_user_id=actor_user_id,
            subject_kind="signal_template",
            subject_id=template_id,
            farm_id=None,
            details={
                "code": existing["code"],
                "fields": sorted(updates.keys()),
                "members_replaced": members is not None,
            },
        )
        member_rows = await self._repo.get_template_members(template_id=template_id)
        return out, member_rows

    async def delete_template(
        self,
        *,
        template_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        existing = await self._repo.get_template(template_id=template_id)
        if existing is None:
            raise SignalTemplateNotFoundError(template_id)
        deleted = await self._repo.soft_delete_template(
            template_id=template_id, actor_user_id=actor_user_id
        )
        if not deleted:
            return
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.template_deleted",
            actor_user_id=actor_user_id,
            subject_kind="signal_template",
            subject_id=template_id,
            farm_id=None,
            details={"code": existing["code"]},
        )

    @staticmethod
    def _validate_template_members(
        members: tuple[SignalTemplateDefinitionMember, ...],
    ) -> None:
        """Pre-DB checks for member-shape constraints. The two unique
        constraints in migration 0029 would catch these too, but we'd
        have to do error-message string matching on IntegrityError to
        distinguish them — easier to enforce here so the 400 carries
        which conflict was hit."""
        if not members:
            raise SignalTemplateMembersInvalidError(
                detail="Template must include at least one member."
            )
        seen_defs: set[UUID] = set()
        seen_positions: set[int] = set()
        for m in members:
            if m.signal_definition_id in seen_defs:
                raise SignalTemplateMembersInvalidError(
                    detail=(
                        f"Duplicate signal_definition_id "
                        f"{m.signal_definition_id} in template members."
                    ),
                )
            seen_defs.add(m.signal_definition_id)
            if m.position in seen_positions:
                raise SignalTemplateMembersInvalidError(
                    detail=f"Duplicate position {m.position} in template members.",
                )
            seen_positions.add(m.position)

    async def _assert_all_definitions_exist(
        self, members: tuple[SignalTemplateDefinitionMember, ...]
    ) -> None:
        def_ids = tuple(m.signal_definition_id for m in members)
        missing = await self._repo.missing_definitions(definition_ids=def_ids)
        if missing:
            raise SignalTemplateMembersInvalidError(
                detail=(
                    f"Template references unknown or deleted signal definitions: "
                    f"{', '.join(str(d) for d in missing)}"
                ),
            )

    # ---- Template-observation submission (CS-4) -----------------------

    async def create_template_observation(
        self,
        *,
        template_id: UUID,
        farm_id: UUID,
        block_id: UUID | None,
        observed_at: datetime | None,
        location_mode: str,
        location_point: GeopointModel | None,
        members: tuple[SignalTemplateObservationMemberSubmission, ...],
        recorded_by: UUID,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Atomic N-row insert with shared template_observation_id (D8).

        Validation gates (all surfaced as 400 / 404):
          1. Template exists + not soft-deleted.
          2. Every submitted member's signal_definition_id is actually
             a member of this template (template-bound).
          3. Each submitted value matches its definition's value_kind +
             bounds (delegates to _validate_value).
          4. Attachments respect each definition's attachment_allowed
             + presence in object storage.
          5. location_mode/location_point combo respects the CS-1 D2
             rules (entity ⇒ NULL location_point; point_in_entity /
             free_point ⇒ non-NULL). The ST_Within DB trigger is the
             ultimate authority for point_in_entity correctness; we
             pre-check only the presence rule here.

        Returns the lean response shape: shared template_observation_id
        + counts. Full per-row hydration is `GET
        /signals/observations?template_observation_id=...`.
        """
        if not members:
            # Defensive: schema enforces min_length=1 but a future
            # caller path might bypass Pydantic.
            raise SignalTemplateMembersInvalidError(
                detail="Template submission must include at least one member."
            )
        self._validate_location_presence(location_mode=location_mode, location_point=location_point)

        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise SignalTemplateNotFoundError(template_id)

        # Build the set of definition ids this template binds, then
        # reject submitted member ids that aren't bound. This prevents
        # callers from sneaking observations into a template that
        # doesn't actually contain that definition.
        template_members = await self._repo.get_template_members(template_id=template_id)
        bound_def_ids = {m["signal_definition_id"] for m in template_members}
        submitted_def_ids = [m.signal_definition_id for m in members]
        if len(set(submitted_def_ids)) != len(submitted_def_ids):
            raise SignalTemplateMembersInvalidError(
                detail="Duplicate signal_definition_id in submission members."
            )
        out_of_scope = [d for d in submitted_def_ids if d not in bound_def_ids]
        if out_of_scope:
            raise SignalTemplateMembersInvalidError(
                detail=(
                    f"Members reference signal definitions not bound to template "
                    f"{template_id}: {', '.join(str(d) for d in out_of_scope)}"
                ),
            )

        # Pre-load each definition once; validate every submitted value
        # before any insert fires so a single bad member can't leave
        # half the batch in the DB.
        defs_by_id: dict[UUID, dict[str, Any]] = {}
        for member in members:
            defn = await self._repo.get_definition(definition_id=member.signal_definition_id)
            if defn is None:
                # Race: a definition was soft-deleted between
                # get_template_members and now. Surface as the
                # same 400 the bound-check uses.
                raise SignalTemplateMembersInvalidError(
                    detail=(
                        f"Signal definition {member.signal_definition_id} "
                        f"was deleted between template fetch and submit; retry."
                    ),
                )
            defs_by_id[member.signal_definition_id] = defn
            self._validate_value(
                defn=defn,
                request_values={
                    "value_numeric": member.value_numeric,
                    "value_categorical": member.value_categorical,
                    "value_event": member.value_event,
                    "value_boolean": member.value_boolean,
                    "value_geopoint": member.value_geopoint,
                },
            )
            if member.attachment_s3_key is not None:
                if not defn["attachment_allowed"]:
                    raise AttachmentNotPermittedError(code=defn["code"])
                try:
                    self._storage.head_object(key=member.attachment_s3_key)
                except StorageObjectMissingError as exc:
                    raise AttachmentMissingError(key=member.attachment_s3_key) from exc

        # Lead row id is the shared template_observation_id (D8: the
        # lead row stores its own id, siblings carry it).
        lead_observation_id = uuid7()
        observation_time = observed_at or datetime.now(UTC)
        location_point_wkt = (
            f"POINT({location_point.longitude} {location_point.latitude})"
            if location_point is not None
            else None
        )

        for index, member in enumerate(members):
            obs_id = lead_observation_id if index == 0 else uuid7()
            value_geopoint_wkt = (
                f"POINT({member.value_geopoint.longitude} {member.value_geopoint.latitude})"
                if member.value_geopoint is not None
                else None
            )
            await self._repo.insert_observation(
                observation_id=obs_id,
                time=observation_time,
                signal_definition_id=member.signal_definition_id,
                farm_id=farm_id,
                block_id=block_id,
                value_numeric=member.value_numeric,
                value_categorical=member.value_categorical,
                value_event=member.value_event,
                value_boolean=member.value_boolean,
                value_geopoint_wkt=value_geopoint_wkt,
                attachment_s3_key=member.attachment_s3_key,
                notes=member.notes,
                recorded_by=recorded_by,
                template_observation_id=lead_observation_id,
                location_mode=location_mode,
                location_point_wkt=location_point_wkt,
            )

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.template_observation_recorded",
            actor_user_id=recorded_by,
            subject_kind="signal_template_observation",
            subject_id=lead_observation_id,
            farm_id=farm_id,
            details={
                "template_id": str(template_id),
                "template_code": template["code"],
                "block_id": str(block_id) if block_id else None,
                "observation_count": len(members),
                "location_mode": location_mode,
            },
        )

        return {
            "template_observation_id": lead_observation_id,
            "template_id": template_id,
            "farm_id": farm_id,
            "block_id": block_id,
            "observed_at": observation_time,
            "observation_count": len(members),
        }

    @staticmethod
    def _validate_location_presence(
        *, location_mode: str, location_point: GeopointModel | None
    ) -> None:
        """CS-1 D2 presence rule. The DB CHECK constraint enforces the
        same shape, but checking here surfaces a clean 400 with field
        context instead of a low-level IntegrityError."""
        if location_mode == "entity":
            if location_point is not None:
                raise InvalidSignalValueError(
                    detail="location_mode='entity' must not include a location_point."
                )
        elif location_mode in {"point_in_entity", "free_point"}:
            if location_point is None:
                raise InvalidSignalValueError(
                    detail=f"location_mode={location_mode!r} requires a location_point."
                )
        else:
            raise InvalidSignalValueError(detail=f"Unknown location_mode {location_mode!r}.")

    # ---- CSV import (CS-7) --------------------------------------------

    async def import_observations_csv(
        self,
        *,
        farm_id: UUID,
        csv_bytes: bytes,
        recorded_by: UUID,
        tenant_schema: str,
    ) -> dict[str, int]:
        """Strict-mode CSV import. Either every row is inserted in one
        transaction, or none are and we raise CsvImportFailedError with
        the per-row diagnostics (D4).

        Validation runs in two passes:

          1. csv_import.parse_csv — shape errors (missing required
             columns, unparseable timestamps, multiple value columns
             set, etc.).
          2. Service-level business-rule validation — each row's
             signal_code resolves to an active definition, the value
             column matches its value_kind, numeric bounds hold,
             categorical-membership holds.

        The two passes accumulate into one error list; the caller
        either sees `rows_imported` on success or the combined
        error report on failure.
        """
        if len(csv_bytes) > CSV_MAX_BYTES:
            raise CsvImportTooLargeError(size_bytes=len(csv_bytes), limit_bytes=CSV_MAX_BYTES)

        try:
            text_body = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CsvImportFailedError(
                errors=[
                    {
                        "row_number": 1,
                        "field": None,
                        "message": (
                            "Could not decode file as UTF-8. Save the CSV "
                            f"as UTF-8 and re-upload. (decode error: {exc})"
                        ),
                    }
                ]
            ) from exc

        parsed = parse_csv(text_body)

        # Resolve unique signal_codes referenced in the file → load
        # each definition once. Codes missing from the catalog produce
        # a row-level error.
        codes_referenced = {r.signal_code for r in parsed.rows}
        defs_by_code: dict[str, dict[str, Any]] = {}
        for code in sorted(codes_referenced):
            defn = await self._repo.get_definition(code=code)
            if defn is not None:
                defs_by_code[code] = defn

        # Second-pass: business-rule validation.
        business_errors: list[CsvRowError] = []
        for row in parsed.rows:
            defn = defs_by_code.get(row.signal_code)
            if defn is None:
                business_errors.append(
                    CsvRowError(
                        row_number=row.row_number,
                        field="signal_code",
                        message=(
                            f"No active signal definition with code "
                            f"{row.signal_code!r} in this tenant."
                        ),
                    )
                )
                continue
            try:
                self._validate_value(
                    defn=defn,
                    request_values={
                        "value_numeric": row.value_numeric,
                        "value_categorical": row.value_categorical,
                        "value_event": row.value_event,
                        "value_boolean": row.value_boolean,
                        "value_geopoint": None,
                    },
                )
            except InvalidSignalValueError as exc:
                # exc.detail is typed `str | None` on the base APIError
                # but InvalidSignalValueError always passes a detail; the
                # fallback is defensive only.
                business_errors.append(
                    CsvRowError(
                        row_number=row.row_number,
                        field=None,
                        message=exc.detail or "Invalid signal value.",
                    )
                )

        all_errors = parsed.errors + business_errors
        if all_errors:
            raise CsvImportFailedError(
                errors=[
                    {"row_number": e.row_number, "field": e.field, "message": e.message}
                    for e in all_errors
                ]
            )

        # All-or-nothing insert. Caller's session wraps the whole
        # batch in a single transaction so a mid-loop DB error rolls
        # back the partial insertion.
        for row in parsed.rows:
            defn = defs_by_code[row.signal_code]
            await self._repo.insert_observation(
                observation_id=uuid7(),
                time=row.observed_at,
                signal_definition_id=defn["id"],
                farm_id=farm_id,
                block_id=row.block_id,
                value_numeric=row.value_numeric,
                value_categorical=row.value_categorical,
                value_event=row.value_event,
                value_boolean=row.value_boolean,
                value_geopoint_wkt=None,
                attachment_s3_key=None,
                notes=row.notes,
                recorded_by=recorded_by,
            )

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="signals.observations_csv_imported",
            actor_user_id=recorded_by,
            subject_kind="signal_observation",
            subject_id=None,
            farm_id=farm_id,
            details={
                "rows_imported": len(parsed.rows),
                "signal_codes": sorted(codes_referenced),
            },
        )
        return {"rows_imported": len(parsed.rows)}


def _enrich_observation(row: dict[str, Any], *, storage: StorageClient) -> dict[str, Any]:
    """Map repository row → API shape: rename geopoint, attach a
    short-lived presigned download URL when an attachment is set.
    CS-5 also unwraps the location_point GeoJSON Point the same way
    value_geopoint is unwrapped."""
    out = dict(row)
    out["value_geopoint"] = _geojson_point_to_geopoint(out.pop("value_geopoint_geojson", None))
    out["location_point"] = _geojson_point_to_geopoint(out.pop("location_point_geojson", None))
    key = out.get("attachment_s3_key")
    if key:
        out["attachment_download_url"] = storage.presign_download(key=key).url
    else:
        out["attachment_download_url"] = None
    return out


def _geojson_point_to_geopoint(geo: Any) -> dict[str, float] | None:
    if isinstance(geo, dict) and geo.get("type") == "Point":
        coords = geo.get("coordinates") or []
        if len(coords) == 2:
            return {"longitude": coords[0], "latitude": coords[1]}
    return None


def get_signals_service(*, tenant_session: AsyncSession) -> SignalsServiceImpl:
    return SignalsServiceImpl(tenant_session=tenant_session)


def _check(impl: SignalsServiceImpl) -> SignalsService:
    return impl
