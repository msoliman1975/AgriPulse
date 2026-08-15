"""The orphan scan must not hold the cluster's lock table hostage.

The tenant history tables are hypertables, and a query against one takes an
AccessShareLock on every chunk *and every chunk index* it might read. The scan
used to run every table of every tenant on the caller's single transaction, so
those locks accumulated until the sweep finished. On production that reached
~9,500 relation locks against a 12,800-entry pool shared by every backend, and
`GET /api/v1/admin/purge/orphans` failed outright with

    asyncpg.exceptions.OutOfMemoryError: out of shared memory
    HINT: You might need to increase max_locks_per_transaction

Counting rows correctly is the easy half and was never broken. What these tests
pin is *where* the locks live, which is the half that took the endpoint down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.purge.scanner import scan_tenant_schema

pytestmark = [pytest.mark.integration]

_BID = bindparam("bid", type_=PG_UUID(as_uuid=True))
_FID = bindparam("fid", type_=PG_UUID(as_uuid=True))

# Spread far enough apart that each row lands in its own chunk whatever the
# configured interval is, so the batching path is genuinely exercised.
_CHUNK_SPREAD_DAYS = 400


async def _seed_orphaned_history(
    session: AsyncSession, schema: str, *, rows: int
) -> tuple[UUID, int]:
    """A block with index history, then the block deleted out from under it.

    Returns the block id and how many history rows are now orphaned.
    """
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(
        text(
            f'INSERT INTO "{schema}".farms (id, code, name, boundary, boundary_utm, '
            "centroid, area_m2) VALUES (:fid, 'LOCK-01', 'Lock Farm', "
            "'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, "
            "31.2 30.1)))'::geometry, "
            "'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "'SRID=4326;POINT(31.205 30.105)'::geometry, 100)"
        ).bindparams(_FID),
        {"fid": farm_id},
    )
    await session.execute(
        text(
            f'INSERT INTO "{schema}".blocks (id, farm_id, code, name, boundary, '
            "boundary_utm, centroid, area_m2, unit_type) VALUES (:bid, :fid, 'LOCK-B1', "
            "'Lock Block', 'SRID=4326;POLYGON((31.2 30.1, 31.205 30.1, 31.205 30.105, "
            "31.2 30.105, 31.2 30.1))'::geometry, "
            "'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "'SRID=4326;POINT(31.2025 30.1025)'::geometry, 50, 'block')"
        ).bindparams(_BID, _FID),
        {"bid": block_id, "fid": farm_id},
    )
    product_id = (
        await session.execute(text("SELECT id FROM public.imagery_products LIMIT 1"))
    ).scalar_one()

    base = datetime(2020, 1, 1, tzinfo=UTC)
    for i in range(rows):
        await session.execute(
            text(
                f'INSERT INTO "{schema}".block_index_aggregates '
                "(block_id, time, index_code, product_id, stac_item_id, mean, "
                "valid_pixel_count, total_pixel_count) "
                "VALUES (:bid, :t, 'ndvi', :pid, :stac, 0.5, 100, 100)"
            ).bindparams(_BID, bindparam("pid", type_=PG_UUID(as_uuid=True))),
            {
                "bid": block_id,
                "pid": product_id,
                "stac": f"lock-scene-{i}",
                "t": base + timedelta(days=i * _CHUNK_SPREAD_DAYS),
            },
        )

    # The block goes, the history stays: exactly the residue the scan hunts.
    await session.execute(
        text(f'DELETE FROM "{schema}".blocks WHERE id = :bid').bindparams(_BID),
        {"bid": block_id},
    )
    # Committed on purpose. The scan reads through its own connection, so it
    # sees committed state only — which is what every caller already gives it.
    await session.commit()
    return block_id, rows


async def _relation_locks_held(session: AsyncSession) -> int:
    """Relation locks held right now by *this* session's backend."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE pid = pg_backend_pid() AND locktype = 'relation'"
                )
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_scan_counts_orphans_across_every_chunk(
    admin_session: AsyncSession, tenant_env: dict[str, Any]
) -> None:
    """Summing per-chunk counts must equal the whole-hypertable count.

    Chunks partition the hypertable, so a row belongs to exactly one. Getting
    this wrong in either direction — double counting a row, or dropping a
    chunk from the sweep — would make the audit lie in the direction nobody
    checks.
    """
    schema = tenant_env["schema_name"]
    _, expected = await _seed_orphaned_history(admin_session, schema, rows=5)

    result = await scan_tenant_schema(admin_session, schema)

    aggregates = [o for o in result.orphans if o.table == "block_index_aggregates"]
    assert len(aggregates) == 1, result.as_dict()
    assert aggregates[0].rows == expected
    assert aggregates[0].column == "block_id"


@pytest.mark.asyncio
async def test_scan_leaves_no_locks_on_the_caller(
    admin_session: AsyncSession, tenant_env: dict[str, Any]
) -> None:
    """The regression: chunk locks must not pile up on the caller's transaction.

    Before the fix the scan ran on this very session, so every chunk and chunk
    index it touched stayed locked until the caller committed — and a sweep of
    all tenants blew the shared lock table. Now the counting happens on the
    scanner's own AUTOCOMMIT connection, so nothing survives the call here.
    """
    schema = tenant_env["schema_name"]
    await _seed_orphaned_history(admin_session, schema, rows=5)

    before = await _relation_locks_held(admin_session)
    await scan_tenant_schema(admin_session, schema)
    after = await _relation_locks_held(admin_session)

    # `before`/`after` cover only the two pg_locks probes themselves. The old
    # implementation left one lock per chunk and per chunk index on this
    # backend; five chunks plus their indexes cleared this comfortably.
    assert after <= before, (
        f"scan left {after - before} extra relation locks on the caller's "
        "transaction; chunk locks must be released as the scan proceeds"
    )
