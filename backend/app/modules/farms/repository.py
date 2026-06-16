"""Async DB access for the farms module. Internal to the module.

Geometry I/O uses EWKT through `ST_GeomFromEWKT` — keeps the calls
parameter-bindable without pulling geoalchemy2 WKBElement into the
service layer. Read-side projections back to GeoJSON go through
`ST_AsGeoJSON`, returning a JSON string the repository parses once.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as _date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.modules.farms.errors import (
    BlockCodeConflictError,
    BlockNotFoundError,
    CropNotFoundError,
    CropTaxonomyError,
    FarmCodeConflictError,
    FarmMemberAlreadyAssignedError,
    FarmMembershipMissingError,
    FarmNotFoundError,
)
from app.modules.farms.models import (
    Block,
    BlockAttachment,
    BlockCrop,
    Crop,
    CropVariety,
    CropVarietyStrain,
    Farm,
    FarmAttachment,
    GrowthStageLog,
)

# Allowlists for dynamic UPDATE clauses — every column name interpolated
# into an UPDATE … SET list MUST be in one of these sets. The router only
# forwards Pydantic-declared fields, so this is a defense-in-depth guard
# against future callers passing arbitrary keys into the repository.
_FARM_UPDATABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "elevation_m",
        "governorate",
        "district",
        "nearest_city",
        "address_line",
        "farm_type",
        "ownership_type",
        "primary_water_source",
        "established_date",
        "tags",
    }
)

_BLOCK_UPDATABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "name",
        "elevation_m",
        "irrigation_system",
        "irrigation_source",
        "soil_texture",
        "salinity_class",
        "soil_ph",
        "agronomist_membership_id",
        "notes",
        "tags",
    }
)


# ---- Read projections ------------------------------------------------------


def _is_active_expr_for(active_from: Any, active_to: Any) -> Any:
    """Build a server-side ``is_active`` predicate.

    Mirrors the SQL filter we use everywhere else: a row is active when
    today (Postgres ``current_date``) falls inside ``[active_from,
    active_to)``. Computing this in SQL keeps it in lock-step with the
    column defaults the DB stamped on the row, which avoids a
    timezone-race we hit in user time zones ahead of UTC.
    """
    return case(
        (
            and_(
                active_from <= func.current_date(),
                or_(active_to.is_(None), active_to > func.current_date()),
            ),
            True,
        ),
        else_=False,
    ).label("is_active_computed")


def _row_geom_select_for_farm(*, with_boundary: bool) -> tuple[Any, ...]:
    """Columns to select for a farm row, with geometry as GeoJSON strings.

    Returning the geometry as JSON-text avoids any geoalchemy2 deserializer
    work in the hot path; the repository decodes once at the boundary.
    """
    cols: list[Any] = [
        Farm.id,
        Farm.code,
        Farm.name,
        Farm.description,
        Farm.area_m2,
        Farm.elevation_m,
        Farm.governorate,
        Farm.district,
        Farm.nearest_city,
        Farm.address_line,
        Farm.farm_type,
        Farm.ownership_type,
        Farm.primary_water_source,
        Farm.established_date,
        Farm.tags,
        Farm.active_from,
        Farm.active_to,
        _is_active_expr_for(Farm.active_from, Farm.active_to),
        Farm.created_at,
        Farm.updated_at,
        func.ST_AsGeoJSON(Farm.centroid).label("centroid_geojson"),
    ]
    if with_boundary:
        cols.append(func.ST_AsGeoJSON(Farm.boundary).label("boundary_geojson"))
    return tuple(cols)


def _row_geom_select_for_block(*, with_boundary: bool) -> tuple[Any, ...]:
    cols: list[Any] = [
        Block.id,
        Block.farm_id,
        Block.code,
        Block.name,
        Block.area_m2,
        Block.elevation_m,
        Block.aoi_hash,
        Block.irrigation_system,
        Block.irrigation_source,
        Block.soil_texture,
        Block.salinity_class,
        Block.soil_ph,
        Block.agronomist_membership_id,
        Block.notes,
        Block.tags,
        Block.active_from,
        Block.active_to,
        _is_active_expr_for(Block.active_from, Block.active_to),
        Block.unit_type,
        Block.parent_unit_id,
        Block.irrigation_geometry,
        Block.created_at,
        Block.updated_at,
        func.ST_AsGeoJSON(Block.centroid).label("centroid_geojson"),
    ]
    if with_boundary:
        cols.append(func.ST_AsGeoJSON(Block.boundary).label("boundary_geojson"))
    return tuple(cols)


def _decode_geojson(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


# ---- Repository ------------------------------------------------------------


class FarmsRepository:
    """SQLAlchemy queries for farms / blocks / block_crops / attachments / members.

    Sessions are passed in by the caller; the repository never opens its
    own. `farm_scopes` lookups go to a separate session pinned to public
    (the cross-schema FK is logical — see data_model § 4.6).
    """

    def __init__(self, tenant_session: AsyncSession, *, public_session: AsyncSession) -> None:
        self._tenant = tenant_session
        self._public = public_session

    # ---- Farms -----------------------------------------------------

    async def code_exists(self, code: str) -> bool:
        stmt = select(Farm.id).where(Farm.code == code, Farm.deleted_at.is_(None))
        return (await self._tenant.execute(stmt)).first() is not None

    async def insert_farm(
        self,
        *,
        farm_id: UUID,
        code: str,
        name: str,
        description: str | None,
        boundary_ewkt: str,
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
        active_from: _date | None = None,
    ) -> dict[str, Any]:
        stmt = text(
            """
            INSERT INTO farms (
                id, code, name, description, boundary,
                boundary_utm, centroid, area_m2,
                elevation_m, governorate, district, nearest_city, address_line,
                farm_type, ownership_type, primary_water_source, established_date,
                tags, active_from, created_by, updated_by
            )
            VALUES (
                :id, :code, :name, :description, ST_GeomFromEWKT(:boundary),
                'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry,
                'SRID=4326;POINT(0 0)'::geometry,
                0,
                :elevation_m, :governorate, :district, :nearest_city, :address_line,
                :farm_type, :ownership_type, :primary_water_source, :established_date,
                :tags, COALESCE(:active_from, current_date), :actor, :actor
            )
            RETURNING id, created_at, area_m2
            """
        ).bindparams(
            *(
                _bind_uuid("id"),
                _bind_uuid("actor"),
                _bind_text_array("tags"),
            )
        )
        try:
            result = await self._tenant.execute(
                stmt,
                {
                    "id": farm_id,
                    "code": code,
                    "name": name,
                    "description": description,
                    "boundary": boundary_ewkt,
                    "elevation_m": elevation_m,
                    "governorate": governorate,
                    "district": district,
                    "nearest_city": nearest_city,
                    "address_line": address_line,
                    "farm_type": farm_type,
                    "ownership_type": ownership_type,
                    "primary_water_source": primary_water_source,
                    "established_date": established_date,
                    "tags": tags,
                    "active_from": active_from,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if _is_unique_violation(exc, "uq_farms_code_active"):
                raise FarmCodeConflictError(code) from exc
            raise

        row = result.one()
        return {
            "id": row.id,
            "created_at": row.created_at,
            "area_m2": row.area_m2,
        }

    async def get_farm_by_id(
        self, farm_id: UUID, *, with_boundary: bool = True, include_archived: bool = False
    ) -> dict[str, Any] | None:
        stmt = select(*_row_geom_select_for_farm(with_boundary=with_boundary)).where(
            Farm.id == farm_id
        )
        if not include_archived:
            stmt = stmt.where(Farm.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).first()
        if row is None:
            return None
        return _farm_row_to_dict(row, with_boundary=with_boundary)

    async def list_farms(
        self,
        *,
        after: UUID | None,
        limit: int,
        governorate: str | None,
        tag: str | None,
        include_inactive: bool,
        farm_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(*_row_geom_select_for_farm(with_boundary=False))
        if not include_inactive:
            # Only "currently active" rows: not soft-inactivated AND inside
            # the lifecycle window.
            stmt = stmt.where(
                Farm.deleted_at.is_(None),
                (Farm.active_to.is_(None)) | (Farm.active_to > func.current_date()),
            )
        if farm_ids is not None:
            # SMK-RBAC-GAP-02: restrict to a farm-scoped user's visible farms.
            stmt = stmt.where(Farm.id.in_(farm_ids))
        if governorate:
            stmt = stmt.where(Farm.governorate == governorate)
        if tag:
            # ARRAY contains-element via the @> operator works for text[] columns.
            stmt = stmt.where(Farm.tags.contains([tag]))
        if after is not None:
            stmt = stmt.where(Farm.id > after)
        stmt = stmt.order_by(Farm.id.asc()).limit(limit)
        rows = (await self._tenant.execute(stmt)).all()
        return [_farm_row_to_dict(r, with_boundary=False) for r in rows]

    async def update_farm(
        self,
        *,
        farm_id: UUID,
        changes: dict[str, Any],
        boundary_ewkt: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        if not changes and boundary_ewkt is None:
            current = await self.get_farm_by_id(farm_id)
            if current is None:
                raise FarmNotFoundError(farm_id)
            return current

        invalid_keys = set(changes) - _FARM_UPDATABLE_COLUMNS
        if invalid_keys:
            raise ValueError(f"unsupported farm update keys: {sorted(invalid_keys)}")

        sets: list[str] = []
        params: dict[str, Any] = {"id": farm_id, "actor": actor_user_id}
        for key, value in changes.items():
            sets.append(f"{key} = :{key}")
            params[key] = value
        if boundary_ewkt is not None:
            sets.append("boundary = ST_GeomFromEWKT(:boundary)")
            params["boundary"] = boundary_ewkt
        sets.append("updated_by = :actor")

        # Allowlist constrains every key in `sets` to a known column name;
        # the f-string interpolates only those allowlisted identifiers.
        sql = (
            f"UPDATE farms SET {', '.join(sets)} "  # noqa: S608
            f"WHERE id = :id AND deleted_at IS NULL "
            f"RETURNING id"
        )
        stmt = text(sql).bindparams(_bind_uuid("id"), _bind_uuid("actor"))
        if "tags" in params:
            stmt = stmt.bindparams(_bind_text_array("tags"))

        try:
            result = await self._tenant.execute(stmt, params)
        except IntegrityError as exc:
            raise exc

        if result.first() is None:
            raise FarmNotFoundError(farm_id)
        farm = await self.get_farm_by_id(farm_id)
        if farm is None:  # pragma: no cover — defensive
            raise FarmNotFoundError(farm_id)
        return farm

    async def inactivate_farm(
        self,
        *,
        farm_id: UUID,
        actor_user_id: UUID | None,
        effective_date: _date | None = None,
    ) -> None:
        """Set ``active_to`` (and ``deleted_at`` for back-compat) for the farm.

        Existing callers across the codebase still filter on
        ``deleted_at IS NULL``; we keep that column in lock-step with
        ``active_to`` so they continue to exclude inactivated rows
        without each module having to be touched at once.
        """
        effective = effective_date or datetime.now(UTC).date()
        result = await self._tenant.execute(
            update(Farm)
            .where(and_(Farm.id == farm_id, Farm.deleted_at.is_(None)))
            .values(
                active_to=effective,
                deleted_at=datetime.now(UTC),
                updated_by=actor_user_id,
            )
            .returning(Farm.id)
        )
        if result.first() is None:
            raise FarmNotFoundError(farm_id)

    async def reactivate_farm(self, *, farm_id: UUID, actor_user_id: UUID | None) -> None:
        """Clear ``active_to`` + ``deleted_at`` to bring the farm back."""
        result = await self._tenant.execute(
            update(Farm)
            .where(Farm.id == farm_id, Farm.deleted_at.is_not(None))
            .values(
                active_to=None,
                deleted_at=None,
                updated_by=actor_user_id,
            )
            .returning(Farm.id)
        )
        if result.first() is None:
            raise FarmNotFoundError(farm_id)

    # ---- Blocks ----------------------------------------------------

    async def block_code_exists(self, *, farm_id: UUID, code: str) -> bool:
        stmt = select(Block.id).where(
            Block.farm_id == farm_id,
            Block.code == code,
            Block.deleted_at.is_(None),
        )
        return (await self._tenant.execute(stmt)).first() is not None

    async def insert_block(
        self,
        *,
        block_id: UUID,
        farm_id: UUID,
        code: str,
        name: str | None,
        boundary_ewkt: str,
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
        unit_type: str = "block",
        parent_unit_id: UUID | None = None,
        irrigation_geometry: dict[str, Any] | None = None,
        active_from: _date | None = None,
    ) -> dict[str, Any]:
        # Confirm the farm exists in this tenant first.
        farm_exists = await self._tenant.execute(
            select(Farm.id).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
        if farm_exists.first() is None:
            raise FarmNotFoundError(farm_id)

        sql = text(
            """
            INSERT INTO blocks (
                id, farm_id, code, name, boundary,
                boundary_utm, centroid, area_m2, aoi_hash,
                elevation_m, irrigation_system, irrigation_source,
                soil_texture, salinity_class, soil_ph,
                agronomist_membership_id, notes, tags, active_from,
                unit_type, parent_unit_id, irrigation_geometry,
                created_by, updated_by
            )
            VALUES (
                :id, :farm_id, :code, :name, ST_GeomFromEWKT(:boundary),
                'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry,
                'SRID=4326;POINT(0 0)'::geometry,
                0, '',
                :elevation_m, :irrigation_system, :irrigation_source,
                :soil_texture, :salinity_class, :soil_ph,
                :agronomist_membership_id, :notes, :tags,
                COALESCE(:active_from, current_date),
                :unit_type, :parent_unit_id, CAST(:irrigation_geometry AS jsonb),
                :actor, :actor
            )
            RETURNING id, created_at, area_m2, aoi_hash
            """
        ).bindparams(
            _bind_uuid("id"),
            _bind_uuid("farm_id"),
            _bind_uuid("actor"),
            _bind_uuid("agronomist_membership_id"),
            _bind_uuid("parent_unit_id"),
            _bind_text_array("tags"),
        )
        try:
            result = await self._tenant.execute(
                sql,
                {
                    "id": block_id,
                    "farm_id": farm_id,
                    "code": code,
                    "name": name,
                    "boundary": boundary_ewkt,
                    "elevation_m": elevation_m,
                    "irrigation_system": irrigation_system,
                    "irrigation_source": irrigation_source,
                    "soil_texture": soil_texture,
                    "salinity_class": salinity_class,
                    "soil_ph": soil_ph,
                    "agronomist_membership_id": agronomist_membership_id,
                    "notes": notes,
                    "tags": tags,
                    "unit_type": unit_type,
                    "parent_unit_id": parent_unit_id,
                    "irrigation_geometry": (
                        json.dumps(irrigation_geometry) if irrigation_geometry is not None else None
                    ),
                    "active_from": active_from,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            if _is_unique_violation(exc, "uq_blocks_farm_id_code_active"):
                raise BlockCodeConflictError(farm_id, code) from exc
            raise

        row = result.one()
        return {
            "id": row.id,
            "created_at": row.created_at,
            "area_m2": row.area_m2,
            "aoi_hash": row.aoi_hash,
        }

    async def get_block_by_id(
        self, block_id: UUID, *, with_boundary: bool = True, include_archived: bool = False
    ) -> dict[str, Any] | None:
        stmt = select(*_row_geom_select_for_block(with_boundary=with_boundary)).where(
            Block.id == block_id
        )
        if not include_archived:
            stmt = stmt.where(Block.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).first()
        if row is None:
            return None
        return _block_row_to_dict(row, with_boundary=with_boundary)

    async def list_blocks(
        self,
        *,
        farm_id: UUID,
        after: UUID | None,
        limit: int,
        irrigation_system: str | None,
        include_inactive: bool,
    ) -> list[dict[str, Any]]:
        stmt = select(*_row_geom_select_for_block(with_boundary=False)).where(
            Block.farm_id == farm_id
        )
        if not include_inactive:
            stmt = stmt.where(
                Block.deleted_at.is_(None),
                (Block.active_to.is_(None)) | (Block.active_to > func.current_date()),
            )
        if irrigation_system:
            stmt = stmt.where(Block.irrigation_system == irrigation_system)
        if after is not None:
            stmt = stmt.where(Block.id > after)
        stmt = stmt.order_by(Block.id.asc()).limit(limit)
        rows = (await self._tenant.execute(stmt)).all()
        return [_block_row_to_dict(r, with_boundary=False) for r in rows]

    async def update_block(
        self,
        *,
        block_id: UUID,
        changes: dict[str, Any],
        boundary_ewkt: str | None,
        actor_user_id: UUID | None,
    ) -> tuple[dict[str, Any], str | None]:
        """Return (new_block_dict, prev_aoi_hash if boundary changed else None)."""
        prev_aoi_hash: str | None = None
        if boundary_ewkt is not None:
            cur = await self._tenant.execute(
                select(Block.aoi_hash).where(Block.id == block_id, Block.deleted_at.is_(None))
            )
            row = cur.first()
            if row is None:
                raise BlockNotFoundError(block_id)
            prev_aoi_hash = row.aoi_hash

        invalid_keys = set(changes) - _BLOCK_UPDATABLE_COLUMNS
        if invalid_keys:
            raise ValueError(f"unsupported block update keys: {sorted(invalid_keys)}")

        sets: list[str] = []
        params: dict[str, Any] = {"id": block_id, "actor": actor_user_id}
        for key, value in changes.items():
            sets.append(f"{key} = :{key}")
            params[key] = value
        if boundary_ewkt is not None:
            sets.append("boundary = ST_GeomFromEWKT(:boundary)")
            params["boundary"] = boundary_ewkt
        sets.append("updated_by = :actor")

        if not sets[:-1] and boundary_ewkt is None:
            current = await self.get_block_by_id(block_id)
            if current is None:
                raise BlockNotFoundError(block_id)
            return current, None

        # Allowlist constrains every key in `sets` to a known column name;
        # the f-string interpolates only those allowlisted identifiers.
        sql = (
            f"UPDATE blocks SET {', '.join(sets)} "  # noqa: S608
            f"WHERE id = :id AND deleted_at IS NULL "
            f"RETURNING id"
        )
        stmt = text(sql).bindparams(_bind_uuid("id"), _bind_uuid("actor"))
        if "agronomist_membership_id" in params:
            stmt = stmt.bindparams(_bind_uuid("agronomist_membership_id"))
        if "tags" in params:
            stmt = stmt.bindparams(_bind_text_array("tags"))

        result = await self._tenant.execute(stmt, params)
        if result.first() is None:
            raise BlockNotFoundError(block_id)
        block = await self.get_block_by_id(block_id)
        if block is None:  # pragma: no cover — defensive
            raise BlockNotFoundError(block_id)
        return block, prev_aoi_hash

    async def inactivate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        effective_date: _date | None = None,
    ) -> UUID:
        """Set ``active_to`` (+ ``deleted_at``) and return the parent farm_id."""
        cur = await self._tenant.execute(
            select(Block.farm_id).where(Block.id == block_id, Block.deleted_at.is_(None))
        )
        row = cur.first()
        if row is None:
            raise BlockNotFoundError(block_id)

        effective = effective_date or datetime.now(UTC).date()
        await self._tenant.execute(
            update(Block)
            .where(and_(Block.id == block_id, Block.deleted_at.is_(None)))
            .values(
                active_to=effective,
                deleted_at=datetime.now(UTC),
                updated_by=actor_user_id,
            )
        )
        return row.farm_id

    async def reactivate_block(self, *, block_id: UUID, actor_user_id: UUID | None) -> UUID:
        cur = await self._tenant.execute(
            select(Block.farm_id).where(Block.id == block_id, Block.deleted_at.is_not(None))
        )
        row = cur.first()
        if row is None:
            raise BlockNotFoundError(block_id)
        await self._tenant.execute(
            update(Block)
            .where(Block.id == block_id, Block.deleted_at.is_not(None))
            .values(
                active_to=None,
                deleted_at=None,
                updated_by=actor_user_id,
            )
        )
        return row.farm_id

    async def list_active_block_ids_for_farm(self, *, farm_id: UUID) -> tuple[UUID, ...]:
        """Block IDs under a farm that are still active. Used by the farm-cascade."""
        rows = (
            await self._tenant.execute(
                select(Block.id).where(
                    Block.farm_id == farm_id,
                    Block.deleted_at.is_(None),
                )
            )
        ).all()
        return tuple(r.id for r in rows)

    # ---- Block crops ----------------------------------------------

    async def insert_block_crop(
        self,
        *,
        block_crop_id: UUID,
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
        canopy_size_class: str | None = None,
        growth_stage_locked: bool = False,
    ) -> dict[str, Any]:
        # Confirm block exists.
        block_exists = await self._tenant.execute(
            select(Block.id).where(Block.id == block_id, Block.deleted_at.is_(None))
        )
        if block_exists.first() is None:
            raise BlockNotFoundError(block_id)

        # Confirm crop exists + read its code + classification depth.
        crop_row = (
            await self._public.execute(
                select(Crop.code, Crop.classification_depth).where(
                    Crop.id == crop_id, Crop.is_active.is_(True)
                )
            )
        ).first()
        if crop_row is None:
            raise CropNotFoundError(crop_id)

        # Resolve + validate variety / strain containment, collecting paths.
        variety_path: str | None = None
        if crop_variety_id is not None:
            v_row = (
                await self._public.execute(
                    select(CropVariety.path).where(
                        CropVariety.id == crop_variety_id,
                        CropVariety.crop_id == crop_id,
                        CropVariety.is_active.is_(True),
                    )
                )
            ).first()
            if v_row is None:
                raise CropNotFoundError(crop_variety_id)
            variety_path = v_row.path

        strain_path: str | None = None
        if crop_variety_strain_id is not None:
            if crop_variety_id is None:
                raise CropTaxonomyError(reason="A strain requires a variety.")
            s_row = (
                await self._public.execute(
                    select(CropVarietyStrain.path).where(
                        CropVarietyStrain.id == crop_variety_strain_id,
                        CropVarietyStrain.crop_variety_id == crop_variety_id,
                        CropVarietyStrain.is_active.is_(True),
                    )
                )
            ).first()
            if s_row is None:
                raise CropNotFoundError(crop_variety_strain_id)
            strain_path = s_row.path

        # Enforce exact classification depth + derive the canonical path.
        crop_path = _resolve_crop_path(
            depth=crop_row.classification_depth,
            crop_code=crop_row.code,
            crop_variety_id=crop_variety_id,
            variety_path=variety_path,
            crop_variety_strain_id=crop_variety_strain_id,
            strain_path=strain_path,
        )

        # Two-phase: flip prior current to FALSE, then insert. The unique
        # partial index on (block_id) WHERE is_current = TRUE makes the
        # flip-and-insert atomic within the transaction.
        if make_current:
            await self._tenant.execute(
                update(BlockCrop)
                .where(BlockCrop.block_id == block_id, BlockCrop.is_current.is_(True))
                .values(is_current=False, updated_by=actor_user_id)
            )

        bc = BlockCrop(
            id=block_crop_id,
            block_id=block_id,
            crop_id=crop_id,
            crop_variety_id=crop_variety_id,
            crop_variety_strain_id=crop_variety_strain_id,
            crop_path=crop_path,
            season_label=season_label,
            planting_date=planting_date,
            expected_harvest_start=expected_harvest_start,
            expected_harvest_end=expected_harvest_end,
            plant_density_per_ha=plant_density_per_ha,
            row_spacing_m=row_spacing_m,
            plant_spacing_m=plant_spacing_m,
            canopy_size_class=canopy_size_class,
            growth_stage_locked=growth_stage_locked,
            notes=notes,
            is_current=make_current,
            status="growing" if make_current else "planned",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._tenant.add(bc)
        await self._tenant.flush()
        return _block_crop_to_dict(bc)

    async def list_crops(
        self, *, category: str | None = None, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        stmt = select(Crop)
        if not include_inactive:
            stmt = stmt.where(Crop.is_active.is_(True))
        if category is not None:
            stmt = stmt.where(Crop.category == category)
        stmt = stmt.order_by(Crop.name_en)
        rows = (await self._public.execute(stmt)).scalars().all()
        return [_crop_dict(r) for r in rows]

    async def list_crop_varieties(
        self, *, crop_id: UUID, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        stmt = select(CropVariety).where(CropVariety.crop_id == crop_id)
        if not include_inactive:
            stmt = stmt.where(CropVariety.is_active.is_(True))
        stmt = stmt.order_by(CropVariety.name_en)
        rows = (await self._public.execute(stmt)).scalars().all()
        return [_variety_dict(r) for r in rows]

    async def list_variety_strains(
        self, *, crop_variety_id: UUID, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        stmt = select(CropVarietyStrain).where(CropVarietyStrain.crop_variety_id == crop_variety_id)
        if not include_inactive:
            stmt = stmt.where(CropVarietyStrain.is_active.is_(True))
        stmt = stmt.order_by(CropVarietyStrain.name_en)
        rows = (await self._public.execute(stmt)).scalars().all()
        return [_strain_dict(r) for r in rows]

    # ---- Crop catalog authoring (platform) -----------------------------

    async def get_crop(self, *, crop_id: UUID) -> Crop | None:
        return (
            await self._public.execute(select(Crop).where(Crop.id == crop_id))
        ).scalar_one_or_none()

    async def get_variety(self, *, variety_id: UUID) -> CropVariety | None:
        return (
            await self._public.execute(select(CropVariety).where(CropVariety.id == variety_id))
        ).scalar_one_or_none()

    async def get_strain(self, *, strain_id: UUID) -> CropVarietyStrain | None:
        return (
            await self._public.execute(
                select(CropVarietyStrain).where(CropVarietyStrain.id == strain_id)
            )
        ).scalar_one_or_none()

    async def resolve_taxonomy_by_path(
        self, *, crop_path: str
    ) -> tuple[Crop | None, CropVariety | None, CropVarietyStrain | None]:
        """Walk a ``<crop>[.<variety>[.<strain>]]`` path to its catalog rows.

        Returns ``(crop, variety, strain)`` with ``None`` for any level the
        path doesn't reach or that isn't found.
        """
        segments = [s for s in crop_path.split(".") if s]
        if not segments:
            return None, None, None
        crop = (
            await self._public.execute(select(Crop).where(Crop.code == segments[0]))
        ).scalar_one_or_none()
        if crop is None or len(segments) == 1:
            return crop, None, None
        variety = (
            await self._public.execute(
                select(CropVariety).where(
                    CropVariety.crop_id == crop.id, CropVariety.code == segments[1]
                )
            )
        ).scalar_one_or_none()
        if variety is None or len(segments) == 2:
            return crop, variety, None
        strain = (
            await self._public.execute(
                select(CropVarietyStrain).where(
                    CropVarietyStrain.crop_variety_id == variety.id,
                    CropVarietyStrain.code == segments[2],
                )
            )
        ).scalar_one_or_none()
        return crop, variety, strain

    async def crop_code_exists(self, *, code: str) -> bool:
        return (
            await self._public.execute(select(Crop.id).where(Crop.code == code))
        ).first() is not None

    async def variety_code_exists(self, *, crop_id: UUID, code: str) -> bool:
        return (
            await self._public.execute(
                select(CropVariety.id).where(
                    CropVariety.crop_id == crop_id, CropVariety.code == code
                )
            )
        ).first() is not None

    async def strain_code_exists(self, *, crop_variety_id: UUID, code: str) -> bool:
        return (
            await self._public.execute(
                select(CropVarietyStrain.id).where(
                    CropVarietyStrain.crop_variety_id == crop_variety_id,
                    CropVarietyStrain.code == code,
                )
            )
        ).first() is not None

    async def create_crop(self, *, fields: dict[str, Any]) -> dict[str, Any]:
        row = Crop(**fields)
        self._public.add(row)
        await self._public.flush()
        await self._public.refresh(row)
        return _crop_dict(row)

    async def update_crop(self, *, crop: Crop, fields: dict[str, Any]) -> dict[str, Any]:
        for key, value in fields.items():
            setattr(crop, key, value)
        await self._public.flush()
        await self._public.refresh(crop)
        return _crop_dict(crop)

    async def create_variety(
        self,
        *,
        crop_id: UUID,
        crop_code: str,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        overrides = overrides or {}
        row = CropVariety(
            crop_id=crop_id,
            code=code,
            name_en=name_en,
            name_ar=name_ar,
            path=f"{crop_code}.{code}",
            default_thresholds=overrides.get("default_thresholds"),
            phenology_stages_override=overrides.get("phenology_stages_override"),
            size_classes_override=overrides.get("size_classes_override"),
        )
        self._public.add(row)
        await self._public.flush()
        await self._public.refresh(row)
        return _variety_dict(row)

    async def update_variety(
        self, *, variety: CropVariety, fields: dict[str, Any]
    ) -> dict[str, Any]:
        for key, value in fields.items():
            setattr(variety, key, value)
        await self._public.flush()
        await self._public.refresh(variety)
        return _variety_dict(variety)

    async def create_strain(
        self,
        *,
        crop_variety_id: UUID,
        variety_path: str,
        code: str,
        name_en: str,
        name_ar: str | None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        overrides = overrides or {}
        row = CropVarietyStrain(
            crop_variety_id=crop_variety_id,
            code=code,
            name_en=name_en,
            name_ar=name_ar,
            path=f"{variety_path}.{code}",
            default_thresholds=overrides.get("default_thresholds"),
            phenology_stages_override=overrides.get("phenology_stages_override"),
            size_classes_override=overrides.get("size_classes_override"),
        )
        self._public.add(row)
        await self._public.flush()
        await self._public.refresh(row)
        return _strain_dict(row)

    async def update_strain(
        self, *, strain: CropVarietyStrain, fields: dict[str, Any]
    ) -> dict[str, Any]:
        for key, value in fields.items():
            setattr(strain, key, value)
        await self._public.flush()
        await self._public.refresh(strain)
        return _strain_dict(strain)

    async def list_block_crops(self, *, block_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(BlockCrop)
            .where(BlockCrop.block_id == block_id, BlockCrop.deleted_at.is_(None))
            .order_by(BlockCrop.planting_date.desc().nullslast(), BlockCrop.id.desc())
        )
        rows = (await self._tenant.execute(stmt)).scalars().all()
        return [_block_crop_to_dict(r) for r in rows]

    async def get_block_crop(self, *, block_crop_id: UUID) -> BlockCrop | None:
        return (
            await self._tenant.execute(
                select(BlockCrop).where(
                    BlockCrop.id == block_crop_id, BlockCrop.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def list_block_crops_for_advance(self) -> list[BlockCrop]:
        """Current, non-locked, live block_crops eligible for phenology
        auto-advance: ``is_current`` + not deleted + lock off + a crop path
        set + an in-progress lifecycle status."""
        rows = (
            (
                await self._tenant.execute(
                    select(BlockCrop).where(
                        BlockCrop.is_current.is_(True),
                        BlockCrop.deleted_at.is_(None),
                        BlockCrop.growth_stage_locked.is_(False),
                        BlockCrop.crop_path != "",
                        BlockCrop.status.notin_(("completed", "aborted")),
                    )
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def update_block_crop(
        self, *, bc: BlockCrop, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        for key, value in fields.items():
            setattr(bc, key, value)
        bc.updated_by = actor_user_id
        await self._tenant.flush()
        await self._tenant.refresh(bc)
        return _block_crop_to_dict(bc)

    # ---- Growth-stage logs (PR-3) -----------------------------------

    async def insert_growth_stage_log(
        self,
        *,
        log_id: UUID,
        block_id: UUID,
        block_crop_id: UUID | None,
        stage: str,
        source: str,
        confirmed_by: UUID | None,
        transition_date: datetime | None,
        notes: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Append a transition log row.

        ``transition_date=None`` falls through to the column default
        ``now()`` so the manual path doesn't have to fabricate a clock.
        """
        block_exists = await self._tenant.execute(
            select(Block.id).where(Block.id == block_id, Block.deleted_at.is_(None))
        )
        if block_exists.first() is None:
            raise BlockNotFoundError(block_id)

        log = GrowthStageLog(
            id=log_id,
            block_id=block_id,
            block_crop_id=block_crop_id,
            stage=stage,
            source=source,
            confirmed_by=confirmed_by,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        if transition_date is not None:
            log.transition_date = transition_date
        self._tenant.add(log)
        await self._tenant.flush()
        return _growth_stage_log_to_dict(log)

    async def list_growth_stage_logs(self, *, block_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(GrowthStageLog)
            .where(
                GrowthStageLog.block_id == block_id,
                GrowthStageLog.deleted_at.is_(None),
            )
            .order_by(
                GrowthStageLog.transition_date.desc(),
                GrowthStageLog.id.desc(),
            )
        )
        rows = (await self._tenant.execute(stmt)).scalars().all()
        return [_growth_stage_log_to_dict(r) for r in rows]

    async def update_block_crop_growth_stage(
        self,
        *,
        block_crop_id: UUID,
        stage: str,
        transition_date: datetime,
        actor_user_id: UUID | None,
    ) -> None:
        """Reflect the new stage on the current block_crops row.

        Called from the service alongside `insert_growth_stage_log` so
        the canonical "current stage" stays consistent with the log.
        """
        await self._tenant.execute(
            update(BlockCrop)
            .where(BlockCrop.id == block_crop_id)
            .values(
                growth_stage=stage,
                growth_stage_updated_at=transition_date,
                updated_by=actor_user_id,
            )
        )

    # ---- Members (cross-schema farm_scopes in `public`) -----------

    async def assert_membership_in_tenant(self, *, membership_id: UUID, tenant_id: UUID) -> None:
        result = await self._public.execute(
            text(
                "SELECT 1 FROM public.tenant_memberships " "WHERE id = :mid AND tenant_id = :tid"
            ).bindparams(_bind_uuid("mid"), _bind_uuid("tid")),
            {"mid": membership_id, "tid": tenant_id},
        )
        if result.first() is None:
            raise FarmMembershipMissingError(membership_id=membership_id, tenant_id=tenant_id)

    async def assign_farm_member(
        self,
        *,
        membership_id: UUID,
        farm_id: UUID,
        role: str,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Confirm farm exists in the tenant schema.
        farm_exists = await self._tenant.execute(
            select(Farm.id).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
        if farm_exists.first() is None:
            raise FarmNotFoundError(farm_id)

        # Insert into public.farm_scopes — logical cross-schema FK.
        # `granted_by` is FK→users.id (nullable); wrap the bind in a
        # SELECT so a missing actor UUID null-coerces instead of raising
        # FK violation (e.g. fixture tests with synthetic actor IDs).
        sql = text(
            """
            INSERT INTO public.farm_scopes (membership_id, farm_id, role, granted_by)
            VALUES (:mid, :fid, :role,
                    (SELECT id FROM public.users WHERE id = :actor))
            RETURNING id, granted_at
            """
        ).bindparams(_bind_uuid("mid"), _bind_uuid("fid"), _bind_uuid("actor"))
        try:
            result = await self._public.execute(
                sql,
                {
                    "mid": membership_id,
                    "fid": farm_id,
                    "role": role,
                    "actor": actor_user_id,
                },
            )
        except IntegrityError as exc:
            raise FarmMemberAlreadyAssignedError(
                membership_id=membership_id, farm_id=farm_id, role=role
            ) from exc

        row = result.one()
        return {
            "id": row.id,
            "membership_id": membership_id,
            "farm_id": farm_id,
            "role": role,
            "granted_at": row.granted_at,
            "revoked_at": None,
        }

    async def revoke_farm_member(
        self,
        *,
        farm_scope_id: UUID,
        farm_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        result = await self._public.execute(
            text(
                """
                UPDATE public.farm_scopes
                SET revoked_at = now()
                WHERE id = :sid AND farm_id = :fid AND revoked_at IS NULL
                RETURNING id, membership_id, farm_id, role, granted_at, revoked_at
                """
            ).bindparams(_bind_uuid("sid"), _bind_uuid("fid")),
            {"sid": farm_scope_id, "fid": farm_id},
        )
        row = result.first()
        if row is None:
            raise FarmMembershipMissingError(membership_id=farm_scope_id, tenant_id=farm_id)
        return {
            "id": row.id,
            "membership_id": row.membership_id,
            "farm_id": row.farm_id,
            "role": row.role,
            "granted_at": row.granted_at,
            "revoked_at": row.revoked_at,
        }

    async def get_membership_farm_scopes_for_kc(
        self, *, membership_id: UUID
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Return ``(keycloak_subject, all of the user's active farm scopes)``
        for the user that owns ``membership_id``.

        Used to re-project the ``farm_scopes`` Keycloak user attribute after a
        grant/revoke so the JWT claim the auth middleware reads stays in sync
        with ``public.farm_scopes`` (the source of truth). The Keycloak
        attribute is per-user (global), so we aggregate scopes across *all* of
        the user's memberships — a grant in one tenant must not clobber another.
        ``keycloak_subject`` is ``None`` for an unknown membership;
        ``pending::`` subjects are returned as-is and skipped by the caller."""
        result = await self._public.execute(
            text(
                """
                SELECT u.keycloak_subject AS kc,
                       fs.farm_id AS farm_id,
                       fs.role AS role
                FROM public.tenant_memberships m0
                JOIN public.users u ON u.id = m0.user_id
                LEFT JOIN public.tenant_memberships m ON m.user_id = u.id
                LEFT JOIN public.farm_scopes fs
                       ON fs.membership_id = m.id AND fs.revoked_at IS NULL
                WHERE m0.id = :mid
                """
            ).bindparams(_bind_uuid("mid")),
            {"mid": membership_id},
        )
        rows = result.all()
        if not rows:
            return None, []
        seen: set[tuple[str, str]] = set()
        scopes: list[dict[str, str]] = []
        for r in rows:
            if r.farm_id is None:
                continue
            key = (str(r.farm_id), r.role)
            if key in seen:
                continue
            seen.add(key)
            scopes.append({"farm_id": str(r.farm_id), "role": r.role})
        return rows[0].kc, scopes

    async def list_farm_members(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        result = await self._public.execute(
            text(
                "SELECT id, membership_id, farm_id, role, granted_at, revoked_at "
                "FROM public.farm_scopes WHERE farm_id = :fid AND revoked_at IS NULL "
                "ORDER BY granted_at ASC"
            ).bindparams(_bind_uuid("fid")),
            {"fid": farm_id},
        )
        return [
            {
                "id": r.id,
                "membership_id": r.membership_id,
                "farm_id": r.farm_id,
                "role": r.role,
                "granted_at": r.granted_at,
                "revoked_at": r.revoked_at,
            }
            for r in result.all()
        ]

    async def farm_managers_for(self, *, farm_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
        """Map farm_id -> {membership_id, full_name} for the primary manager.

        "Primary" = the active ``FarmManager`` farm-scope with the earliest
        grant. Farms with no FarmManager scope are absent from the map.
        U-4a derives this in place of the dropped ``farm_manager_id`` column.

        Cross-schema read via the public session — ``farm_scopes``,
        ``tenant_memberships`` and ``users`` all live in ``public``. Batched
        (one query for N farms) to keep list endpoints free of N+1.
        """
        if not farm_ids:
            return {}
        result = await self._public.execute(
            text(
                """
                SELECT DISTINCT ON (fs.farm_id)
                       fs.farm_id, fs.membership_id, u.full_name
                FROM public.farm_scopes fs
                JOIN public.tenant_memberships tm ON tm.id = fs.membership_id
                JOIN public.users u ON u.id = tm.user_id
                WHERE fs.role = 'FarmManager'
                  AND fs.revoked_at IS NULL
                  AND fs.farm_id = ANY(:fids)
                ORDER BY fs.farm_id, fs.granted_at ASC
                """
            ).bindparams(_bind_uuid_array("fids")),
            {"fids": farm_ids},
        )
        return {
            r.farm_id: {"membership_id": r.membership_id, "full_name": r.full_name}
            for r in result.all()
        }

    # ---- Attachments -----------------------------------------------

    async def insert_farm_attachment(
        self,
        *,
        attachment_id: UUID,
        farm_id: UUID,
        kind: str,
        s3_key: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point_ewkt: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Confirm the farm exists in this tenant — otherwise a presigned
        # PUT URL would let a caller scribble objects under arbitrary keys.
        if (await self.get_farm_by_id(farm_id, with_boundary=False)) is None:
            raise FarmNotFoundError(farm_id)

        stmt = text(
            """
            INSERT INTO farm_attachments (
                id, farm_id, kind, s3_key, original_filename, content_type, size_bytes,
                caption, taken_at, geo_point, created_by, updated_by
            ) VALUES (
                :id, :farm_id, :kind, :s3_key, :filename, :content_type, :size,
                :caption, :taken_at,
                CASE WHEN :geo IS NULL THEN NULL ELSE ST_GeomFromEWKT(:geo) END,
                :actor, :actor
            )
            RETURNING id, created_at, updated_at
            """
        ).bindparams(_bind_uuid("id"), _bind_uuid("farm_id"), _bind_uuid("actor"))
        result = await self._tenant.execute(
            stmt,
            {
                "id": attachment_id,
                "farm_id": farm_id,
                "kind": kind,
                "s3_key": s3_key,
                "filename": original_filename,
                "content_type": content_type,
                "size": size_bytes,
                "caption": caption,
                "taken_at": taken_at,
                "geo": geo_point_ewkt,
                "actor": actor_user_id,
            },
        )
        row = result.one()
        return {
            "id": row.id,
            "owner_kind": "farm",
            "owner_id": farm_id,
            "kind": kind,
            "s3_key": s3_key,
            "original_filename": original_filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "caption": caption,
            "taken_at": taken_at,
            "geo_point": None,  # client provided EWKT only; full re-fetch on list/get
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def insert_block_attachment(
        self,
        *,
        attachment_id: UUID,
        block_id: UUID,
        kind: str,
        s3_key: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        caption: str | None,
        taken_at: Any,
        geo_point_ewkt: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        block_exists = await self._tenant.execute(
            select(Block.id).where(Block.id == block_id, Block.deleted_at.is_(None))
        )
        if block_exists.first() is None:
            raise BlockNotFoundError(block_id)

        stmt = text(
            """
            INSERT INTO block_attachments (
                id, block_id, kind, s3_key, original_filename, content_type, size_bytes,
                caption, taken_at, geo_point, created_by, updated_by
            ) VALUES (
                :id, :block_id, :kind, :s3_key, :filename, :content_type, :size,
                :caption, :taken_at,
                CASE WHEN :geo IS NULL THEN NULL ELSE ST_GeomFromEWKT(:geo) END,
                :actor, :actor
            )
            RETURNING id, created_at, updated_at
            """
        ).bindparams(_bind_uuid("id"), _bind_uuid("block_id"), _bind_uuid("actor"))
        result = await self._tenant.execute(
            stmt,
            {
                "id": attachment_id,
                "block_id": block_id,
                "kind": kind,
                "s3_key": s3_key,
                "filename": original_filename,
                "content_type": content_type,
                "size": size_bytes,
                "caption": caption,
                "taken_at": taken_at,
                "geo": geo_point_ewkt,
                "actor": actor_user_id,
            },
        )
        row = result.one()
        return {
            "id": row.id,
            "owner_kind": "block",
            "owner_id": block_id,
            "kind": kind,
            "s3_key": s3_key,
            "original_filename": original_filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "caption": caption,
            "taken_at": taken_at,
            "geo_point": None,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def list_farm_attachments(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(
                FarmAttachment.id,
                FarmAttachment.farm_id,
                FarmAttachment.kind,
                FarmAttachment.s3_key,
                FarmAttachment.original_filename,
                FarmAttachment.content_type,
                FarmAttachment.size_bytes,
                FarmAttachment.caption,
                FarmAttachment.taken_at,
                func.ST_AsGeoJSON(FarmAttachment.geo_point).label("geo_point_geojson"),
                FarmAttachment.created_at,
                FarmAttachment.updated_at,
            )
            .where(FarmAttachment.farm_id == farm_id, FarmAttachment.deleted_at.is_(None))
            .order_by(FarmAttachment.created_at.desc(), FarmAttachment.id.desc())
        )
        rows = (await self._tenant.execute(stmt)).all()
        return [_attachment_row_to_dict(r, owner_kind="farm", owner_id=r.farm_id) for r in rows]

    async def list_block_attachments(self, *, block_id: UUID) -> list[dict[str, Any]]:
        stmt = (
            select(
                BlockAttachment.id,
                BlockAttachment.block_id,
                BlockAttachment.kind,
                BlockAttachment.s3_key,
                BlockAttachment.original_filename,
                BlockAttachment.content_type,
                BlockAttachment.size_bytes,
                BlockAttachment.caption,
                BlockAttachment.taken_at,
                func.ST_AsGeoJSON(BlockAttachment.geo_point).label("geo_point_geojson"),
                BlockAttachment.created_at,
                BlockAttachment.updated_at,
            )
            .where(BlockAttachment.block_id == block_id, BlockAttachment.deleted_at.is_(None))
            .order_by(BlockAttachment.created_at.desc(), BlockAttachment.id.desc())
        )
        rows = (await self._tenant.execute(stmt)).all()
        return [_attachment_row_to_dict(r, owner_kind="block", owner_id=r.block_id) for r in rows]

    async def get_farm_attachment(self, *, attachment_id: UUID) -> dict[str, Any] | None:
        stmt = select(
            FarmAttachment.id,
            FarmAttachment.farm_id,
            FarmAttachment.kind,
            FarmAttachment.s3_key,
            FarmAttachment.original_filename,
            FarmAttachment.content_type,
            FarmAttachment.size_bytes,
            FarmAttachment.caption,
            FarmAttachment.taken_at,
            func.ST_AsGeoJSON(FarmAttachment.geo_point).label("geo_point_geojson"),
            FarmAttachment.created_at,
            FarmAttachment.updated_at,
        ).where(FarmAttachment.id == attachment_id, FarmAttachment.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).first()
        if row is None:
            return None
        return _attachment_row_to_dict(row, owner_kind="farm", owner_id=row.farm_id)

    async def get_block_attachment(self, *, attachment_id: UUID) -> dict[str, Any] | None:
        stmt = select(
            BlockAttachment.id,
            BlockAttachment.block_id,
            BlockAttachment.kind,
            BlockAttachment.s3_key,
            BlockAttachment.original_filename,
            BlockAttachment.content_type,
            BlockAttachment.size_bytes,
            BlockAttachment.caption,
            BlockAttachment.taken_at,
            func.ST_AsGeoJSON(BlockAttachment.geo_point).label("geo_point_geojson"),
            BlockAttachment.created_at,
            BlockAttachment.updated_at,
        ).where(BlockAttachment.id == attachment_id, BlockAttachment.deleted_at.is_(None))
        row = (await self._tenant.execute(stmt)).first()
        if row is None:
            return None
        return _attachment_row_to_dict(row, owner_kind="block", owner_id=row.block_id)

    async def soft_delete_farm_attachment(
        self, *, attachment_id: UUID, actor_user_id: UUID | None
    ) -> bool:
        result = await self._tenant.execute(
            update(FarmAttachment)
            .where(FarmAttachment.id == attachment_id, FarmAttachment.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC), updated_by=actor_user_id)
        )
        # CursorResult exposes rowcount; cast keeps mypy happy under strict.
        from sqlalchemy.engine import CursorResult

        cursor_result: CursorResult[Any] = result  # type: ignore[assignment]
        return (cursor_result.rowcount or 0) > 0

    async def soft_delete_block_attachment(
        self, *, attachment_id: UUID, actor_user_id: UUID | None
    ) -> bool:
        result = await self._tenant.execute(
            update(BlockAttachment)
            .where(BlockAttachment.id == attachment_id, BlockAttachment.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC), updated_by=actor_user_id)
        )
        # CursorResult exposes rowcount; cast keeps mypy happy under strict.
        from sqlalchemy.engine import CursorResult

        cursor_result: CursorResult[Any] = result  # type: ignore[assignment]
        return (cursor_result.rowcount or 0) > 0


# ---- Helpers ---------------------------------------------------------------


def _bind_uuid(name: str) -> Any:
    from sqlalchemy import bindparam

    return bindparam(name, type_=PG_UUID(as_uuid=True))


def _bind_text_array(name: str) -> Any:
    from sqlalchemy import bindparam

    return bindparam(name, type_=ARRAY(Text))


def _bind_uuid_array(name: str) -> Any:
    from sqlalchemy import bindparam

    return bindparam(name, type_=ARRAY(PG_UUID(as_uuid=True)))


def _is_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
    msg = str(exc.orig) if exc.orig is not None else str(exc)
    return constraint_name in msg


def _farm_row_to_dict(row: Any, *, with_boundary: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "centroid": _decode_geojson(row.centroid_geojson),
        "area_m2": row.area_m2,
        "elevation_m": row.elevation_m,
        "governorate": row.governorate,
        "district": row.district,
        "nearest_city": row.nearest_city,
        "address_line": row.address_line,
        "farm_type": row.farm_type,
        "ownership_type": row.ownership_type,
        "primary_water_source": row.primary_water_source,
        "established_date": row.established_date,
        "tags": list(row.tags or []),
        "active_from": row.active_from,
        "active_to": row.active_to,
        "is_active": bool(row.is_active_computed),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if with_boundary:
        out["boundary"] = _decode_geojson(row.boundary_geojson)
    return out


def _block_row_to_dict(row: Any, *, with_boundary: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.id,
        "farm_id": row.farm_id,
        "code": row.code,
        "name": row.name,
        "centroid": _decode_geojson(row.centroid_geojson),
        "area_m2": row.area_m2,
        "elevation_m": row.elevation_m,
        "aoi_hash": row.aoi_hash,
        "irrigation_system": row.irrigation_system,
        "irrigation_source": row.irrigation_source,
        "soil_texture": row.soil_texture,
        "salinity_class": row.salinity_class,
        "soil_ph": row.soil_ph,
        "agronomist_membership_id": row.agronomist_membership_id,
        "notes": row.notes,
        "tags": list(row.tags or []),
        "active_from": row.active_from,
        "active_to": row.active_to,
        "is_active": bool(row.is_active_computed),
        "unit_type": row.unit_type,
        "parent_unit_id": row.parent_unit_id,
        "irrigation_geometry": row.irrigation_geometry,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if with_boundary:
        out["boundary"] = _decode_geojson(row.boundary_geojson)
    return out


def _resolve_crop_path(
    *,
    depth: str,
    crop_code: str,
    crop_variety_id: UUID | None,
    variety_path: str | None,
    crop_variety_strain_id: UUID | None,
    strain_path: str | None,
) -> str:
    """Enforce a crop's exact classification depth and return the
    canonical path. Raises CropTaxonomyError on a depth mismatch."""
    if depth == "crop_only":
        if crop_variety_id is not None or crop_variety_strain_id is not None:
            raise CropTaxonomyError(
                reason="This crop is not sub-classified; omit variety and strain."
            )
        return crop_code
    if depth == "variety":
        if crop_variety_id is None:
            raise CropTaxonomyError(reason="This crop requires a variety.")
        if crop_variety_strain_id is not None:
            raise CropTaxonomyError(reason="This crop has no strain level; omit the strain.")
        return variety_path or crop_code
    # variety_strain
    if crop_variety_id is None or crop_variety_strain_id is None:
        raise CropTaxonomyError(reason="This crop requires both a variety and a strain.")
    return strain_path or crop_code


def _block_crop_to_dict(bc: BlockCrop) -> dict[str, Any]:
    return {
        "id": bc.id,
        "block_id": bc.block_id,
        "crop_id": bc.crop_id,
        "crop_variety_id": bc.crop_variety_id,
        "crop_variety_strain_id": bc.crop_variety_strain_id,
        "crop_path": bc.crop_path,
        "season_label": bc.season_label,
        "planting_date": bc.planting_date,
        "expected_harvest_start": bc.expected_harvest_start,
        "expected_harvest_end": bc.expected_harvest_end,
        "actual_harvest_date": bc.actual_harvest_date,
        "plant_density_per_ha": bc.plant_density_per_ha,
        "row_spacing_m": bc.row_spacing_m,
        "plant_spacing_m": bc.plant_spacing_m,
        "canopy_size_class": bc.canopy_size_class,
        "growth_stage": bc.growth_stage,
        "growth_stage_updated_at": bc.growth_stage_updated_at,
        "growth_stage_locked": bc.growth_stage_locked,
        "is_current": bc.is_current,
        "status": bc.status,
        "notes": bc.notes,
        "created_at": bc.created_at,
        "updated_at": bc.updated_at,
    }


def _growth_stage_log_to_dict(row: GrowthStageLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "block_id": row.block_id,
        "block_crop_id": row.block_crop_id,
        "stage": row.stage,
        "source": row.source,
        "confirmed_by": row.confirmed_by,
        "transition_date": row.transition_date,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _attachment_row_to_dict(row: Any, *, owner_kind: str, owner_id: UUID) -> dict[str, Any]:
    return {
        "id": row.id,
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "kind": row.kind,
        "s3_key": row.s3_key,
        "original_filename": row.original_filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "caption": row.caption,
        "taken_at": row.taken_at,
        "geo_point": _decode_geojson(row.geo_point_geojson),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _crop_dict(r: Crop) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "name_en": r.name_en,
        "name_ar": r.name_ar,
        "scientific_name": r.scientific_name,
        "category": r.category,
        "is_perennial": r.is_perennial,
        "default_growing_season_days": r.default_growing_season_days,
        "gdd_base_temp_c": r.gdd_base_temp_c,
        "gdd_upper_temp_c": r.gdd_upper_temp_c,
        "relevant_indices": list(r.relevant_indices or []),
        "phenology_stages": r.phenology_stages,
        "default_thresholds": r.default_thresholds,
        "size_classes": r.size_classes,
        "classification_depth": r.classification_depth,
        "is_active": r.is_active,
    }


def _variety_dict(r: CropVariety) -> dict[str, Any]:
    return {
        "id": r.id,
        "crop_id": r.crop_id,
        "code": r.code,
        "name_en": r.name_en,
        "name_ar": r.name_ar,
        "path": r.path,
        "attributes": dict(r.attributes or {}),
        "default_thresholds": r.default_thresholds,
        "phenology_stages_override": r.phenology_stages_override,
        "size_classes_override": r.size_classes_override,
        "is_active": r.is_active,
    }


def _strain_dict(r: CropVarietyStrain) -> dict[str, Any]:
    return {
        "id": r.id,
        "crop_variety_id": r.crop_variety_id,
        "code": r.code,
        "name_en": r.name_en,
        "name_ar": r.name_ar,
        "path": r.path,
        "attributes": dict(r.attributes or {}),
        "default_thresholds": r.default_thresholds,
        "phenology_stages_override": r.phenology_stages_override,
        "size_classes_override": r.size_classes_override,
        "is_active": r.is_active,
    }


__all__ = [
    "BlockAttachment",
    "Crop",
    "CropVariety",
    "FarmAttachment",
    "FarmsRepository",
]
