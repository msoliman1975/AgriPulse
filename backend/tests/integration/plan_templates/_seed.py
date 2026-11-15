"""Shared seeding for the plan-templates integration tests: one farm with one
mango block (Alphonso, short strain) planted 2020-06-01, in a given tenant
schema. Moved here from the retired one-shot apply test.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_block(session: AsyncSession, schema: str) -> tuple:
    crop_id = (
        await session.execute(text("SELECT id FROM public.crops WHERE code='mango'"))
    ).scalar_one()
    variety_id = (
        await session.execute(
            text("SELECT id FROM public.crop_varieties WHERE path='mango.alphonso'")
        )
    ).scalar_one()
    strain_id = (
        await session.execute(
            text("SELECT id FROM public.crop_variety_strains WHERE path='mango.alphonso.short'")
        )
    ).scalar_one()
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(text(f"SET search_path TO {schema}, public"))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'PT', 'PT Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, :farm, 'B1', "
            " ST_GeomFromEWKT('SRID=4326;POLYGON((31.2 30.0,31.201 30.0,31.201 30.001,31.2 30.001,31.2 30.0))'), "
            " 'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": block_id, "farm": farm_id},
    )
    await session.execute(
        text(
            "INSERT INTO block_crops (id, block_id, crop_id, crop_variety_id, "
            " crop_variety_strain_id, crop_path, season_label, planting_date, effective_from, "
            " is_current, status) "
            "VALUES (:id, :block, :crop, :variety, :strain, 'mango.alphonso.short', '2026', "
            # Open-ended from the planting date: a perennial assignment that
            # is still current, which is what the phenology sweep looks for.
            " '2020-06-01', '2020-06-01', TRUE, 'growing')"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("crop", type_=PG_UUID(as_uuid=True)),
            bindparam("variety", type_=PG_UUID(as_uuid=True)),
            bindparam("strain", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "block": block_id,
            "crop": crop_id,
            "variety": variety_id,
            "strain": strain_id,
        },
    )
    await session.execute(text("SET search_path TO public"))
    await session.commit()
    return farm_id, block_id
