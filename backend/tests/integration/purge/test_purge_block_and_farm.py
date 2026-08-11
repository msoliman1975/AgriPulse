"""End-to-end purge behaviour for blocks and farms.

The properties worth pinning down:

  * **platform-admin only** — a tenant admin who can archive must not be able to
    purge, because purge is the one irreversible delete in the product;
  * **archive first** — a live entity is refused, an archived one goes through;
  * **dry run changes nothing** — and still returns measured counts, so the
    rehearsal is worth trusting;
  * **nothing is left behind** — the receipt's own verification scan must come
    back clean, and a direct query must find no residue in the tables the old
    cascade never touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import client_for, polygon, square

pytestmark = [pytest.mark.integration]


async def _make_farm_with_block(client: AsyncClient, *, code: str = "F1") -> tuple[str, str]:
    farm = await client.post(
        "/api/v1/farms",
        json={"code": code, "name": code, "boundary": square(31.2, 30.0)},
    )
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]
    block = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": f"{code}-B1", "name": f"{code}-B1", "boundary": polygon(31.201, 30.001)},
    )
    assert block.status_code == 201, block.text
    return farm_id, block.json()["id"]


async def _seed_block_data(
    session: AsyncSession, *, schema: str, farm_id: str, block_id: str
) -> None:
    """Seed rows in tables the inactivation cascade does NOT clean up.

    These are the ones that orphan today: two hypertables with no FK
    (``block_index_aggregates``, ``audit_events``) and ``recommendations_history``.
    If purge is complete they are gone afterwards; if it is not, the verification
    scan catches them.
    """
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            """
            INSERT INTO alerts (id, block_id, rule_code, severity, status,
                                signal_snapshot, created_at, updated_at)
            VALUES (gen_random_uuid(), :bid, 'r.purge', 'warning', 'open',
                    '{}'::jsonb, now(), now())
            """
        ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
        {"bid": UUID(block_id)},
    )
    product_id = (
        await session.execute(text("SELECT id FROM imagery_products LIMIT 1"))
    ).scalar_one()
    for day in range(3):
        await session.execute(
            text(
                """
                INSERT INTO block_index_aggregates
                    (time, block_id, index_code, product_id, mean,
                     valid_pixel_count, total_pixel_count, stac_item_id)
                VALUES (:t, :bid, 'ndvi', :pid, 0.5, 100, 100, :stac)
                """
            ).bindparams(
                bindparam("bid", type_=PG_UUID(as_uuid=True)),
                bindparam("pid", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "t": datetime.now(UTC) - timedelta(days=day + 1),
                "bid": UUID(block_id),
                "pid": product_id,
                "stac": f"cdse/s2_l2a/SCENE{day}/hash{day}",
            },
        )
    await session.execute(
        text(
            """
            INSERT INTO audit_events
                (time, id, event_type, actor_kind, subject_kind, subject_id, farm_id)
            VALUES (now(), gen_random_uuid(), 'test.purge', 'user', 'farm', :fid, :fid)
            """
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": UUID(farm_id)},
    )
    await session.commit()


async def _count(session: AsyncSession, schema: str, sql: str, params: dict[str, Any]) -> int:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    n = (await session.execute(text(sql), params)).scalar_one()
    await session.rollback()
    return int(n)


# --- authorisation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_admin_cannot_purge(tenant_env: dict[str, Any]) -> None:
    """Phase 1 is platform-admin only, even for someone who can archive."""
    async with client_for(tenant_env["tenant_context"]) as c:
        _farm_id, block_id = await _make_farm_with_block(c)
        resp = await c.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "F1-B1",
            },
        )
    assert resp.status_code == 403, resp.text


# --- archive first ----------------------------------------------------------


@pytest.mark.asyncio
async def test_live_block_is_refused_until_archived(tenant_env: dict[str, Any]) -> None:
    async with client_for(tenant_env["tenant_context"]) as tc:
        _farm_id, block_id = await _make_farm_with_block(tc)

    async with client_for(tenant_env["platform_context"]) as pc:
        preview = await pc.get(
            "/api/v1/admin/purge/preview",
            params={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
            },
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["archived"] is False
        assert body["blocking"][0]["reason"] == "not_archived"

        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": body["confirmation_phrase"],
            },
        )
    assert resp.status_code == 409, resp.text
    assert "archived" in resp.text

    # Archive it, and the identical request now succeeds.
    async with client_for(tenant_env["tenant_context"]) as tc:
        assert (await tc.delete(f"/api/v1/blocks/{block_id}")).status_code in (200, 204)

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "F1-B1",
            },
        )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "succeeded"


@pytest.mark.asyncio
async def test_wrong_confirmation_is_rejected(tenant_env: dict[str, Any]) -> None:
    async with client_for(tenant_env["tenant_context"]) as tc:
        _farm_id, block_id = await _make_farm_with_block(tc)
        await tc.delete(f"/api/v1/blocks/{block_id}")

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "not-the-code",
            },
        )
    assert resp.status_code == 400, resp.text


# --- dry run ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_measures_but_changes_nothing(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    schema = tenant_env["schema_name"]
    async with client_for(tenant_env["tenant_context"]) as tc:
        farm_id, block_id = await _make_farm_with_block(tc)
    await _seed_block_data(admin_session, schema=schema, farm_id=farm_id, block_id=block_id)

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "F1-B1",
                "dry_run": True,
            },
        )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded"
    assert job["dry_run"] is True

    # A dry run may rehearse a live entity — that is how an admin learns what
    # archiving would commit them to.
    assert job["preview"]["archived"] is False

    # The measured counts are real...
    receipt = job["receipt"]
    assert receipt["deleted"]["db_rows"]["block_index_aggregates"] == 3
    assert receipt["deleted"]["dry_run"] is True

    # ...and nothing was actually removed.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM block_index_aggregates WHERE block_id = :b",
            {"b": block_id},
        )
        == 3
    )
    assert (
        await _count(
            admin_session, schema, "SELECT count(*) FROM blocks WHERE id = :b", {"b": block_id}
        )
        == 1
    )


# --- the real thing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_block_purge_leaves_nothing_behind(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    schema = tenant_env["schema_name"]
    async with client_for(tenant_env["tenant_context"]) as tc:
        farm_id, block_id = await _make_farm_with_block(tc)
        await tc.delete(f"/api/v1/blocks/{block_id}")
    await _seed_block_data(admin_session, schema=schema, farm_id=farm_id, block_id=block_id)

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "block",
                "id": block_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "F1-B1",
                "reason": "test cleanup",
            },
        )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job

    receipt = job["receipt"]
    # The independent re-scan is what makes the receipt worth reading.
    assert receipt["verification"]["orphans_found"] == 0, receipt["verification"]
    assert receipt["deleted"]["db_rows"]["blocks"] == 1
    assert receipt["deleted"]["db_rows"]["alerts"] == 1
    assert receipt["deleted"]["db_rows"]["block_index_aggregates"] == 3

    # The rows the inactivation cascade never touched are gone too.
    # block_index_aggregates in particular has no FK, so only the manifest
    # reaches it — it is the canonical orphan this feature exists to prevent.
    residue = {
        "alerts": "SELECT count(*) FROM alerts WHERE block_id = :b",
        "block_index_aggregates": (
            "SELECT count(*) FROM block_index_aggregates WHERE block_id = :b"
        ),
        "blocks": "SELECT count(*) FROM blocks WHERE id = :b",
    }
    for table, sql in residue.items():
        remaining = await _count(admin_session, schema, sql, {"b": block_id})
        assert remaining == 0, f"{table} still holds rows for the purged block"

    # The farm is untouched — a block purge must not widen its blast radius.
    assert (
        await _count(
            admin_session, schema, "SELECT count(*) FROM farms WHERE id = :f", {"f": farm_id}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_farm_purge_removes_its_blocks(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    """blocks.farm_id is ON DELETE RESTRICT — children must go first."""
    schema = tenant_env["schema_name"]
    async with client_for(tenant_env["tenant_context"]) as tc:
        farm_id, block_id = await _make_farm_with_block(tc, code="FARM")
        second = await tc.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "FARM-B2", "boundary": polygon(31.203, 30.003)},
        )
        assert second.status_code == 201, second.text
        await tc.delete(f"/api/v1/farms/{farm_id}")
    await _seed_block_data(admin_session, schema=schema, farm_id=farm_id, block_id=block_id)

    async with client_for(tenant_env["platform_context"]) as pc:
        preview = (
            await pc.get(
                "/api/v1/admin/purge/preview",
                params={
                    "kind": "farm",
                    "id": farm_id,
                    "tenant_id": str(tenant_env["tenant_id"]),
                },
            )
        ).json()
        assert preview["archived"] is True
        assert preview["blocking"] == []

        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "farm",
                "id": farm_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": preview["confirmation_phrase"],
            },
        )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job
    assert job["receipt"]["verification"]["orphans_found"] == 0

    assert job["receipt"]["deleted"]["db_rows"]["blocks"] == 2
    assert job["receipt"]["deleted"]["db_rows"]["farms"] == 1
    assert (
        await _count(
            admin_session, schema, "SELECT count(*) FROM farms WHERE id = :f", {"f": farm_id}
        )
        == 0
    )
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM blocks WHERE farm_id = :f",
            {"f": farm_id},
        )
        == 0
    )
    # audit_events carries farm_id with no FK — the classic orphan.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM audit_events WHERE farm_id = :f",
            {"f": farm_id},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_farm_purge_archives_its_own_workers_and_spares_shared_ones(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    """W2-C — a worker is tenant-level now, so purging a farm cannot delete them.

    Two things have to hold at once. Somebody who only ever worked the purged
    farm must stop appearing anywhere, but be *archived* rather than deleted:
    hard-deleting cascades `activity_resources` away, and those rows are the
    record of who did the work — including on farms that were not purged.
    Somebody who also works another farm must come through completely
    untouched, having merely lost one availability link.
    """
    schema = tenant_env["schema_name"]
    async with client_for(tenant_env["tenant_context"]) as tc:
        doomed_farm, _ = await _make_farm_with_block(tc, code="DOOMED")
        keeper_farm, _ = await _make_farm_with_block(tc, code="KEEPER")
        await tc.delete(f"/api/v1/farms/{doomed_farm}")

    await admin_session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    only_here = uuid4()
    shared = uuid4()
    for rid, name in ((only_here, "Only Here"), (shared, "Shared Sami")):
        await admin_session.execute(
            text(
                "INSERT INTO resources (id, kind, name, role) "
                "VALUES (:id, 'worker', :n, 'Scout')"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": rid, "n": name},
        )
        await admin_session.execute(
            text("INSERT INTO resource_farms (resource_id, farm_id) VALUES (:r, :f)").bindparams(
                bindparam("r", type_=PG_UUID(as_uuid=True)),
                bindparam("f", type_=PG_UUID(as_uuid=True)),
            ),
            {"r": rid, "f": UUID(doomed_farm)},
        )
    # The shared one also works the farm that survives.
    await admin_session.execute(
        text("INSERT INTO resource_farms (resource_id, farm_id) VALUES (:r, :f)").bindparams(
            bindparam("r", type_=PG_UUID(as_uuid=True)),
            bindparam("f", type_=PG_UUID(as_uuid=True)),
        ),
        {"r": shared, "f": UUID(keeper_farm)},
    )
    await admin_session.commit()

    async with client_for(tenant_env["platform_context"]) as pc:
        preview = (
            await pc.get(
                "/api/v1/admin/purge/preview",
                params={
                    "kind": "farm",
                    "id": doomed_farm,
                    "tenant_id": str(tenant_env["tenant_id"]),
                },
            )
        ).json()
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "farm",
                "id": doomed_farm,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": preview["confirmation_phrase"],
            },
        )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job
    assert job["receipt"]["verification"]["orphans_found"] == 0

    # Neither worker row was deleted — that is the whole point.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM resources WHERE id = ANY(:ids)",
            {"ids": [only_here, shared]},
        )
        == 2
    )
    # The one with nowhere left to work is archived.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM resources WHERE id = :r AND archived_at IS NOT NULL",
            {"r": only_here},
        )
        == 1
    )
    # The shared one is untouched and still linked to the surviving farm.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM resources WHERE id = :r AND archived_at IS NULL",
            {"r": shared},
        )
        == 1
    )
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM resource_farms WHERE resource_id = :r",
            {"r": shared},
        )
        == 1
    )
    # And the purged farm's links are gone for both.
    assert (
        await _count(
            admin_session,
            schema,
            "SELECT count(*) FROM resource_farms WHERE farm_id = :f",
            {"f": UUID(doomed_farm)},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_farm_scopes_are_cleaned_across_the_schema_boundary(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    """public.farm_scopes references a farm in a tenant schema with no FK.

    Nothing has ever deleted these — the hourly consistency check reports them
    and deliberately does not act. A farm purge must clear them.
    """
    async with client_for(tenant_env["tenant_context"]) as tc:
        farm_id, _block_id = await _make_farm_with_block(tc, code="SCOPED")
        await tc.delete(f"/api/v1/farms/{farm_id}")

    await admin_session.execute(
        text(
            "INSERT INTO public.farm_scopes (id, membership_id, farm_id, role) "
            "VALUES (:id, :mid, :fid, 'FarmManager')"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": uuid4(), "mid": tenant_env["membership_id"], "fid": UUID(farm_id)},
    )
    await admin_session.commit()

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "farm",
                "id": farm_id,
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": "SCOPED",
            },
        )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "succeeded"

    remaining = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.farm_scopes WHERE farm_id = :f").bindparams(
                bindparam("f", type_=PG_UUID(as_uuid=True))
            ),
            {"f": UUID(farm_id)},
        )
    ).scalar_one()
    assert remaining == 0
