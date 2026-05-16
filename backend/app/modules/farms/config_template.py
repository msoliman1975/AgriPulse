"""Farm-level subscription template — read, replace, diff, Apply.

PR-2 of the farm-block config model rollout. See
``docs/proposals/farm-block-config-model.md`` § "Rollout — PR-2".

The template is a multi-row list of (product / provider, cadence,
is_active) rows the user wants their blocks to inherit. Block reads do
NOT consult the template at runtime — the template is only touched by
Apply / Reset / Lock. This module exposes:

* :func:`get_template`           — return current imagery + weather rows.
* :func:`replace_template`       — atomic full replace (delete + reinsert).
* :func:`compute_apply_diff`     — per-block list of will_add /
                                   will_update / will_deactivate rows.
* :func:`apply_template`         — execute the reconcile atomically and
                                   stamp ``applied_at = now()`` on each
                                   touched block-side row.

"Extra" subscriptions on a block (not in the template) are
**deactivated** (``is_active = False``), not hard-deleted. This matches
the project convention from ``ImageryRepository.revoke_subscription`` —
preserving ingestion-job history is the safer call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.models import Block, FarmImageryTemplate, FarmWeatherTemplate
from app.modules.imagery.models import ImageryAoiSubscription
from app.modules.weather.models import WeatherSubscription


# ---------- Pure data carriers ----------------------------------------------


@dataclass(frozen=True, slots=True)
class ImageryTemplateRow:
    product_id: UUID
    cadence_hours: int
    cloud_cover_max_pct: int | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class WeatherTemplateRow:
    provider_code: str
    cadence_hours: int
    is_active: bool


@dataclass(frozen=True, slots=True)
class BlockDiff:
    """What Apply would change for one block."""

    block_id: UUID
    will_add: tuple[dict[str, Any], ...]
    will_update: tuple[dict[str, Any], ...]
    will_deactivate: tuple[dict[str, Any], ...]

    @property
    def matches(self) -> bool:
        return not (self.will_add or self.will_update or self.will_deactivate)


@dataclass(frozen=True, slots=True)
class ApplyDiff:
    """The result of ``compute_apply_diff`` across both subscription kinds."""

    imagery: tuple[BlockDiff, ...]
    weather: tuple[BlockDiff, ...]

    @property
    def total_blocks(self) -> int:
        # imagery + weather diffs are computed over the same block set,
        # so either tuple's length is fine.
        return len(self.imagery)

    @property
    def matched_blocks(self) -> int:
        # A block matches the subscription category only if it matches in
        # both kinds simultaneously.
        by_id = {d.block_id: d.matches for d in self.imagery}
        return sum(
            1 for d in self.weather if by_id.get(d.block_id, False) and d.matches
        )


# ---------- Read --------------------------------------------------------------


async def get_imagery_template(
    session: AsyncSession, farm_id: UUID
) -> tuple[ImageryTemplateRow, ...]:
    rows = (
        await session.execute(
            select(FarmImageryTemplate)
            .where(FarmImageryTemplate.farm_id == farm_id)
            .order_by(FarmImageryTemplate.product_id)
        )
    ).scalars().all()
    return tuple(
        ImageryTemplateRow(
            product_id=r.product_id,
            cadence_hours=r.cadence_hours,
            cloud_cover_max_pct=r.cloud_cover_max_pct,
            is_active=r.is_active,
        )
        for r in rows
    )


async def get_weather_template(
    session: AsyncSession, farm_id: UUID
) -> tuple[WeatherTemplateRow, ...]:
    rows = (
        await session.execute(
            select(FarmWeatherTemplate)
            .where(FarmWeatherTemplate.farm_id == farm_id)
            .order_by(FarmWeatherTemplate.provider_code)
        )
    ).scalars().all()
    return tuple(
        WeatherTemplateRow(
            provider_code=r.provider_code,
            cadence_hours=r.cadence_hours,
            is_active=r.is_active,
        )
        for r in rows
    )


# ---------- Replace -----------------------------------------------------------


async def replace_imagery_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    rows: list[ImageryTemplateRow],
    updated_by: UUID | None,
) -> None:
    """Atomic full replace of the imagery template for one farm."""
    _reject_duplicates(
        [r.product_id for r in rows], context="imagery template product_id"
    )
    await session.execute(
        delete(FarmImageryTemplate).where(FarmImageryTemplate.farm_id == farm_id)
    )
    for r in rows:
        session.add(
            FarmImageryTemplate(
                farm_id=farm_id,
                product_id=r.product_id,
                cadence_hours=r.cadence_hours,
                cloud_cover_max_pct=r.cloud_cover_max_pct,
                is_active=r.is_active,
                updated_by=updated_by,
            )
        )
    await session.flush()


async def replace_weather_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    rows: list[WeatherTemplateRow],
    updated_by: UUID | None,
) -> None:
    _reject_duplicates(
        [r.provider_code for r in rows], context="weather template provider_code"
    )
    await session.execute(
        delete(FarmWeatherTemplate).where(FarmWeatherTemplate.farm_id == farm_id)
    )
    for r in rows:
        session.add(
            FarmWeatherTemplate(
                farm_id=farm_id,
                provider_code=r.provider_code,
                cadence_hours=r.cadence_hours,
                is_active=r.is_active,
                updated_by=updated_by,
            )
        )
    await session.flush()


def _reject_duplicates(keys: list[Any], *, context: str) -> None:
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate keys in {context}")


# ---------- Diff --------------------------------------------------------------


async def compute_apply_diff(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None = None,
) -> ApplyDiff:
    """Compute per-block diff for both imagery + weather subscriptions.

    If ``target_block_ids`` is None, the diff covers every active block
    under the farm.
    """
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    imagery_tpl = await get_imagery_template(session, farm_id)
    weather_tpl = await get_weather_template(session, farm_id)

    imagery_diffs: list[BlockDiff] = []
    weather_diffs: list[BlockDiff] = []

    for block_id in block_ids:
        imagery_diffs.append(
            await _imagery_diff_for_block(session, block_id, imagery_tpl)
        )
        weather_diffs.append(
            await _weather_diff_for_block(session, block_id, weather_tpl)
        )

    return ApplyDiff(imagery=tuple(imagery_diffs), weather=tuple(weather_diffs))


async def _imagery_diff_for_block(
    session: AsyncSession,
    block_id: UUID,
    template: tuple[ImageryTemplateRow, ...],
) -> BlockDiff:
    current = {
        row.product_id: row
        for row in (
            await session.execute(
                select(ImageryAoiSubscription).where(
                    ImageryAoiSubscription.block_id == block_id,
                    ImageryAoiSubscription.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    }
    tpl_by_pid = {r.product_id: r for r in template}

    will_add: list[dict[str, Any]] = []
    will_update: list[dict[str, Any]] = []
    will_deactivate: list[dict[str, Any]] = []

    for pid, tpl in tpl_by_pid.items():
        if pid not in current:
            will_add.append(
                {
                    "product_id": pid,
                    "cadence_hours": tpl.cadence_hours,
                    "cloud_cover_max_pct": tpl.cloud_cover_max_pct,
                    "is_active": tpl.is_active,
                }
            )
        else:
            row = current[pid]
            if (
                row.cadence_hours != tpl.cadence_hours
                or row.cloud_cover_max_pct != tpl.cloud_cover_max_pct
                or row.is_active != tpl.is_active
            ):
                will_update.append(
                    {
                        "product_id": pid,
                        "before": {
                            "cadence_hours": row.cadence_hours,
                            "cloud_cover_max_pct": row.cloud_cover_max_pct,
                            "is_active": row.is_active,
                        },
                        "after": {
                            "cadence_hours": tpl.cadence_hours,
                            "cloud_cover_max_pct": tpl.cloud_cover_max_pct,
                            "is_active": tpl.is_active,
                        },
                    }
                )

    for pid, row in current.items():
        if pid not in tpl_by_pid and row.is_active:
            will_deactivate.append(
                {
                    "product_id": pid,
                    "subscription_id": row.id,
                    "cadence_hours": row.cadence_hours,
                }
            )

    return BlockDiff(
        block_id=block_id,
        will_add=tuple(will_add),
        will_update=tuple(will_update),
        will_deactivate=tuple(will_deactivate),
    )


async def _weather_diff_for_block(
    session: AsyncSession,
    block_id: UUID,
    template: tuple[WeatherTemplateRow, ...],
) -> BlockDiff:
    current = {
        row.provider_code: row
        for row in (
            await session.execute(
                select(WeatherSubscription).where(
                    WeatherSubscription.block_id == block_id,
                    WeatherSubscription.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    }
    tpl_by_pc = {r.provider_code: r for r in template}

    will_add: list[dict[str, Any]] = []
    will_update: list[dict[str, Any]] = []
    will_deactivate: list[dict[str, Any]] = []

    for pc, tpl in tpl_by_pc.items():
        if pc not in current:
            will_add.append(
                {
                    "provider_code": pc,
                    "cadence_hours": tpl.cadence_hours,
                    "is_active": tpl.is_active,
                }
            )
        else:
            row = current[pc]
            if row.cadence_hours != tpl.cadence_hours or row.is_active != tpl.is_active:
                will_update.append(
                    {
                        "provider_code": pc,
                        "before": {
                            "cadence_hours": row.cadence_hours,
                            "is_active": row.is_active,
                        },
                        "after": {
                            "cadence_hours": tpl.cadence_hours,
                            "is_active": tpl.is_active,
                        },
                    }
                )

    for pc, row in current.items():
        if pc not in tpl_by_pc and row.is_active:
            will_deactivate.append(
                {
                    "provider_code": pc,
                    "subscription_id": row.id,
                    "cadence_hours": row.cadence_hours,
                }
            )

    return BlockDiff(
        block_id=block_id,
        will_add=tuple(will_add),
        will_update=tuple(will_update),
        will_deactivate=tuple(will_deactivate),
    )


# ---------- Apply -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApplyCounts:
    """Returned by ``apply_template`` so the UI can show what happened."""

    blocks_touched: int
    imagery_added: int
    imagery_updated: int
    imagery_deactivated: int
    weather_added: int
    weather_updated: int
    weather_deactivated: int


async def apply_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
    updated_by: UUID | None,
) -> ApplyCounts:
    """Reconcile each target block's subscription rows to the farm template.

    All work runs in the caller's session — wrap the call in a single
    transaction (the router does this) so partial application is
    impossible.

    Block-side rows touched by Apply get ``applied_at = now()``.
    """
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    imagery_tpl = await get_imagery_template(session, farm_id)
    weather_tpl = await get_weather_template(session, farm_id)

    now = datetime.now(UTC)
    counts = {
        "blocks_touched": 0,
        "imagery_added": 0,
        "imagery_updated": 0,
        "imagery_deactivated": 0,
        "weather_added": 0,
        "weather_updated": 0,
        "weather_deactivated": 0,
    }

    for block_id in block_ids:
        touched = False
        i_diff = await _imagery_diff_for_block(session, block_id, imagery_tpl)
        w_diff = await _weather_diff_for_block(session, block_id, weather_tpl)
        if not (i_diff.matches and w_diff.matches):
            touched = True

        # Imagery: add ---------------------------------------------------
        for spec in i_diff.will_add:
            session.add(
                ImageryAoiSubscription(
                    block_id=block_id,
                    product_id=spec["product_id"],
                    cadence_hours=spec["cadence_hours"],
                    cloud_cover_max_pct=spec["cloud_cover_max_pct"],
                    is_active=spec["is_active"],
                    applied_at=now,
                    created_by=updated_by,
                    updated_by=updated_by,
                )
            )
            counts["imagery_added"] += 1

        # Imagery: update ------------------------------------------------
        for spec in i_diff.will_update:
            after = spec["after"]
            await session.execute(
                update(ImageryAoiSubscription)
                .where(
                    and_(
                        ImageryAoiSubscription.block_id == block_id,
                        ImageryAoiSubscription.product_id == spec["product_id"],
                        ImageryAoiSubscription.deleted_at.is_(None),
                    )
                )
                .values(
                    cadence_hours=after["cadence_hours"],
                    cloud_cover_max_pct=after["cloud_cover_max_pct"],
                    is_active=after["is_active"],
                    applied_at=now,
                    updated_by=updated_by,
                )
            )
            counts["imagery_updated"] += 1

        # Imagery: deactivate -------------------------------------------
        for spec in i_diff.will_deactivate:
            await session.execute(
                update(ImageryAoiSubscription)
                .where(ImageryAoiSubscription.id == spec["subscription_id"])
                .values(is_active=False, applied_at=now, updated_by=updated_by)
            )
            counts["imagery_deactivated"] += 1

        # Weather: add ---------------------------------------------------
        for spec in w_diff.will_add:
            session.add(
                WeatherSubscription(
                    block_id=block_id,
                    provider_code=spec["provider_code"],
                    cadence_hours=spec["cadence_hours"],
                    is_active=spec["is_active"],
                    applied_at=now,
                    created_by=updated_by,
                    updated_by=updated_by,
                )
            )
            counts["weather_added"] += 1

        # Weather: update ------------------------------------------------
        for spec in w_diff.will_update:
            after = spec["after"]
            await session.execute(
                update(WeatherSubscription)
                .where(
                    and_(
                        WeatherSubscription.block_id == block_id,
                        WeatherSubscription.provider_code == spec["provider_code"],
                        WeatherSubscription.deleted_at.is_(None),
                    )
                )
                .values(
                    cadence_hours=after["cadence_hours"],
                    is_active=after["is_active"],
                    applied_at=now,
                    updated_by=updated_by,
                )
            )
            counts["weather_updated"] += 1

        # Weather: deactivate -------------------------------------------
        for spec in w_diff.will_deactivate:
            await session.execute(
                update(WeatherSubscription)
                .where(WeatherSubscription.id == spec["subscription_id"])
                .values(is_active=False, applied_at=now, updated_by=updated_by)
            )
            counts["weather_deactivated"] += 1

        if touched:
            counts["blocks_touched"] += 1

    await session.flush()
    return ApplyCounts(**counts)


# ---------- Internal helpers --------------------------------------------------


async def _resolve_target_blocks(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
) -> tuple[UUID, ...]:
    """All active blocks under the farm, optionally narrowed to a subset.

    Caller-supplied ``target_block_ids`` MUST belong to the farm; rows
    that don't are dropped silently rather than raising — the
    apply-preview UI shows checkboxes for blocks the user already
    sees, so a mismatch can only happen via a stale tab and the safe
    behavior is to ignore.
    """
    stmt = select(Block.id).where(
        Block.farm_id == farm_id,
        Block.deleted_at.is_(None),
    )
    if target_block_ids is not None:
        stmt = stmt.where(Block.id.in_(target_block_ids))
    rows = (await session.execute(stmt)).all()
    return tuple(r.id for r in rows)
