"""One card per anomalous block, not one per index that noticed it (0080).

0079 grouped cell-scoped output and deliberately left block-scoped alerts
alone, on the reasoning that one alert per block per rule is already the right
unit. Prod said otherwise: 444 of 445 block-scoped alerts came from the grid
spatial-anomaly sweep, which fires per index — and NDVI, SAVI, EVI, GNDVI and
MSAVI are correlated, so one physical anomaly lit up six to nine cards on a
single block and published a notification for each.

What is worth testing here, beyond "it groups":

* the key is **not** per index, which is the entire point;
* severity still splits, so a critical NDVI and a warning SAVI on one block
  stay two cards — the caller's rule, one level up;
* the members keep their own per-index `rule_code`, because that is what still
  dedups each index under `uq_alerts_block_rule_open`; a parent that stole
  those codes would let the next sweep re-raise every index;
* the drill-down can still say *which* index fired, since the parent's text
  deliberately cannot.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.modules.action_center.repository import ActionCenterRepository
from app.modules.action_center.service import ActionCenterServiceImpl, member_label
from app.modules.alerts.repository import AlertsRepository
from app.modules.tenancy.service import get_tenant_service
from app.shared.action_items import GRID_GROUP_RULE_CODE, build_grid_group_key

pytestmark = [pytest.mark.integration]

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"
_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"

# The correlated vegetation-vigour family, which is exactly the set that fires
# together on one physical anomaly.
_INDICES = ("ndvi", "savi", "evi", "gndvi", "msavi", "ndre")

_SHARED: dict[str, Any] = {}


async def _seed(admin_session: Any) -> dict[str, Any]:
    if not _SHARED:
        slug = f"grid-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
        farm_id = (
            await admin_session.execute(
                text(
                    """
                    INSERT INTO farms (code, name, country_code, boundary, boundary_utm,
                                       centroid, area_m2)
                    VALUES ('GRIDF', 'Grid farm', 'EG',
                            ST_GeomFromText(:poly, 4326),
                            ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                            ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000)
                    RETURNING id
                    """
                ),
                {"poly": _POLY},
            )
        ).scalar_one()
        blocks = [
            (
                await admin_session.execute(
                    text(
                        """
                        INSERT INTO blocks (farm_id, code, boundary, boundary_utm, centroid,
                                            area_m2, aoi_hash)
                        VALUES (:f, :c, ST_GeomFromText(:poly, 4326),
                                ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                                ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000, :h)
                        RETURNING id
                        """
                    ),
                    {"f": farm_id, "c": f"GB-{i}", "poly": _POLY, "h": f"grid-{i}"},
                )
            ).scalar_one()
            for i in range(4)
        ]
        await admin_session.commit()
        _SHARED.update(schema=str(tenant.schema_name), farm_id=farm_id, blocks=blocks)
    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return _SHARED


async def _raise_index_alerts(
    repo: AlertsRepository,
    *,
    block_id: UUID,
    severity: str,
    indices: tuple[str, ...],
    today: date,
) -> tuple[UUID, list[UUID]]:
    """A parent plus one member per index, exactly as the sweep writes them."""
    key = build_grid_group_key(action_type=None, severity=severity)
    parent_id = await repo.find_open_group_parent(block_id=block_id, group_key=key)
    created_parent = parent_id is None
    if created_parent:
        parent_id = uuid4()
        assert await repo.insert_alert(
            alert_id=parent_id,
            block_id=block_id,
            rule_code=GRID_GROUP_RULE_CODE,
            severity=severity,
            diagnosis_en="Spatial anomaly detected on this block.",
            diagnosis_ar=None,
            prescription_en=None,
            prescription_ar=None,
            prescription_activity_id=None,
            signal_snapshot=None,
            actor_user_id=None,
            group_key=key,
            group_parent_id=None,
            is_group=True,
            today=today,
        )
    members = []
    for code in indices:
        member_id = uuid4()
        assert await repo.insert_alert(
            alert_id=member_id,
            block_id=block_id,
            rule_code=f"grid:{code}_spatial_anomaly",
            severity=severity,
            diagnosis_en=f"{code} anomaly",
            diagnosis_ar=None,
            prescription_en=None,
            prescription_ar=None,
            prescription_activity_id=None,
            signal_snapshot={"index": code},
            actor_user_id=None,
            group_key=key,
            group_parent_id=parent_id,
            is_group=False,
            today=today,
        )
        members.append(member_id)
    await repo.refresh_member_count(parent_id=parent_id, today=today)
    assert parent_id is not None
    return parent_id, members


@pytest.mark.asyncio
async def test_six_correlated_indices_on_one_block_are_one_card(admin_session: Any) -> None:
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    parent_id, members = await _raise_index_alerts(
        repo,
        block_id=seed["blocks"][0],
        severity="warning",
        indices=_INDICES,
        today=date(2026, 8, 25),
    )
    await admin_session.commit()

    ac = ActionCenterRepository(tenant_session=admin_session)
    rows = await ac.list_items(farm_id=seed["farm_id"])
    listed = [r for r in rows if r["id"] == parent_id]
    assert len(listed) == 1
    assert listed[0]["member_count"] == len(_INDICES)
    # Six index alerts, one row. Before 0080 this block had six.
    assert not [r for r in rows if r["id"] in set(members)]

    # The members keep their own rule_codes — that is what still dedups each
    # index. A parent that stole them would let the next sweep re-raise all six.
    codes = {m["rule_code"] for m in await ac.list_members(kind="alert", parent_id=parent_id)}
    assert codes == {f"grid:{c}_spatial_anomaly" for c in _INDICES}


@pytest.mark.asyncio
async def test_severity_still_splits_the_card(admin_session: Any) -> None:
    """The caller's rule, one level up: same block, different severity, two
    cards. A critical anomaly folded into a warning card would be the grouping
    hiding the thing that decides urgency."""
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    block = seed["blocks"][1]
    warn_id, _ = await _raise_index_alerts(
        repo, block_id=block, severity="warning", indices=("ndvi",), today=date(2026, 8, 26)
    )
    crit_id, _ = await _raise_index_alerts(
        repo, block_id=block, severity="critical", indices=("ndwi",), today=date(2026, 8, 26)
    )
    await admin_session.commit()

    assert warn_id != crit_id
    ac = ActionCenterRepository(tenant_session=admin_session)
    ids = {r["id"] for r in await ac.list_items(farm_id=seed["farm_id"])}
    assert {warn_id, crit_id} <= ids


@pytest.mark.asyncio
async def test_the_card_says_signals_and_the_drill_down_names_them(
    admin_session: Any,
) -> None:
    """A grid group aggregates measurements, not places.

    Rendering "6 zones" for six indices would send a supervisor looking for six
    locations that do not exist, so the kind travels with the count and each
    member carries the index that fired.
    """
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    parent_id, _ = await _raise_index_alerts(
        repo,
        # Its own block: the per-index dedup is (block_id, rule_code) with no
        # severity in it, so an `ndvi` row on a block already used above would
        # be refused however the severities differ.
        block_id=seed["blocks"][2],
        severity="info",
        indices=("ndvi", "msi"),
        today=date(2026, 8, 27),
    )
    await admin_session.commit()

    service = ActionCenterServiceImpl(tenant_session=admin_session)
    response = await service.list_items(farm_id=seed["farm_id"], group_by="none")
    item = next(i for g in response.groups for i in g.items if i.id == parent_id)
    assert item.aggregation.is_group is True
    assert item.aggregation.member_kind == "signal"
    assert item.aggregation.member_count == 2

    members = await service.list_members(farm_id=seed["farm_id"], item_id=parent_id)
    assert members is not None
    assert {m.label for m in members.members} == {"ndvi", "msi"}
    # A signal member has no place on the map; saying otherwise would put a pin
    # on a block-wide finding.
    assert all(m.cell is None for m in members.members)


def test_member_label_reads_the_index_out_of_a_rule_code() -> None:
    assert member_label("grid:ndvi_spatial_anomaly") == "ndvi"
    assert member_label("grid:lst_spatial_anomaly") == "lst"
    # A cell member is identified by where it is, not by what fired.
    assert member_label(None) is None
    # A tree-sourced member is not a grid signal and must not be mislabelled.
    assert member_label("tree:mango_pest_v1:leaf_hot") is None


@pytest.mark.asyncio
async def test_0080_backfills_the_live_backlog(admin_session: Any) -> None:
    """Down to 0079, seed the pre-0080 shape, come back up.

    The shape that matters: the backfill rebuilds the group key in SQL while
    the sweep builds it in Python. If the two disagreed, a backfilled card and
    tomorrow's firing would fork into two rows for one block, forever, with no
    error anywhere.
    """
    slug = f"grid80-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    schema = str(tenant.schema_name)

    cfg = Config(str(_ALEMBIC_INI), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.downgrade(cfg, "0079")

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    farm_id = (
        await admin_session.execute(
            text(
                """
                INSERT INTO farms (code, name, country_code, boundary, boundary_utm,
                                   centroid, area_m2)
                VALUES ('B80', 'Backfill 80', 'EG', ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000)
                RETURNING id
                """
            ),
            {"poly": _POLY},
        )
    ).scalar_one()
    block_id = (
        await admin_session.execute(
            text(
                """
                INSERT INTO blocks (farm_id, code, boundary, boundary_utm, centroid,
                                    area_m2, aoi_hash)
                VALUES (:f, 'B80-1', ST_GeomFromText(:poly, 4326),
                        ST_Transform(ST_GeomFromText(:poly, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000, 'b80')
                RETURNING id
                """
            ),
            {"f": farm_id, "poly": _POLY},
        )
    ).scalar_one()

    for code in _INDICES:
        await admin_session.execute(
            text(
                """
                INSERT INTO alerts (block_id, rule_code, severity, status, diagnosis_en)
                VALUES (:b, :r, 'warning', 'open', :d)
                """
            ),
            {"b": block_id, "r": f"grid:{code}_spatial_anomaly", "d": f"{code} anomaly"},
        )
    # A resolved row from the same family must be left exactly as it is.
    resolved_id = (
        await admin_session.execute(
            text(
                """
                INSERT INTO alerts (block_id, rule_code, severity, status, diagnosis_en,
                                    resolved_at)
                VALUES (:b, 'grid:ndwi_spatial_anomaly', 'warning', 'resolved', 'old', now())
                RETURNING id
                """
            ),
            {"b": block_id},
        )
    ).scalar_one()
    await admin_session.commit()

    command.upgrade(cfg, "0080")
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    parent = (
        (
            await admin_session.execute(
                text(
                    "SELECT id, group_key, member_count, rule_code, cell_id "
                    "  FROM alerts WHERE is_group = TRUE"
                )
            )
        )
        .mappings()
        .one()
    )
    assert parent["group_key"] == build_grid_group_key(action_type=None, severity="warning")
    assert parent["member_count"] == len(_INDICES)
    assert parent["rule_code"] == GRID_GROUP_RULE_CODE
    # A parent spans indices; it is not itself on a cell.
    assert parent["cell_id"] is None

    orphans = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM alerts WHERE status = 'open' AND is_group = FALSE "
                " AND group_parent_id IS NULL AND rule_code LIKE 'grid:%'"
            )
        )
    ).scalar_one()
    assert orphans == 0

    untouched = (
        (
            await admin_session.execute(
                text("SELECT group_parent_id, group_key, status FROM alerts WHERE id = :i"),
                {"i": resolved_id},
            )
        )
        .mappings()
        .one()
    )
    assert untouched["status"] == "resolved"
    assert untouched["group_parent_id"] is None
    assert untouched["group_key"] is None
    await admin_session.commit()


@pytest.mark.asyncio
async def test_an_index_that_escalates_moves_card_and_leaves_the_old_one_lighter(
    admin_session: Any,
) -> None:
    """The consequence of the dedup key having no severity in it.

    `uq_alerts_block_rule_open` is `(block_id, rule_code)`, so one index holds
    at most one open alert on a block whatever its severity. When that index
    escalates, the existing row moves to the critical card — and the warning
    card it left has to lose a member, which nothing else in the sweep would
    ever go back and notice.
    """
    seed = await _seed(admin_session)
    repo = AlertsRepository(tenant_session=admin_session, public_session=admin_session)
    # Its own block. The module shares one tenant to keep the suite inside its
    # time budget, so a block another test has already put alerts on would make
    # these counts read someone else's rows.
    block = seed["blocks"][3]
    today = date(2026, 8, 28)

    warn_parent, members = await _raise_index_alerts(
        repo, block_id=block, severity="warning", indices=("evi", "msavi"), today=today
    )
    assert await repo.refresh_member_count(parent_id=warn_parent, today=today) == 2

    # `evi` comes back critical the next morning.
    crit_key = build_grid_group_key(action_type=None, severity="critical")
    crit_parent = uuid4()
    assert await repo.insert_alert(
        alert_id=crit_parent,
        block_id=block,
        rule_code=GRID_GROUP_RULE_CODE,
        severity="critical",
        diagnosis_en="Spatial anomaly detected on this block.",
        diagnosis_ar=None,
        prescription_en=None,
        prescription_ar=None,
        prescription_activity_id=None,
        signal_snapshot=None,
        actor_user_id=None,
        group_key=crit_key,
        group_parent_id=None,
        is_group=True,
        today=today,
    )
    existing = await repo.find_open_alert(block_id=block, rule_code="grid:evi_spatial_anomaly")
    assert existing == members[0]
    await repo.attach_child(
        child_id=existing,
        parent_id=crit_parent,
        group_key=crit_key,
        diagnosis_en="evi anomaly, worse",
        diagnosis_ar=None,
        signal_snapshot={"index": "evi"},
        today=today,
        actor_user_id=None,
        severity="critical",
    )
    await repo.refresh_grid_member_counts(block_id=block, today=today)

    counts = dict(
        (
            await admin_session.execute(
                text("SELECT id, member_count FROM alerts WHERE id = ANY(:ids)"),
                {"ids": [warn_parent, crit_parent]},
            )
        ).all()
    )
    # The member moved: one card lost it, the other gained it.
    assert counts[warn_parent] == 1
    assert counts[crit_parent] == 1

    row = (
        (
            await admin_session.execute(
                text("SELECT severity, group_parent_id FROM alerts WHERE id = :i"),
                {"i": existing},
            )
        )
        .mappings()
        .one()
    )
    # The row's own severity followed it. A warning member sitting under a
    # critical card is the shape that makes a queue untrustworthy.
    assert row["severity"] == "critical"
    assert row["group_parent_id"] == crit_parent
    await admin_session.commit()
