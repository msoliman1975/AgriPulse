"""Farms service: public Protocol + concrete implementation.

Other modules depend on `FarmService` (the Protocol), never on
`FarmServiceImpl`. The router and tests construct an instance per
request via `get_farm_service`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.farms import auto_grid as _auto_grid
from app.modules.farms import geometry as _geometry
from app.modules.farms.errors import (
    BlockNotFoundError,
    FarmNotFoundError,
)
from app.modules.farms.events import (
    BlockArchivedV1,
    BlockAttachmentDeletedV1,
    BlockAttachmentUploadedV1,
    BlockBoundaryChangedV1,
    BlockCreatedV1,
    BlockCropAssignedV1,
    BlockUpdatedV1,
    FarmArchivedV1,
    FarmAttachmentDeletedV1,
    FarmAttachmentUploadedV1,
    FarmBoundaryChangedV1,
    FarmCreatedV1,
    FarmMemberAssignedV1,
    FarmMemberRevokedV1,
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
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_farms(
        self,
        *,
        after: UUID | None,
        limit: int,
        status_filter: str | None,
        governorate: str | None,
        tag: str | None,
        include_archived: bool,
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

    async def archive_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

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
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def list_blocks(
        self,
        *,
        farm_id: UUID,
        after: UUID | None,
        limit: int,
        status_filter: str | None,
        irrigation_system: str | None,
        include_archived: bool,
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

    async def archive_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

    async def auto_grid(self, *, farm_id: UUID, cell_size_m: int) -> dict[str, Any]: ...

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
        status_filter: str | None,
        governorate: str | None,
        tag: str | None,
        include_archived: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_farms(
            after=after,
            limit=limit,
            status_filter=status_filter,
            governorate=governorate,
            tag=tag,
            include_archived=include_archived,
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

    async def archive_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        await self._repo.archive_farm(farm_id=farm_id, actor_user_id=actor_user_id)
        await self._tenant_session.flush()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_archived",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={},
            correlation_id=correlation_id,
        )
        self._bus.publish(FarmArchivedV1(farm_id=farm_id, actor_user_id=actor_user_id))

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
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        _geometry.validate_polygon_geojson(boundary)
        ewkt = _geometry.geojson_to_ewkt_polygon(boundary)

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

    async def list_blocks(
        self,
        *,
        farm_id: UUID,
        after: UUID | None,
        limit: int,
        status_filter: str | None,
        irrigation_system: str | None,
        include_archived: bool,
        preferred_unit: str,
    ) -> list[dict[str, Any]]:
        # Confirm farm exists; cross-tenant calls return 404 here.
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)

        rows = await self._repo.list_blocks(
            farm_id=farm_id,
            after=after,
            limit=limit,
            status_filter=status_filter,
            irrigation_system=irrigation_system,
            include_archived=include_archived,
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

    async def archive_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        farm_id = await self._repo.archive_block(block_id=block_id, actor_user_id=actor_user_id)
        await self._tenant_session.flush()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_archived",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=farm_id,
            details={},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockArchivedV1(block_id=block_id, farm_id=farm_id, actor_user_id=actor_user_id)
        )

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
