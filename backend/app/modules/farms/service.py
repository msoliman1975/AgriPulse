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
from app.modules.farms.crop_thresholds import (
    resolve_phenology_stages,
    resolve_size_classes,
)
from app.modules.farms.errors import (
    BlockNotFoundError,
    CountryCodeConflictError,
    CountryNotFoundError,
    CropAssignmentNotFoundError,
    CropCatalogConflictError,
    CropCatalogValidationError,
    CropNotFoundError,
    CropStrainNotFoundError,
    CropVarietyNotFoundError,
    FarmNotFoundError,
    InvalidUnitTypeError,
    UnknownCountryCodeError,
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
from app.modules.farms.phenology import (
    validate_phenology_payload,
    validate_size_classes_payload,
)
from app.modules.farms.phenology_advance import needs_gdd, stage_for_date
from app.modules.farms.repository import FarmsRepository
from app.modules.weather.snapshot import load_gdd_since
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus
from app.shared.keycloak.client import KeycloakAdminClient, get_keycloak_client
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


def _bulk_err(index: int, code: str, error_code: str, message: str) -> dict[str, Any]:
    """Build an error result row for the bulk-block reconcile."""
    return {
        "index": index,
        "code": code,
        "status": "error",
        "error_code": error_code,
        "message": message,
    }


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
        country_code: str | None,
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
        farm_ids: list[UUID] | None = None,
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
        agronomist_membership_id: UUID | None,
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

    async def reconcile_blocks_bulk(
        self,
        *,
        farm_id: UUID,
        items: list[dict[str, Any]],
        allow_replace: bool,
        can_replace: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
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
        include_boundary: bool = False,
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

    async def auto_grid(
        self, *, farm_id: UUID, cell_size_m: int, max_area_m2: float | None = None
    ) -> dict[str, Any]: ...

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
        crop_variety_strain_id: UUID | None = None,
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
        canopy_size_class: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]: ...

    async def update_block_crop(
        self,
        *,
        block_id: UUID,
        block_crop_id: UUID,
        fields: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...

    async def list_block_crops(self, *, block_id: UUID) -> list[dict[str, Any]]: ...

    async def advance_growth_stages(self, *, tenant_schema: str) -> dict[str, int]: ...

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

    async def list_countries(self) -> list[dict[str, Any]]: ...

    async def list_countries_admin(self, *, include_inactive: bool) -> list[dict[str, Any]]: ...

    async def create_country(
        self, *, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...

    async def update_country(
        self, *, country_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...

    async def list_crops(self, *, category: str | None = None) -> list[dict[str, Any]]: ...

    async def list_crop_varieties(self, *, crop_id: UUID) -> list[dict[str, Any]]: ...

    async def list_variety_strains(self, *, crop_variety_id: UUID) -> list[dict[str, Any]]: ...

    async def get_resolved_taxonomy(self, *, crop_path: str) -> dict[str, Any]: ...

    # ---- Crop catalog authoring (platform-only) -----------------------

    async def list_crops_admin(self, *, include_inactive: bool) -> list[dict[str, Any]]: ...

    async def list_crop_varieties_admin(
        self, *, crop_id: UUID, include_inactive: bool
    ) -> list[dict[str, Any]]: ...

    async def list_variety_strains_admin(
        self, *, crop_variety_id: UUID, include_inactive: bool
    ) -> list[dict[str, Any]]: ...

    async def create_crop(
        self, *, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...

    async def update_crop(
        self, *, crop_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...

    async def create_variety(
        self,
        *,
        crop_id: UUID,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]: ...

    async def update_variety(
        self, *, variety_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...

    async def create_strain(
        self,
        *,
        crop_variety_id: UUID,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]: ...

    async def update_strain(
        self, *, strain_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]: ...


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
        keycloak_client: KeycloakAdminClient | None = None,
    ) -> None:
        self._tenant_session = tenant_session
        self._public_session = public_session
        self._repo = FarmsRepository(tenant_session, public_session=public_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._storage = storage_client or get_storage_client()
        self._kc = keycloak_client or get_keycloak_client()
        self._log = get_logger(__name__)

    async def _sync_member_scopes_to_kc(self, *, membership_id: UUID) -> None:
        """Re-project a membership's active farm scopes into Keycloak so they
        reach the JWT (`farm_scopes` claim) and the auth middleware grants
        farm-scoped capabilities. Best-effort: a Keycloak hiccup must not fail
        the grant/revoke — it is logged and the next sync / reconcile recovers.
        """
        try:
            kc_subject, scopes = await self._repo.get_membership_farm_scopes_for_kc(
                membership_id=membership_id
            )
            if not kc_subject or kc_subject.startswith("pending::"):
                return
            await self._kc.set_farm_scopes(keycloak_user_id=kc_subject, scopes=scopes)
        except Exception as exc:  # best-effort sync, never fatal
            self._log.warning(
                "farm_scopes_keycloak_sync_failed",
                membership_id=str(membership_id),
                error=str(exc),
            )

    # ---- Farms ------------------------------------------------------

    async def _attach_farm_managers(self, farms: list[dict[str, Any]]) -> None:
        """Populate each farm dict's derived, read-only ``farm_manager``.

        U-4a replaced the stored ``farm_manager_id`` column with this
        derivation (the active FarmManager farm-scope holder, earliest
        grant). One batched cross-schema query for the whole list.
        """
        if not farms:
            return
        managers = await self._repo.farm_managers_for(farm_ids=[f["id"] for f in farms])
        for farm in farms:
            farm["farm_manager"] = managers.get(farm["id"])

    async def create_farm(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
        boundary: dict[str, Any],
        elevation_m: Decimal | None,
        country_code: str | None,
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
        await self._ensure_country_code(country_code)

        farm_id = uuid7()
        await self._repo.insert_farm(
            farm_id=farm_id,
            code=code,
            name=name,
            description=description,
            boundary_ewkt=ewkt,
            elevation_m=elevation_m,
            country_code=country_code,
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
        # A just-created farm has no FarmManager scope yet.
        farm["farm_manager"] = None
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
        farm_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_farms(
            after=after,
            limit=limit,
            governorate=governorate,
            tag=tag,
            include_inactive=include_inactive,
            farm_ids=farm_ids,
        )
        await self._attach_farm_managers(rows)
        return [_stamp_area_unit(r, preferred_unit) for r in rows]

    async def get_farm(self, *, farm_id: UUID, preferred_unit: str) -> dict[str, Any]:
        farm = await self._repo.get_farm_by_id(farm_id)
        if farm is None:
            raise FarmNotFoundError(farm_id)
        await self._attach_farm_managers([farm])
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
        if "country_code" in changes:
            await self._ensure_country_code(changes["country_code"])

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
        await self._attach_farm_managers([farm])
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
        counts = _cascade.RestoreCounts()
        if restore_blocks:
            inactive_ids = await self._list_inactive_block_ids_for_farm(farm_id)
            for bid in inactive_ids:
                await self._repo.reactivate_block(block_id=bid, actor_user_id=actor_user_id)
                restored += 1
            # Restore the subs the farm cascade turned off on those blocks.
            counts = await _cascade.restore_block_cascade(
                session=self._tenant_session,
                block_ids=inactive_ids,
                actor_user_id=actor_user_id,
            )
        await self._tenant_session.flush()

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.farm_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="farm",
            subject_id=farm_id,
            farm_id=farm_id,
            details={"restored_block_count": restored, **counts.as_dict()},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            FarmReactivatedV1(
                farm_id=farm_id,
                restored_block_count=restored,
                actor_user_id=actor_user_id,
            )
        )
        return {"farm_id": farm_id, "restored_block_count": restored, **counts.as_dict()}

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
        agronomist_membership_id: UUID | None,
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
            agronomist_membership_id=agronomist_membership_id,
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

    async def reconcile_blocks_bulk(
        self,
        *,
        farm_id: UUID,
        items: list[dict[str, Any]],
        allow_replace: bool,
        can_replace: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Reconcile many AOI-derived candidate blocks against a farm.

        Best-effort and per-row: each item is validated and processed
        independently, so one bad row never fails the batch. Identity is the
        block *code*:

          * new code                       -> create
          * code exists, geometry equal    -> reuse (no write)
          * code exists, geometry changed  -> replace the old block: hard-delete
            it when pristine, else soft-inactivate (cascade), then create new.

        A destructive replace only runs when the caller confirmed it
        (``allow_replace``) AND holds the delete capability (``can_replace``);
        otherwise that row is returned as an error, never executed silently.
        Each write is wrapped in a SAVEPOINT so an unexpected DB failure rolls
        back just that row and leaves the batch transaction usable.
        """
        if (await self._repo.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)

        results: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for index, item in enumerate(items):
            results.append(
                await self._reconcile_one_block(
                    farm_id=farm_id,
                    index=index,
                    item=item,
                    seen_codes=seen_codes,
                    allow_replace=allow_replace,
                    can_replace=can_replace,
                    actor_user_id=actor_user_id,
                    tenant_schema=tenant_schema,
                    correlation_id=correlation_id,
                )
            )

        statuses = [r["status"] for r in results]
        return {
            "results": results,
            "created": statuses.count("created"),
            "reused": statuses.count("reused"),
            "replaced": statuses.count("replaced_deleted") + statuses.count("replaced_inactivated"),
            "errors": statuses.count("error"),
        }

    async def _reconcile_one_block(
        self,
        *,
        farm_id: UUID,
        index: int,
        item: dict[str, Any],
        seen_codes: set[str],
        allow_replace: bool,
        can_replace: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None,
    ) -> dict[str, Any]:
        """Process one bulk row → a single result dict. See reconcile_blocks_bulk."""
        # 1) + 2) Validate code and geometry; returns an error row or the EWKT.
        valid = self._validate_bulk_row(index=index, item=item, seen_codes=seen_codes)
        if valid["status"] == "error":
            return valid
        code = valid["code"]
        name = item.get("name")
        boundary = item["boundary"]
        ewkt = valid["ewkt"]

        # 3) Classify by code.
        existing_id = await self._repo.find_active_block_by_code(farm_id=farm_id, code=code)

        # 3a) New code → create.
        if existing_id is None:
            try:
                async with self._tenant_session.begin_nested():
                    block = await self._create_plain_block(
                        farm_id=farm_id,
                        code=code,
                        name=name,
                        boundary=boundary,
                        actor_user_id=actor_user_id,
                        tenant_schema=tenant_schema,
                        correlation_id=correlation_id,
                    )
            except Exception:
                self._log.exception("bulk_block_create_failed", code=code, farm_id=str(farm_id))
                return _bulk_err(index, code, "create_failed", "Could not create block.")
            return {"index": index, "code": code, "status": "created", "block_id": block["id"]}

        # 3b) Code exists with an identical boundary → reuse.
        if await self._repo.block_boundary_equals(block_id=existing_id, boundary_ewkt=ewkt):
            return {
                "index": index,
                "code": code,
                "status": "reused",
                "block_id": existing_id,
                "message": "Matched existing block; unchanged.",
            }

        # 3c) Code exists, geometry changed → destructive replace (gated).
        return await self._replace_existing_block(
            farm_id=farm_id,
            index=index,
            code=code,
            name=name,
            boundary=boundary,
            existing_id=existing_id,
            allow_replace=allow_replace,
            can_replace=can_replace,
            actor_user_id=actor_user_id,
            tenant_schema=tenant_schema,
            correlation_id=correlation_id,
        )

    def _validate_bulk_row(
        self, *, index: int, item: dict[str, Any], seen_codes: set[str]
    ) -> dict[str, Any]:
        """Validate a bulk row's code + geometry.

        Returns ``{"status": "ok", "code", "ewkt"}`` on success, or an error
        result row (``status == "error"``) that flows straight back to the
        client. Mutates ``seen_codes`` to detect duplicates within the batch.
        """
        from app.modules.farms.errors import GeometryInvalidError, GeometryOutOfEgyptError
        from app.modules.farms.schemas import _validate_code

        code = str(item.get("code") or "").strip()
        boundary = item.get("boundary")
        try:
            _validate_code(code)
        except ValueError:
            return _bulk_err(index, code, "invalid_code", "Invalid block code.")
        if code in seen_codes:
            return _bulk_err(index, code, "duplicate_in_batch", "Duplicate code in upload.")
        seen_codes.add(code)

        if not isinstance(boundary, dict):
            return _bulk_err(index, code, "invalid_geometry", "Missing geometry.")
        try:
            _geometry.validate_polygon_geojson(boundary)
            ewkt = _geometry.geojson_to_ewkt_polygon(boundary)
        except GeometryOutOfEgyptError:
            return _bulk_err(index, code, "out_of_egypt", "Geometry is outside Egypt.")
        except (GeometryInvalidError, ValueError, TypeError, KeyError):
            return _bulk_err(index, code, "invalid_geometry", "Invalid geometry.")
        return {"status": "ok", "code": code, "ewkt": ewkt}

    async def _create_plain_block(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str | None,
        boundary: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None,
    ) -> dict[str, Any]:
        """create_block with all optional block metadata left unset — the shape
        a bulk AOI import produces (geometry + code + optional name only)."""
        return await self.create_block(
            farm_id=farm_id,
            code=code,
            name=name,
            boundary=boundary,
            elevation_m=None,
            irrigation_system=None,
            irrigation_source=None,
            soil_texture=None,
            salinity_class=None,
            soil_ph=None,
            agronomist_membership_id=None,
            notes=None,
            tags=[],
            actor_user_id=actor_user_id,
            tenant_schema=tenant_schema,
            preferred_unit="hectare",
            correlation_id=correlation_id,
        )

    async def _replace_existing_block(
        self,
        *,
        farm_id: UUID,
        index: int,
        code: str,
        name: str | None,
        boundary: dict[str, Any],
        existing_id: UUID,
        allow_replace: bool,
        can_replace: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None,
    ) -> dict[str, Any]:
        """Replace a same-code block whose geometry changed. Hard-delete the old
        block when pristine, else soft-inactivate (cascade), then create new.
        Gated on caller confirmation + delete capability."""
        if not can_replace:
            return _bulk_err(index, code, "replace_forbidden", "Not permitted to replace blocks.")
        if not allow_replace:
            return _bulk_err(index, code, "replace_not_confirmed", "Replace not confirmed.")
        try:
            async with self._tenant_session.begin_nested():
                if await self._repo.block_has_dependents(block_id=existing_id):
                    await self.inactivate_block(
                        block_id=existing_id,
                        actor_user_id=actor_user_id,
                        tenant_schema=tenant_schema,
                        reason="Replaced by AOI bulk upload",
                        correlation_id=correlation_id,
                    )
                    status = "replaced_inactivated"
                else:
                    await self._repo.hard_delete_block(block_id=existing_id)
                    status = "replaced_deleted"
                block = await self._create_plain_block(
                    farm_id=farm_id,
                    code=code,
                    name=name,
                    boundary=boundary,
                    actor_user_id=actor_user_id,
                    tenant_schema=tenant_schema,
                    correlation_id=correlation_id,
                )
        except Exception:
            self._log.exception("bulk_block_replace_failed", code=code, farm_id=str(farm_id))
            return _bulk_err(index, code, "replace_failed", "Could not replace block.")
        return {
            "index": index,
            "code": code,
            "status": status,
            "block_id": block["id"],
            "replaced_block_id": existing_id,
        }

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
        include_boundary: bool = False,
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
            with_boundary=include_boundary,
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
        # Reverse the subscription half of the inactivation cascade — restore
        # only the subs this block's cascade turned off (migration 0049).
        counts = await _cascade.restore_block_cascade(
            session=self._tenant_session,
            block_ids=[block_id],
            actor_user_id=actor_user_id,
        )
        await self._tenant_session.flush()
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_reactivated",
            actor_user_id=actor_user_id,
            subject_kind="block",
            subject_id=block_id,
            farm_id=farm_id,
            details={**counts.as_dict()},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            BlockReactivatedV1(block_id=block_id, farm_id=farm_id, actor_user_id=actor_user_id)
        )
        return {"block_id": block_id, "farm_id": farm_id, **counts.as_dict()}

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
            agronomist_membership_id=None,
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
                agronomist_membership_id=None,
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

    async def auto_grid(
        self, *, farm_id: UUID, cell_size_m: int, max_area_m2: float | None = None
    ) -> dict[str, Any]:
        farm = await self._repo.get_farm_by_id(farm_id, with_boundary=True)
        if farm is None:
            raise FarmNotFoundError(farm_id)

        # A per-block area cap takes precedence: a full interior cell is the
        # largest block, so the cap maps to a square cell of side √area.
        if max_area_m2 is not None:
            cell_size_m = _auto_grid.cell_size_for_max_area_m2(max_area_m2)

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
        crop_variety_strain_id: UUID | None = None,
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
        canopy_size_class: str | None = None,
        correlation_id: UUID | None = None,
    ) -> dict[str, Any]:
        if canopy_size_class is not None:
            await self._validate_canopy_size_class(
                canopy_size_class,
                crop_id=crop_id,
                crop_variety_id=crop_variety_id,
                crop_variety_strain_id=crop_variety_strain_id,
            )
        bc_id = uuid7()
        result = await self._repo.insert_block_crop(
            block_crop_id=bc_id,
            block_id=block_id,
            crop_id=crop_id,
            crop_variety_id=crop_variety_id,
            crop_variety_strain_id=crop_variety_strain_id,
            season_label=season_label,
            planting_date=planting_date,
            expected_harvest_start=expected_harvest_start,
            expected_harvest_end=expected_harvest_end,
            plant_density_per_ha=plant_density_per_ha,
            row_spacing_m=row_spacing_m,
            plant_spacing_m=plant_spacing_m,
            canopy_size_class=canopy_size_class,
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

    async def _resolve_size_class_codes(
        self,
        *,
        crop_id: UUID,
        crop_variety_id: UUID | None,
        crop_variety_strain_id: UUID | None,
    ) -> set[str]:
        crop = await self._repo.get_crop(crop_id=crop_id)
        variety = (
            await self._repo.get_variety(variety_id=crop_variety_id)
            if crop_variety_id is not None
            else None
        )
        strain = (
            await self._repo.get_strain(strain_id=crop_variety_strain_id)
            if crop_variety_strain_id is not None
            else None
        )
        resolved = resolve_size_classes(
            crop_classes=crop.size_classes if crop else None,
            variety_override=variety.size_classes_override if variety else None,
            strain_override=strain.size_classes_override if strain else None,
        )
        if not resolved:
            return set()
        return {c.get("code") for c in resolved.get("classes", [])}

    async def _validate_canopy_size_class(
        self,
        value: str,
        *,
        crop_id: UUID,
        crop_variety_id: UUID | None,
        crop_variety_strain_id: UUID | None,
    ) -> None:
        codes = await self._resolve_size_class_codes(
            crop_id=crop_id,
            crop_variety_id=crop_variety_id,
            crop_variety_strain_id=crop_variety_strain_id,
        )
        if value not in codes:
            raise CropCatalogValidationError(
                reason=(
                    f"canopy_size_class {value!r} is not a valid size class for this crop "
                    f"(allowed: {sorted(codes)})"
                )
            )

    async def update_block_crop(
        self,
        *,
        block_id: UUID,
        block_crop_id: UUID,
        fields: dict[str, Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        bc = await self._repo.get_block_crop(block_crop_id=block_crop_id)
        if bc is None or bc.block_id != block_id:
            raise CropAssignmentNotFoundError(block_crop_id)
        if fields.get("canopy_size_class") is not None:
            await self._validate_canopy_size_class(
                fields["canopy_size_class"],
                crop_id=bc.crop_id,
                crop_variety_id=bc.crop_variety_id,
                crop_variety_strain_id=bc.crop_variety_strain_id,
            )
        result = await self._repo.update_block_crop(
            bc=bc, fields=fields, actor_user_id=actor_user_id
        )
        block = await self._repo.get_block_by_id(block_id, with_boundary=False)
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="farms.block_crop_updated",
            actor_user_id=actor_user_id,
            subject_kind="block_crop",
            subject_id=block_crop_id,
            farm_id=block["farm_id"] if block else None,
            details={"fields": sorted(fields.keys())},
        )
        return result

    async def list_block_crops(self, *, block_id: UUID) -> list[dict[str, Any]]:
        return await self._repo.list_block_crops(block_id=block_id)

    async def advance_growth_stages(self, *, tenant_schema: str) -> dict[str, int]:
        """Move every eligible block to its calendar/age-derived phenology
        stage, writing a ``source='derived'`` GrowthStageLog row when it
        changes. Locked blocks are excluded by the repo query. Idempotent:
        a block already on its computed stage is a no-op.
        """
        candidates = await self._repo.list_block_crops_for_advance()
        today = _date.today()
        evaluated = 0
        advanced = 0
        no_stages = 0
        # GDD is a farm-level series, so blocks on the same farm planted on
        # the same day share an answer. Only crops that actually declare a
        # `gdd_from_planting` stage pay for the lookup at all.
        gdd_cache: dict[tuple[UUID, _date], Decimal | None] = {}
        farm_by_block: dict[UUID, UUID] | None = None
        for bc in candidates:
            evaluated += 1
            crop, variety, strain = await self._repo.resolve_taxonomy_by_path(
                crop_path=bc.crop_path
            )
            if crop is None:
                no_stages += 1
                continue
            resolved = resolve_phenology_stages(
                crop_stages=crop.phenology_stages,
                variety_override=variety.phenology_stages_override if variety else None,
                strain_override=strain.phenology_stages_override if strain else None,
            )
            stages = (resolved or {}).get("stages") or []
            if not stages:
                no_stages += 1
                continue
            gdd_cumulative: float | None = None
            if needs_gdd(stages) and bc.planting_date is not None and not crop.is_perennial:
                if farm_by_block is None:
                    farm_by_block = await self._repo.map_blocks_to_farms(
                        [c.block_id for c in candidates]
                    )
                farm_id = farm_by_block.get(bc.block_id)
                if farm_id is not None:
                    key = (farm_id, bc.planting_date)
                    if key not in gdd_cache:
                        gdd_cache[key] = await load_gdd_since(
                            self._tenant_session,
                            farm_id=farm_id,
                            since=bc.planting_date,
                            until=today,
                        )
                    total = gdd_cache[key]
                    gdd_cumulative = None if total is None else float(total)
            target = stage_for_date(
                stages,
                is_perennial=crop.is_perennial,
                planting_date=bc.planting_date,
                today=today,
                gdd_cumulative=gdd_cumulative,
            )
            if target is None or target == bc.growth_stage:
                continue
            await self.record_growth_stage_transition(
                block_id=bc.block_id,
                stage=target,
                source="derived",
                transition_date=None,
                block_crop_id=bc.id,
                notes="auto-advanced by phenology task",
                actor_user_id=None,
                tenant_schema=tenant_schema,
            )
            advanced += 1
        self._log.info(
            "phenology_advance_done",
            tenant_schema=tenant_schema,
            evaluated=evaluated,
            advanced=advanced,
            no_stages=no_stages,
        )
        return {"evaluated": evaluated, "advanced": advanced, "no_stages": no_stages}

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
        await self._sync_member_scopes_to_kc(membership_id=membership_id)

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
        await self._sync_member_scopes_to_kc(membership_id=result["membership_id"])

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

    # ---- Country catalog ----------------------------------------------

    async def _ensure_country_code(self, code: str | None) -> None:
        """Validate a farm's ``country_code`` against the active catalog.

        ``None`` is allowed (a farm need not declare a country). A non-null
        code must resolve to an active ``public.countries`` row, else 422.
        """
        if code is None:
            return
        if not await self._repo.country_code_exists(code=code, active_only=True):
            raise UnknownCountryCodeError(code)

    async def list_countries(self) -> list[dict[str, Any]]:
        return await self._repo.list_countries()

    async def list_countries_admin(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        return await self._repo.list_countries(include_inactive=include_inactive)

    async def create_country(
        self, *, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        code = fields["code"]
        if await self._repo.country_code_exists(code=code):
            raise CountryCodeConflictError(code)
        out = await self._repo.create_country(fields=fields)
        await self._audit_catalog(
            event_type="farms.country_created",
            subject_kind="country",
            subject_id=out["id"],
            actor_user_id=actor_user_id,
            details={"code": code},
        )
        return out

    async def update_country(
        self, *, country_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        country = await self._repo.get_country(country_id=country_id)
        if country is None:
            raise CountryNotFoundError(country_id)
        out = await self._repo.update_country(country=country, fields=fields)
        await self._audit_catalog(
            event_type="farms.country_updated",
            subject_kind="country",
            subject_id=country_id,
            actor_user_id=actor_user_id,
            details={"fields": sorted(fields.keys())},
        )
        return out

    async def list_crops(self, *, category: str | None = None) -> list[dict[str, Any]]:
        return await self._repo.list_crops(category=category)

    async def list_crop_varieties(self, *, crop_id: UUID) -> list[dict[str, Any]]:
        return await self._repo.list_crop_varieties(crop_id=crop_id)

    async def list_variety_strains(self, *, crop_variety_id: UUID) -> list[dict[str, Any]]:
        return await self._repo.list_variety_strains(crop_variety_id=crop_variety_id)

    async def get_resolved_taxonomy(self, *, crop_path: str) -> dict[str, Any]:
        """Resolve phenology + size classes (deepest-wins) for a crop path.

        ``crop_path`` is ``<crop>`` / ``<crop>.<variety>`` /
        ``<crop>.<variety>.<strain>``. Missing levels just don't contribute
        an override. Raises ``CropNotFoundError`` if the crop segment is
        unknown.
        """
        crop, variety, strain = await self._repo.resolve_taxonomy_by_path(crop_path=crop_path)
        if crop is None:
            raise CropNotFoundError(crop_path)  # type: ignore[arg-type]
        phenology = resolve_phenology_stages(
            crop_stages=crop.phenology_stages,
            variety_override=variety.phenology_stages_override if variety else None,
            strain_override=strain.phenology_stages_override if strain else None,
        )
        size_classes = resolve_size_classes(
            crop_classes=crop.size_classes,
            variety_override=variety.size_classes_override if variety else None,
            strain_override=strain.size_classes_override if strain else None,
        )
        return {
            "crop_path": crop_path,
            "phenology_stages": phenology,
            "size_classes": size_classes,
        }

    # ---- Crop catalog authoring (platform-only) -----------------------

    async def _audit_catalog(
        self,
        *,
        event_type: str,
        subject_kind: str,
        subject_id: UUID,
        actor_user_id: UUID | None,
        details: dict[str, Any],
    ) -> None:
        await self._audit.record(
            tenant_schema=None,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind=subject_kind,
            subject_id=subject_id,
            farm_id=None,
            details=details,
        )

    async def list_crops_admin(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        return await self._repo.list_crops(include_inactive=include_inactive)

    async def list_crop_varieties_admin(
        self, *, crop_id: UUID, include_inactive: bool
    ) -> list[dict[str, Any]]:
        if await self._repo.get_crop(crop_id=crop_id) is None:
            raise CropNotFoundError(crop_id)
        return await self._repo.list_crop_varieties(
            crop_id=crop_id, include_inactive=include_inactive
        )

    async def list_variety_strains_admin(
        self, *, crop_variety_id: UUID, include_inactive: bool
    ) -> list[dict[str, Any]]:
        if await self._repo.get_variety(variety_id=crop_variety_id) is None:
            raise CropVarietyNotFoundError(crop_variety_id)
        return await self._repo.list_variety_strains(
            crop_variety_id=crop_variety_id, include_inactive=include_inactive
        )

    async def create_crop(
        self, *, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        code = fields["code"]
        _validate_catalog_payloads(
            phenology=fields.get("phenology_stages"),
            size_classes=fields.get("size_classes"),
            is_perennial=bool(fields.get("is_perennial", False)),
            has_gdd_base=fields.get("gdd_base_temp_c") is not None,
        )
        if await self._repo.crop_code_exists(code=code):
            raise CropCatalogConflictError(level="crop", code=code)
        out = await self._repo.create_crop(fields=fields)
        await self._audit_catalog(
            event_type="farms.crop_created",
            subject_kind="crop",
            subject_id=out["id"],
            actor_user_id=actor_user_id,
            details={"code": code},
        )
        return out

    async def update_crop(
        self, *, crop_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        crop = await self._repo.get_crop(crop_id=crop_id)
        if crop is None:
            raise CropNotFoundError(crop_id)
        is_perennial = fields.get("is_perennial", crop.is_perennial)
        gdd_base = fields.get("gdd_base_temp_c", crop.gdd_base_temp_c)
        _validate_catalog_payloads(
            phenology=fields.get("phenology_stages"),
            size_classes=fields.get("size_classes"),
            is_perennial=bool(is_perennial),
            has_gdd_base=gdd_base is not None,
        )
        out = await self._repo.update_crop(crop=crop, fields=fields)
        await self._audit_catalog(
            event_type="farms.crop_updated",
            subject_kind="crop",
            subject_id=crop_id,
            actor_user_id=actor_user_id,
            details={"fields": sorted(fields.keys())},
        )
        return out

    async def create_variety(
        self,
        *,
        crop_id: UUID,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        crop = await self._repo.get_crop(crop_id=crop_id)
        if crop is None:
            raise CropNotFoundError(crop_id)
        overrides = overrides or {}
        _validate_catalog_payloads(
            phenology=overrides.get("phenology_stages_override"),
            size_classes=overrides.get("size_classes_override"),
            is_perennial=crop.is_perennial,
            has_gdd_base=crop.gdd_base_temp_c is not None,
        )
        if await self._repo.variety_code_exists(crop_id=crop_id, code=code):
            raise CropCatalogConflictError(level="variety", code=code)
        out = await self._repo.create_variety(
            crop_id=crop_id,
            crop_code=crop.code,
            code=code,
            name_en=name_en,
            name_ar=name_ar,
            overrides=overrides,
        )
        await self._audit_catalog(
            event_type="farms.crop_variety_created",
            subject_kind="crop_variety",
            subject_id=out["id"],
            actor_user_id=actor_user_id,
            details={"path": out["path"]},
        )
        return out

    async def update_variety(
        self, *, variety_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        variety = await self._repo.get_variety(variety_id=variety_id)
        if variety is None:
            raise CropVarietyNotFoundError(variety_id)
        crop = await self._repo.get_crop(crop_id=variety.crop_id)
        _validate_catalog_payloads(
            phenology=fields.get("phenology_stages_override"),
            size_classes=fields.get("size_classes_override"),
            is_perennial=bool(crop.is_perennial) if crop else False,
            has_gdd_base=crop.gdd_base_temp_c is not None if crop else False,
        )
        out = await self._repo.update_variety(variety=variety, fields=fields)
        await self._audit_catalog(
            event_type="farms.crop_variety_updated",
            subject_kind="crop_variety",
            subject_id=variety_id,
            actor_user_id=actor_user_id,
            details={"fields": sorted(fields.keys())},
        )
        return out

    async def create_strain(
        self,
        *,
        crop_variety_id: UUID,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        variety = await self._repo.get_variety(variety_id=crop_variety_id)
        if variety is None:
            raise CropVarietyNotFoundError(crop_variety_id)
        overrides = overrides or {}
        crop = await self._repo.get_crop(crop_id=variety.crop_id)
        _validate_catalog_payloads(
            phenology=overrides.get("phenology_stages_override"),
            size_classes=overrides.get("size_classes_override"),
            is_perennial=bool(crop.is_perennial) if crop else False,
            has_gdd_base=crop.gdd_base_temp_c is not None if crop else False,
        )
        if await self._repo.strain_code_exists(crop_variety_id=crop_variety_id, code=code):
            raise CropCatalogConflictError(level="strain", code=code)
        out = await self._repo.create_strain(
            crop_variety_id=crop_variety_id,
            variety_path=variety.path,
            code=code,
            name_en=name_en,
            name_ar=name_ar,
            overrides=overrides,
        )
        await self._audit_catalog(
            event_type="farms.crop_strain_created",
            subject_kind="crop_variety_strain",
            subject_id=out["id"],
            actor_user_id=actor_user_id,
            details={"path": out["path"]},
        )
        return out

    async def update_strain(
        self, *, strain_id: UUID, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        strain = await self._repo.get_strain(strain_id=strain_id)
        if strain is None:
            raise CropStrainNotFoundError(strain_id)
        variety = await self._repo.get_variety(variety_id=strain.crop_variety_id)
        crop = await self._repo.get_crop(crop_id=variety.crop_id) if variety is not None else None
        _validate_catalog_payloads(
            phenology=fields.get("phenology_stages_override"),
            size_classes=fields.get("size_classes_override"),
            is_perennial=bool(crop.is_perennial) if crop else False,
            has_gdd_base=crop.gdd_base_temp_c is not None if crop else False,
        )
        out = await self._repo.update_strain(strain=strain, fields=fields)
        await self._audit_catalog(
            event_type="farms.crop_strain_updated",
            subject_kind="crop_variety_strain",
            subject_id=strain_id,
            actor_user_id=actor_user_id,
            details={"fields": sorted(fields.keys())},
        )
        return out


def _validate_catalog_payloads(
    *,
    phenology: dict[str, Any] | None,
    size_classes: dict[str, Any] | None,
    is_perennial: bool,
    has_gdd_base: bool,
) -> None:
    """Shape-validate phenology + size-class payloads, mapping failures to 422.

    Skips a payload when it is ``None`` (not being set / being cleared).
    """
    try:
        if phenology is not None:
            validate_phenology_payload(
                phenology, is_perennial=is_perennial, has_gdd_base=has_gdd_base
            )
        if size_classes is not None:
            validate_size_classes_payload(size_classes)
    except ValueError as exc:  # pydantic.ValidationError is a ValueError
        raise CropCatalogValidationError(reason=str(exc)) from exc


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
    keycloak_client: KeycloakAdminClient | None = None,
) -> FarmService:
    """Factory used by routers and Celery tasks."""
    return FarmServiceImpl(
        tenant_session=tenant_session,
        public_session=public_session,
        audit_service=audit_service,
        event_bus=event_bus,
        storage_client=storage_client,
        keycloak_client=keycloak_client,
    )
