"""Farms service: public Protocol + concrete implementation.

Other modules depend on `FarmService` (the Protocol), never on
`FarmServiceImpl`. The router and tests construct an instance per
request via `get_farm_service`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as _date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.farms import auto_grid as _auto_grid
from app.modules.farms import cascade as _cascade
from app.modules.farms import geometry as _geometry
from app.modules.farms import pivot_geometry as _pivot_geometry
from app.modules.farms.errors import (
    BlockNotFoundError,
    FarmNotFoundError,
    InvalidUnitTypeError,
)
from app.modules.farms.events import (
    BlockAttachmentDeletedV1,
    BlockAttachmentUploadedV1,
    BlockBoundaryChangedV1,
    BlockCreatedV1,
    BlockCropAssignedV1,
    BlockInactivatedV1,
    BlockReactivatedV1,
    BlockUpdatedV1,
    FarmAttachmentDeletedV1,
    FarmAttachmentUploadedV1,
    FarmBoundaryChangedV1,
    FarmCreatedV1,
    FarmInactivatedV1,
    FarmMemberAssignedV1,
    FarmMemberRevokedV1,
    FarmReactivatedV1,
    FarmUpdatedV1,
)
from app.modules.farms.repository import FarmsRepository
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus
from app.shared.storage import (
    PresignedDownload,
    StorageClient,
    StorageObjectMissingError,
    build_attachment_key,
    get_storage_client,
)

# Conversion factors per data_model § 1.5.
_M2_PER_FEDDAN = Decimal("4200.83")
_M2_PER_ACRE = Decimal("4046.86")
_M2_PER_HECTARE = Decimal("10000")


def _convert_area(area_m2: Decimal | None, unit: str) -> Decimal:
    if area_m2 is None:
        return Decimal("0")
    if unit == "feddan":
        return (area_m2 / _M2_PER_FEDDAN).quantize(Decimal("0.01"))
    if unit == "acre":
        return (area_m2 / _M2_PER_ACRE).quantize(Decimal("0.01"))
    return (area_m2 / _M2_PER_HECTARE).quantize(Decimal("0.01"))


def _stamp_area_unit(item: dict[str, Any], preferred_unit: str) -> dict[str, Any]:
    item["area_unit"] = preferred_unit
    item["area_value"] = _convert_area(item.get("area_m2"), preferred_unit)
    return item


def _centroid_lat_lon(centroid_geojson: dict[str, Any] | None) -> tuple[float, float]:
    if centroid_geojson and centroid_geojson.get("type") == "Point":
        coords = centroid_geojson.get("coordinates") or [0.0, 0.0]
        return float(coords[0]), float(coords[1])
    return 0.0, 0.0


# ---------- Protocol --------------------------------------------------------


class FarmService(Protocol):
    """Public contract — the only `farms` module surface other modules see."""

    async def create_farm(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        boundary: dict[str, Any],
        elevation_m: Decimal | None,
        governorate: str | None,
        district: str | None,
        nearest_city: str | None,
        address_line: str | None,
        farm_type: str,
        ownership_type: str | None,
        primary_water_source: str | None,
        established_date: Any,
        tags: list[str],
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        active_from: _date | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_farms(
        self,
        *,
        after: UUID | None,
        limit: int,
        governorate: str | None,
        tag: str | None,
        include_inactive: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]: ...

    async def get_farm(self, *, farm_id: UUID, preferred_unit: str) -> dict[str, Any]: ...

    async def update_farm(
        self,
        *,
        farm_id: UUID,
        changes: dict[str, Any],
        new_boundary: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def preview_farm_inactivation(
        self,
        *,
        farm_id: UUID,
    ) -> dict[str, Any]: ...

    async def inactivate_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        reason: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def reactivate_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        restore_blocks: bool = False,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def create_block(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str | None,
        boundary: dict[str, Any],
        elevation_m: Decimal | None,
        irrigation_system: str | None,
        irrigation_source: str | None,
        soil_texture: str | None,
        salinity_class: str | None,
        soil_ph: Decimal | None,
        responsible_user_id: UUID | None,
        notes: str | None,
        tags: list[str],
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        unit_type: str = "block",
        parent_unit_id: UUID | None = None,
        irrigation_geometry: dict[str, Any] | None = None,
        active_from: _date | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_blocks(
        self,
        *,
        farm_id: UUID,
        after: UUID | None,
        limit: int,
        irrigation_system: str | None,
        include_inactive: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]: ...

    async def get_block(self, *, block_id: UUID, preferred_unit: str) -> dict[str, Any]: ...

    async def update_block(
        self,
        *,
        block_id: UUID,
        changes: dict[str, Any],
        new_boundary: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def preview_block_inactivation(
        self,
        *,
        block_id: UUID,
    ) -> dict[str, Any]: ...

    async def inactivate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        reason: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def reactivate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def auto_grid(self, *, farm_id: UUID, cell_size_m: int) -> dict[str, Any]: ...

    async def create_pivot_with_sectors(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str | None,
        center_lat: float,
        center_lon: float,
        radius_m: float,
        sector_count: int,
        irrigation_system: str | None,
        active_from: _date | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def assign_block_crop(
        self,
        *,
        block_id: UUID,
        crop_id: UUID,
        crop_variety_id: UUID | None,
        season_label: str,
        planting_date: Any,
        expected_harvest_start: Any,
        expected_harvest_end: Any,
        plant_density_per_ha: Decimal | None,
        row_spacing_m: Decimal | None,
        plant_spacing_m: Decimal | None,
        notes: str | None,
        make_current: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_block_crops(self, *, block_id: UUID) -> list[dict[str, Any]]: ...

    async def record_growth_stage_transition(
        self,
        *,
        block_id: UUID,
        stage: str,
        source: str,
        transition_date: datetime | None,
        block_crop_id: UUID | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_growth_stage_logs(self, *, block_id: UUID) -> list[dict[str, Any]]: ...

    async def assign_member(
        self,
        *,
        farm_id: UUID,
        membership_id: UUID,
        role: str,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def revoke_member(
        self,
        *,
        farm_id: UUID,
        farm_scope_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_members(self, *, farm_id: UUID) -> list[dict[str, Any]]: ...

    async def init_farm_attachment_upload(
        self,
        *,
        farm_id: UUID,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        tenant_id: UUID,
    ) -> dict[str, Any]: ...

    async def finalize_farm_attachment(
        self,
        *,
        farm_id: UUID,
        attachment_id: UUID,
        s3_key: str,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_farm_attachments(self, *, farm_id: UUID) -> list[dict[str, Any]]: ...

    async def delete_farm_attachment(
        self,
        *,
        attachment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

    async def init_block_attachment_upload(
        self,
        *,
        block_id: UUID,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        tenant_id: UUID,
    ) -> dict[str, Any]: ...

    async def finalize_block_attachment(
        self,
        *,
        block_id: UUID,
        attachment_id: UUID,
        s3_key: str,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_block_attachments(self, *, block_id: UUID) -> list[dict[str, Any]]: ...

    async def delete_block_attachment(
        self,
        *,
        attachment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

    async def list_crops(self, *, category: str | None = None) -> list[dict[str, Any]]: ...

    async def list_crop_varieties(self, *, crop_id: UUID) -> list[dict[str, Any]]: ...


# ---------- Implementation --------------------------------------------------


class FarmServiceImpl:
    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        public_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
        storage_client: StorageClient | None = None,
    ) -> None:
        self._tenant_session = tenant_session
        self._public_session = public_session
        self._repo = FarmsRepository(tenant_session, public_session=public_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._storage = storage_client or get_storage_client()
        self._log = get_logger(__name__)

    # ---- Farms ------------------------------------------------------

    async def create_farm(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        boundary: dict[str, Any],
        elevation_m: Decimal | None,
        governorate: str | None,
        district: str | None,
        nearest_city: str | None,
        address_line: str | None,
        farm_type: str,
        ownership_type: str | None,
        primary_water_source: str | None,
        established_date: Any,
        tags: list[str],
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        active_from: _date | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        _geometry.validate_multipolygon_geojson(boundary)
        ewkt = _geometry.geojson_to_ewkt_multipolygon(boundary)

        farm_id = uuid7()
        await self._repo.insert_farm(
            farm_id=farm_id,
            code=code,
            name=name,
            description=description,
            boundary_ewkt=ewkt,
            elevation_m=elevation_m,
            governorate=governorate,
            district=district,
            nearest_city=nearest_city,
            address_line=address_line,
            farm_type=farm_type,
            ownership_type=ownership_type,
            primary_water_source=primary_water_source,
            established_date=established_date,
            tags=tags,
            actor_user_id=actor_user_id,
            active_from=active_from,
        )
        await self._tenant_session.flush()

        farm = await self._repo.get_farm_by_id(farm_id)
        if farm is None:  # pragma: no cover — defensive
            raise FarmNotFoundError(farm_id)

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_created",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={"code": code, "name": name, "area_m2": str(farm["area_m2"])},
            correlation_id=correlation_id,
        )

        self._bus.publish(
            FarmCreatedV1(
                farm_id=farm_id,
                code=code,
                name=name,
                area_m2=farm["area_m2"],
                actor_user_id=actor_user_id,
                created_at=farm["created_at"],
            )
        )
        return _stamp_area_unit(farm, preferred_unit)

    async def list_farms(
        self,
        *,
        after: UUID | None,
        limit: int,
        governorate: str | None,
        tag: str | None,
        include_inactive: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_farms(
            after=after,
            limit=limit,
            governorate=governorate,
            tag=tag,
            include_inactive=include_inactive,
        )
        return [_stamp_area_unit(r, preferred_unit) for r in rows]

    async def get_farm(self, *, farm_id: UUID, preferred_unit: str) -> dict[str, Any]:
        farm = await self._repo.get_farm_by_id(farm_id)
        if farm is None:
            raise FarmNotFoundError(farm_id)
        return _stamp_area_unit(farm, preferred_unit)

    async def update_farm(
        self,
        *,
        farm_id: UUID,
        changes: dict[str, Any],
        new_boundary: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        ewkt: str | None = None
        if new_boundary is not None:
            _geometry.validate_multipolygon_geojson(new_boundary)
            ewkt = _geometry.geojson_to_ewkt_multipolygon(new_boundary)

        farm = await self._repo.update_farm(
            farm_id=farm_id,
            changes=changes,
            boundary_ewkt=ewkt,
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()

        changed = tuple(sorted({*changes.keys(), *(("boundary",) if ewkt else ())}))
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_updated",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={"changed_fields": list(changed)},
            correlation_id=correlation_id,
        )

        self._bus.publish(
            FarmUpdatedV1(farm_id=farm_id, changed_fields=changed, actor_user_id=actor_user_id)
        )
        if ewkt is not None:
            lon, lat = _centroid_lat_lon(farm.get("centroid"))
            self._bus.publish(
                FarmBoundaryChangedV1(
                    farm_id=farm_id,
                    new_centroid_lon=lon,
                    new_centroid_lat=lat,
                    actor_user_id=actor_user_id,
                )
            )
        return _stamp_area_unit(farm, preferred_unit)

    async def preview_farm_inactivation(self, *, farm_id: UUID) -> dict[str, Any]:
        """Return the cascade counts (and child block count) for the modal."""
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)
        block_ids = await self._repo.list_active_block_ids_for_farm(farm_id=farm_id)
        counts = await _cascade.preview_block_cascade(
            session=self._tenant_session, block_ids=block_ids
        )
        return {
            "block_count": len(block_ids),
            **counts.as_dict(),
        }

    async def inactivate_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        reason: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Set active_to on the farm and cascade-inactivate every active block."""
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)
        block_ids = await self._repo.list_active_block_ids_for_farm(farm_id=farm_id)

        # Apply the cascade BEFORE flipping the farm/block rows — the
        # cascade reads from those tables, so doing it last would let
        # any pending row remain pending. Same transaction either way.
        counts = await _cascade.apply_block_cascade(
            session=self._tenant_session,
            block_ids=block_ids,
            actor_user_id=actor_user_id,
            reason_code="farm_inactivated",
        )
        for bid in block_ids:
            await self._repo.inactivate_block(block_id=bid, actor_user_id=actor_user_id)
        await self._repo.inactivate_farm(farm_id=farm_id, actor_user_id=actor_user_id)
        await self._tenant_session.flush()

        today_str = datetime.now(UTC).date().isoformat()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_inactivated",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={
                "reason": reason,
                "active_to": today_str,
                "cascaded_block_count": len(block_ids),
                **counts.as_dict(),
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmInactivatedV1(
                farm_id=farm_id,
                active_to=today_str,
                cascaded_block_count=len(block_ids),
                actor_user_id=actor_user_id,
            )
        )
        return {
            "farm_id": farm_id,
            "active_to": today_str,
            "block_count": len(block_ids),
            **counts.as_dict(),
        }

    async def reactivate_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        restore_blocks: bool = False,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Clear active_to. ``restore_blocks`` decides whether to also lift
        active_to on every block that was inactivated by the farm cascade.

        Because the cascade fans out without a per-block 'reason', we
        conservatively interpret "restore" as: reactivate every currently
        inactive block under the farm. Operators who only want partial
        restore should hit the per-block reactivate endpoint instead.
        """
        await self._repo.reactivate_farm(farm_id=farm_id, actor_user_id=actor_user_id)
        restored = 0
        if restore_blocks:
            inactive_ids = await self._list_inactive_block_ids_for_farm(farm_id)
            for bid in inactive_ids:
                await self._repo.reactivate_block(block_id=bid, actor_user_id=actor_user_id)
                restored += 1
        await self._tenant_session.flush()

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={"restored_block_count": restored},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmReactivatedV1(
                farm_id=farm_id,
                restored_block_count=restored,
                actor_user_id=actor_user_id,
            )
        )
        return {"farm_id": farm_id, "restored_block_count": restored}

    async def _list_inactive_block_ids_for_farm(self, farm_id: UUID) -> tuple[UUID, ...]:
        """Block IDs under a farm that currently have ``deleted_at`` stamped."""
        from sqlalchemy import select

        from app.modules.farms.models import Block

        rows = (
            await self._tenant_session.execute(
                select(Block.id).where(Block.farm_id == farm_id, Block.deleted_at.is_not(None))
            )
        ).all()
        return tuple(r.id for r in rows)

    # ---- Blocks -----------------------------------------------------

    async def create_block(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str | None,
        boundary: dict[str, Any],
        elevation_m: Decimal | None,
        irrigation_system: str | None,
        irrigation_source: str | None,
        soil_texture: str | None,
        salinity_class: str | None,
        soil_ph: Decimal | None,
        responsible_user_id: UUID | None,
        notes: str | None,
        tags: list[str],
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        unit_type: str = "block",
        parent_unit_id: UUID | None = None,
        irrigation_geometry: dict[str, Any] | None = None,
        active_from: _date | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        _geometry.validate_polygon_geojson(boundary)
        ewkt = _geometry.geojson_to_ewkt_polygon(boundary)
        await self._validate_unit_type_and_parent(
            farm_id=farm_id,
            unit_type=unit_type,
            parent_unit_id=parent_unit_id,
        )

        block_id = uuid7()
        await self._repo.insert_block(
            block_id=block_id,
            farm_id=farm_id,
            code=code,
            name=name,
            boundary_ewkt=ewkt,
            elevation_m=elevation_m,
            irrigation_system=irrigation_system,
            irrigation_source=irrigation_source,
            soil_texture=soil_texture,
            salinity_class=salinity_class,
            soil_ph=soil_ph,
            responsible_user_id=responsible_user_id,
            notes=notes,
            tags=tags,
            actor_user_id=actor_user_id,
            unit_type=unit_type,
            parent_unit_id=parent_unit_id,
            irrigation_geometry=irrigation_geometry,
            active_from=active_from,
        )
        await self._tenant_session.flush()

        block = await self._repo.get_block_by_id(block_id)
        if block is None:  # pragma: no cover
            raise BlockNotFoundError(block_id)

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_created",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=farm_id,
            details={
                "code": code,
                "area_m2": str(block["area_m2"]),
                "aoi_hash": block["aoi_hash"],
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockCreatedV1(
                block_id=block_id,
                farm_id=farm_id,
                code=code,
                area_m2=block["area_m2"],
                aoi_hash=block["aoi_hash"],
                actor_user_id=actor_user_id,
            )
        )
        return _stamp_area_unit(block, preferred_unit)

    async def _validate_unit_type_and_parent(
        self,
        *,
        farm_id: UUID,
        unit_type: str,
        parent_unit_id: UUID | None,
    ) -> None:
        """Enforce the cross-row invariants the DB CHECK can't.

        Block-level CHECK already enforces that pivot_sector requires a
        parent and that block/pivot must leave it null. What CHECK
        cannot do: confirm the parent points at a *pivot* on the *same
        farm* — both involve a second row, so we look it up.
        """
        if unit_type == "pivot_sector":
            if parent_unit_id is None:
                raise InvalidUnitTypeError(
                    reason="pivot_sector requires parent_unit_id pointing to a pivot.",
                    extra={"unit_type": unit_type},
                )
            parent = await self._repo.get_block_by_id(parent_unit_id, with_boundary=False)
            if parent is None:
                raise InvalidUnitTypeError(
                    reason=f"Parent unit {parent_unit_id} not found in this tenant.",
                    extra={"parent_unit_id": str(parent_unit_id)},
                )
            if parent["unit_type"] != "pivot":
                raise InvalidUnitTypeError(
                    reason=(
                        f"Parent unit {parent_unit_id} has unit_type "
                        f"{parent['unit_type']!r}; pivot_sector parent must be a pivot."
                    ),
                    extra={
                        "parent_unit_id": str(parent_unit_id),
                        "parent_unit_type": parent["unit_type"],
                    },
                )
            if parent["farm_id"] != farm_id:
                raise InvalidUnitTypeError(
                    reason="Parent pivot must belong to the same farm as the sector.",
                    extra={
                        "parent_unit_id": str(parent_unit_id),
                        "parent_farm_id": str(parent["farm_id"]),
                        "expected_farm_id": str(farm_id),
                    },
                )
        elif parent_unit_id is not None:
            # block / pivot must not carry a parent.
            raise InvalidUnitTypeError(
                reason=(
                    f"unit_type {unit_type!r} must not set parent_unit_id; "
                    "only pivot_sector references a parent."
                ),
                extra={"unit_type": unit_type},
            )

    async def list_blocks(
        self,
        *,
        farm_id: UUID,
        after: UUID | None,
        limit: int,
        irrigation_system: str | None,
        include_inactive: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]:
        # Confirm farm exists; cross-tenant calls return 404 here.
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)

        rows = await self._repo.list_blocks(
            farm_id=farm_id,
            after=after,
            limit=limit,
            irrigation_system=irrigation_system,
            include_inactive=include_inactive,
        )
        return [_stamp_area_unit(r, preferred_unit) for r in rows]

    async def get_block(self, *, block_id: UUID, preferred_unit: str) -> dict[str, Any]:
        block = await self._repo.get_block_by_id(block_id)
        if block is None:
            raise BlockNotFoundError(block_id)
        return _stamp_area_unit(block, preferred_unit)

    async def update_block(
        self,
        *,
        block_id: UUID,
        changes: dict[str, Any],
        new_boundary: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        ewkt: str | None = None
        if new_boundary is not None:
            _geometry.validate_polygon_geojson(new_boundary)
            ewkt = _geometry.geojson_to_ewkt_polygon(new_boundary)

        block, prev_aoi_hash = await self._repo.update_block(
            block_id=block_id,
            changes=changes,
            boundary_ewkt=ewkt,
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()

        changed = tuple(sorted({*changes.keys(), *(("boundary",) if ewkt else ())}))
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_updated",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=block["farm_id"],
            details={"changed_fields": list(changed)},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockUpdatedV1(block_id=block_id, changed_fields=changed, actor_user_id=actor_user_id)
        )
        if ewkt is not None and prev_aoi_hash is not None:
            self._bus.publish(
                BlockBoundaryChangedV1(
                    block_id=block_id,
                    farm_id=block["farm_id"],
                    prev_aoi_hash=prev_aoi_hash,
                    new_aoi_hash=block["aoi_hash"],
                    actor_user_id=actor_user_id,
                )
            )
        return _stamp_area_unit(block, preferred_unit)

    async def preview_block_inactivation(self, *, block_id: UUID) -> dict[str, Any]:
        if (await self._repo.get_block_by_id(block_id, with_boundary=False)) is None:
            raise BlockNotFoundError(block_id)
        counts = await _cascade.preview_block_cascade(
            session=self._tenant_session, block_ids=[block_id]
        )
        return counts.as_dict()

    async def inactivate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        reason: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        block = await self._repo.get_block_by_id(block_id, with_boundary=False)
        if block is None:
            raise BlockNotFoundError(block_id)

        counts = await _cascade.apply_block_cascade(
            session=self._tenant_session,
            block_ids=[block_id],
            actor_user_id=actor_user_id,
            reason_code="block_inactivated",
        )
        farm_id = await self._repo.inactivate_block(block_id=block_id, actor_user_id=actor_user_id)
        await self._tenant_session.flush()

        today_str = datetime.now(UTC).date().isoformat()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_inactivated",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=farm_id,
            details={"reason": reason, "active_to": today_str, **counts.as_dict()},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockInactivatedV1(
                block_id=block_id,
                farm_id=farm_id,
                active_to=today_str,
                actor_user_id=actor_user_id,
            )
        )
        return {
            "block_id": block_id,
            "farm_id": farm_id,
            "active_to": today_str,
            **counts.as_dict(),
        }

    async def reactivate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        farm_id = await self._repo.reactivate_block(block_id=block_id, actor_user_id=actor_user_id)
        await self._tenant_session.flush()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=farm_id,
            details={},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockReactivatedV1(block_id=block_id, farm_id=farm_id, actor_user_id=actor_user_id)
        )
        return {"block_id": block_id, "farm_id": farm_id}

    # ---- Pivots + sectors -------------------------------------------

    async def create_pivot_with_sectors(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str | None,
        center_lat: float,
        center_lon: float,
        radius_m: float,
        sector_count: int,
        irrigation_system: str | None,
        active_from: _date | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        preferred_unit: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Insert a pivot + N pivot_sector children atomically.

        Geometry is computed in Python (spherical approximation); the
        existing ``blocks_geom_compute`` trigger reprojects each row to
        UTM and stamps ``area_m2``. All inserts share the caller's
        tenant transaction so a downstream failure rolls everything
        back.
        """
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)

        pivot_polygon = _pivot_geometry.circle_polygon(
            lat=center_lat, lon=center_lon, radius_m=radius_m
        )
        sector_polygons = _pivot_geometry.equal_sectors(
            lat=center_lat,
            lon=center_lon,
            radius_m=radius_m,
            sector_count=sector_count,
        )

        pivot_id = uuid7()
        pivot_ewkt = _geometry.geojson_to_ewkt_polygon(pivot_polygon)
        await self._repo.insert_block(
            block_id=pivot_id,
            farm_id=farm_id,
            code=code,
            name=name,
            boundary_ewkt=pivot_ewkt,
            elevation_m=None,
            irrigation_system=irrigation_system,
            irrigation_source=None,
            soil_texture=None,
            salinity_class=None,
            soil_ph=None,
            responsible_user_id=None,
            notes=None,
            tags=[],
            actor_user_id=actor_user_id,
            unit_type="pivot",
            parent_unit_id=None,
            irrigation_geometry={
                "center": {"lat": center_lat, "lon": center_lon},
                "radius_m": radius_m,
                "sector_count": sector_count,
            },
            active_from=active_from,
        )

        # Sectors. Codes are deterministic suffixes — `<pivot_code>-S1` ...
        # `-S{N}`. Same farm-scoped uniqueness as plain blocks.
        sector_ids: list[UUID] = []
        for i, poly in enumerate(sector_polygons, start=1):
            sec_id = uuid7()
            await self._repo.insert_block(
                block_id=sec_id,
                farm_id=farm_id,
                code=f"{code}-S{i}",
                name=None,
                boundary_ewkt=_geometry.geojson_to_ewkt_polygon(poly),
                elevation_m=None,
                irrigation_system=irrigation_system,
                irrigation_source=None,
                soil_texture=None,
                salinity_class=None,
                soil_ph=None,
                responsible_user_id=None,
                notes=None,
                tags=[],
                actor_user_id=actor_user_id,
                unit_type="pivot_sector",
                parent_unit_id=pivot_id,
                irrigation_geometry=None,
                active_from=active_from,
            )
            sector_ids.append(sec_id)
        await self._tenant_session.flush()

        # Fetch the materialized rows back so the response carries the
        # computed area + boundary.
        pivot_row = await self._repo.get_block_by_id(pivot_id)
        sector_rows = [await self._repo.get_block_by_id(sid) for sid in sector_ids]
        if pivot_row is None or any(s is None for s in sector_rows):
            # Should never happen — insert succeeded and we hold the txn.
            raise BlockNotFoundError(pivot_id)

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.pivot_created",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=pivot_id,
            farm_id=farm_id,
            details={
                "code": code,
                "sector_count": sector_count,
                "radius_m": radius_m,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockCreatedV1(
                block_id=pivot_id,
                farm_id=farm_id,
                code=code,
                area_m2=pivot_row["area_m2"],
                aoi_hash=pivot_row["aoi_hash"],
                actor_user_id=actor_user_id,
            )
        )

        return {
            "pivot": _stamp_area_unit(pivot_row, preferred_unit),
            "sectors": [_stamp_area_unit(s, preferred_unit) for s in sector_rows if s],
        }

    # ---- Auto-grid --------------------------------------------------

    async def auto_grid(self, *, farm_id: UUID, cell_size_m: int) -> dict[str, Any]:
        farm = await self._repo.get_farm_by_id(farm_id, with_boundary=True)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        candidates = _auto_grid.auto_grid_candidates(farm["boundary"], cell_size_m=cell_size_m)
        return {
            "cell_size_m": cell_size_m,
            "candidates": [
                {
                    "code": c["code"],
                    "boundary": c["geometry"],
                    "area_m2": c["area_m2"],
                }
                for c in candidates
            ],
        }

    # ---- Block crops ------------------------------------------------

    async def assign_block_crop(
        self,
        *,
        block_id: UUID,
        crop_id: UUID,
        crop_variety_id: UUID | None,
        season_label: str,
        planting_date: Any,
        expected_harvest_start: Any,
        expected_harvest_end: Any,
        plant_density_per_ha: Decimal | None,
        row_spacing_m: Decimal | None,
        plant_spacing_m: Decimal | None,
        notes: str | None,
        make_current: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        bc_id = uuid7()
        result = await self._repo.insert_block_crop(
            block_crop_id=bc_id,
            block_id=block_id,
            crop_id=crop_id,
            crop_variety_id=crop_variety_id,
            season_label=season_label,
            planting_date=planting_date,
            expected_harvest_start=expected_harvest_start,
            expected_harvest_end=expected_harvest_end,
            plant_density_per_ha=plant_density_per_ha,
            row_spacing_m=row_spacing_m,
            plant_spacing_m=plant_spacing_m,
            notes=notes,
            make_current=make_current,
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()

        # Fetch farm_id for audit.farm_id (the block_id alone is not enough).
        block = await self._repo.get_block_by_id(block_id, with_boundary=False)
        farm_id = block["farm_id"] if block else None

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_crop_assigned",
            actor_user_id=actor_user_id,
            subject_kind="block_crop",
            subject_id=bc_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "crop_id": str(crop_id),
                "season_label": season_label,
                "is_current": make_current,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockCropAssignedV1(
                block_crop_id=bc_id,
                block_id=block_id,
                crop_id=crop_id,
                crop_variety_id=crop_variety_id,
                season_label=season_label,
                actor_user_id=actor_user_id,
            )
        )
        return result

    async def list_block_crops(self, *, block_id: UUID) -> list[dict[str, Any]]:
        return await self._repo.list_block_crops(block_id=block_id)

    # ---- Growth-stage logs (PR-3) -----------------------------------

    async def record_growth_stage_transition(
        self,
        *,
        block_id: UUID,
        stage: str,
        source: str,
        transition_date: datetime | None,
        block_crop_id: UUID | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Append a transition + reflect it on the current `block_crops` row.

        ``block_crop_id`` defaults to the block's current crop when not
        supplied — that's the common case (manual UI entry). When the
        block has no current crop, the log row still lands but isn't
        linked to any assignment, and the canonical "current stage" on
        block_crops is left untouched.
        """
        # Resolve the target block_crop. If caller didn't pin one,
        # use whichever assignment is `is_current`.
        target_block_crop_id: UUID | None = block_crop_id
        if target_block_crop_id is None:
            assignments = await self._repo.list_block_crops(block_id=block_id)
            current = next((bc for bc in assignments if bc["is_current"]), None)
            if current is not None:
                target_block_crop_id = current["id"]

        log_id = uuid7()
        when = transition_date or datetime.now(UTC)
        log = await self._repo.insert_growth_stage_log(
            log_id=log_id,
            block_id=block_id,
            block_crop_id=target_block_crop_id,
            stage=stage,
            source=source,
            confirmed_by=actor_user_id if source == "manual" else None,
            transition_date=transition_date,
            notes=notes,
            actor_user_id=actor_user_id,
        )
        # Mirror the new stage onto block_crops if there's an assignment
        # to mirror it on. The log is the source of truth; the column
        # is the cached "current" for fast block-detail render.
        if target_block_crop_id is not None:
            await self._repo.update_block_crop_growth_stage(
                block_crop_id=target_block_crop_id,
                stage=stage,
                transition_date=when,
                actor_user_id=actor_user_id,
            )
        await self._tenant_session.flush()

        block = await self._repo.get_block_by_id(block_id, with_boundary=False)
        farm_id = block["farm_id"] if block else None
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.growth_stage_recorded",
            actor_user_id=actor_user_id,
            subject_kind="growth_stage_log",
            subject_id=log_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "stage": stage,
                "source": source,
                "block_crop_id": (
                    str(target_block_crop_id) if target_block_crop_id is not None else None
                ),
            },
            correlation_id=correlation_id,
        )
        return log

    async def list_growth_stage_logs(self, *, block_id: UUID) -> list[dict[str, Any]]:
        # Block-existence check up front so callers see a 404 instead
        # of an empty list when the block is missing.
        if (await self._repo.get_block_by_id(block_id, with_boundary=False)) is None:
            raise BlockNotFoundError(block_id)
        return await self._repo.list_growth_stage_logs(block_id=block_id)

    # ---- Members ----------------------------------------------------

    async def assign_member(
        self,
        *,
        farm_id: UUID,
        membership_id: UUID,
        role: str,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        await self._repo.assert_membership_in_tenant(
            membership_id=membership_id, tenant_id=tenant_id
        )
        result = await self._repo.assign_farm_member(
            membership_id=membership_id,
            farm_id=farm_id,
            role=role,
            actor_user_id=actor_user_id,
        )
        await self._public_session.flush()

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_member_assigned",
            actor_user_id=actor_user_id,
            subject_kind="farm_scope",
            subject_id=result["id"],
            farm_id=farm_id,
            details={
                "membership_id": str(membership_id),
                "role": role,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmMemberAssignedV1(
                farm_scope_id=result["id"],
                membership_id=membership_id,
                farm_id=farm_id,
                role=role,
                actor_user_id=actor_user_id,
            )
        )
        return result

    async def revoke_member(
        self,
        *,
        farm_id: UUID,
        farm_scope_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        result = await self._repo.revoke_farm_member(
            farm_scope_id=farm_scope_id,
            farm_id=farm_id,
            actor_user_id=actor_user_id,
        )
        await self._public_session.flush()

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_member_revoked",
            actor_user_id=actor_user_id,
            subject_kind="farm_scope",
            subject_id=farm_scope_id,
            farm_id=farm_id,
            details={"membership_id": str(result["membership_id"])},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmMemberRevokedV1(
                farm_scope_id=farm_scope_id,
                membership_id=result["membership_id"],
                farm_id=farm_id,
                actor_user_id=actor_user_id,
            )
        )
        return result

    async def list_members(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        # Verify farm exists in this tenant first — otherwise a caller
        # could probe `public.farm_scopes` for arbitrary farm_ids.
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)
        return await self._repo.list_farm_members(farm_id=farm_id)

    # ---- Attachments -------------------------------------------------

    async def init_farm_attachment_upload(
        self,
        *,
        farm_id: UUID,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)
        attachment_id = uuid7()
        s3_key = build_attachment_key(
            tenant_id=tenant_id,
            owner_kind="farms",
            owner_id=farm_id,
            attachment_id=attachment_id,
            original_filename=original_filename,
        )
        upload = self._storage.presign_upload(
            key=s3_key, content_type=content_type, content_length=size_bytes
        )
        return {
            "attachment_id": attachment_id,
            "s3_key": s3_key,
            "upload_url": upload.url,
            "upload_headers": upload.headers,
            "expires_at": upload.expires_at,
        }

    async def finalize_farm_attachment(
        self,
        *,
        farm_id: UUID,
        attachment_id: UUID,
        s3_key: str,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        head = self._verify_uploaded_object(
            s3_key=s3_key, expected_size=size_bytes, expected_content_type=content_type
        )
        del head  # only use is the missing-object signal

        geo_ewkt = _geo_point_to_ewkt(geo_point)
        row = await self._repo.insert_farm_attachment(
            attachment_id=attachment_id,
            farm_id=farm_id,
            kind=kind,
            s3_key=s3_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            caption=caption,
            taken_at=taken_at,
            geo_point_ewkt=geo_ewkt,
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_attachment_uploaded",
            actor_user_id=actor_user_id,
            subject_kind="farm_attachment",
            subject_id=attachment_id,
            farm_id=farm_id,
            details={
                "kind": kind,
                "size_bytes": size_bytes,
                "content_type": content_type,
                "original_filename": original_filename,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmAttachmentUploadedV1(
                attachment_id=attachment_id,
                farm_id=farm_id,
                kind=kind,
                size_bytes=size_bytes,
                content_type=content_type,
                actor_user_id=actor_user_id,
            )
        )
        return self._stamp_download_url(row)

    async def list_farm_attachments(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)
        rows = await self._repo.list_farm_attachments(farm_id=farm_id)
        return [self._stamp_download_url(r) for r in rows]

    async def delete_farm_attachment(
        self,
        *,
        attachment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        existing = await self._repo.get_farm_attachment(attachment_id=attachment_id)
        if existing is None:
            from app.modules.farms.errors import (
                FarmAttachmentNotFoundError,  # local import — see errors.py
            )

            raise FarmAttachmentNotFoundError(attachment_id)
        deleted = await self._repo.soft_delete_farm_attachment(
            attachment_id=attachment_id, actor_user_id=actor_user_id
        )
        if not deleted:
            from app.modules.farms.errors import FarmAttachmentNotFoundError

            raise FarmAttachmentNotFoundError(attachment_id)
        # Best-effort: remove the S3 object. If it never existed we don't
        # care; audit still gets the row.
        try:
            self._storage.delete_object(key=existing["s3_key"])
        except StorageObjectMissingError:
            self._log.info(
                "farm_attachment.s3_object_missing_on_delete",
                attachment_id=str(attachment_id),
                s3_key=existing["s3_key"],
            )

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_attachment_deleted",
            actor_user_id=actor_user_id,
            subject_kind="farm_attachment",
            subject_id=attachment_id,
            farm_id=existing["owner_id"],
            details={"s3_key": existing["s3_key"]},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmAttachmentDeletedV1(
                attachment_id=attachment_id,
                farm_id=existing["owner_id"],
                actor_user_id=actor_user_id,
            )
        )

    async def init_block_attachment_upload(
        self,
        *,
        block_id: UUID,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        block = await self._repo.get_block_by_id(block_id)
        if block is None:
            raise BlockNotFoundError(block_id)
        attachment_id = uuid7()
        s3_key = build_attachment_key(
            tenant_id=tenant_id,
            owner_kind="blocks",
            owner_id=block_id,
            attachment_id=attachment_id,
            original_filename=original_filename,
        )
        upload = self._storage.presign_upload(
            key=s3_key, content_type=content_type, content_length=size_bytes
        )
        return {
            "attachment_id": attachment_id,
            "s3_key": s3_key,
            "upload_url": upload.url,
            "upload_headers": upload.headers,
            "expires_at": upload.expires_at,
        }

    async def finalize_block_attachment(
        self,
        *,
        block_id: UUID,
        attachment_id: UUID,
        s3_key: str,
        kind: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point: dict[str, Any] | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        self._verify_uploaded_object(
            s3_key=s3_key, expected_size=size_bytes, expected_content_type=content_type
        )
        geo_ewkt = _geo_point_to_ewkt(geo_point)
        row = await self._repo.insert_block_attachment(
            attachment_id=attachment_id,
            block_id=block_id,
            kind=kind,
            s3_key=s3_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            caption=caption,
            taken_at=taken_at,
            geo_point_ewkt=geo_ewkt,
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()

        # Block-attachment audits also carry the parent farm_id so audit
        # filtering by farm picks them up.
        block_meta = await self._repo.get_block_by_id(block_id)
        farm_id = block_meta["farm_id"] if block_meta else None

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_attachment_uploaded",
            actor_user_id=actor_user_id,
            subject_kind="block_attachment",
            subject_id=attachment_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "kind": kind,
                "size_bytes": size_bytes,
                "content_type": content_type,
                "original_filename": original_filename,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockAttachmentUploadedV1(
                attachment_id=attachment_id,
                block_id=block_id,
                kind=kind,
                size_bytes=size_bytes,
                content_type=content_type,
                actor_user_id=actor_user_id,
            )
        )
        return self._stamp_download_url(row)

    async def list_block_attachments(self, *, block_id: UUID) -> list[dict[str, Any]]:
        if (await self._repo.get_block_by_id(block_id)) is None:
            raise BlockNotFoundError(block_id)
        rows = await self._repo.list_block_attachments(block_id=block_id)
        return [self._stamp_download_url(r) for r in rows]

    async def delete_block_attachment(
        self,
        *,
        attachment_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        existing = await self._repo.get_block_attachment(attachment_id=attachment_id)
        if existing is None:
            from app.modules.farms.errors import BlockAttachmentNotFoundError

            raise BlockAttachmentNotFoundError(attachment_id)
        deleted = await self._repo.soft_delete_block_attachment(
            attachment_id=attachment_id, actor_user_id=actor_user_id
        )
        if not deleted:
            from app.modules.farms.errors import BlockAttachmentNotFoundError

            raise BlockAttachmentNotFoundError(attachment_id)
        try:
            self._storage.delete_object(key=existing["s3_key"])
        except StorageObjectMissingError:
            self._log.info(
                "block_attachment.s3_object_missing_on_delete",
                attachment_id=str(attachment_id),
                s3_key=existing["s3_key"],
            )

        block_meta = await self._repo.get_block_by_id(existing["owner_id"])
        farm_id = block_meta["farm_id"] if block_meta else None

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_attachment_deleted",
            actor_user_id=actor_user_id,
            subject_kind="block_attachment",
            subject_id=attachment_id,
            farm_id=farm_id,
            details={"s3_key": existing["s3_key"], "block_id": str(existing["owner_id"])},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockAttachmentDeletedV1(
                attachment_id=attachment_id,
                block_id=existing["owner_id"],
                actor_user_id=actor_user_id,
            )
        )

    # ---- Internal helpers --------------------------------------------

    def _verify_uploaded_object(
        self, *, s3_key: str, expected_size: int, expected_content_type: str
    ) -> dict[str, Any]:
        try:
            head = self._storage.head_object(key=s3_key)
        except StorageObjectMissingError as exc:
            from app.modules.farms.errors import AttachmentUploadMissingError

            raise AttachmentUploadMissingError(s3_key) from exc
        actual_size = int(head.get("ContentLength", 0))
        actual_ct = str(head.get("ContentType", ""))
        if actual_size != expected_size or actual_ct.lower() != expected_content_type.lower():
            from app.modules.farms.errors import AttachmentUploadMismatchError

            raise AttachmentUploadMismatchError(
                s3_key=s3_key,
                expected_size=expected_size,
                actual_size=actual_size,
                expected_content_type=expected_content_type,
                actual_content_type=actual_ct,
            )
        return head

    def _stamp_download_url(self, row: dict[str, Any]) -> dict[str, Any]:
        presigned: PresignedDownload = self._storage.presign_download(key=row["s3_key"])
        out = dict(row)
        out["download_url"] = presigned.url
        out["download_url_expires_at"] = presigned.expires_at
        return out

    async def list_crops(self, *, category: str | None = None) -> list[dict[str, Any]]:
        return await self._repo.list_crops(category=category)

    async def list_crop_varieties(self, *, crop_id: UUID) -> list[dict[str, Any]]:
        return await self._repo.list_crop_varieties(crop_id=crop_id)


def _geo_point_to_ewkt(geo_point: dict[str, Any] | None) -> str | None:
    if geo_point is None:
        return None
    coords = geo_point.get("coordinates") or [0.0, 0.0]
    lon = float(coords[0])
    lat = float(coords[1])
    return f"SRID=4326;POINT({lon} {lat})"


def get_farm_service(
    *,
    tenant_session: AsyncSession,
    public_session: AsyncSession,
    audit_service: AuditService | None = None,
    event_bus: EventBus | None = None,
    storage_client: StorageClient | None = None,
) -> FarmService:
    """Factory used by routers and Celery tasks."""
    return FarmServiceImpl(
        tenant_session=tenant_session,
        public_session=public_session,
        audit_service=audit_service,
        event_bus=event_bus,
        storage_client=storage_client,
    )
