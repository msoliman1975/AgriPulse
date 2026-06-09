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
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.errors import (
    CategoryLockedError,
    FarmNotFoundError,
    LockDivergenceError,
)
from app.modules.farms.models import (
    Block,
    Farm,
    FarmImageryTemplate,
    FarmWeatherTemplate,
)
from app.modules.imagery.models import ImageryAoiSubscription
from app.modules.weather.models import WeatherSubscription

Category = Literal["subscriptions", "irrigation", "org"]
_LOCK_COLUMN: dict[Category, str] = {
    "subscriptions": "subscriptions_locked",
    "irrigation": "irrigation_locked",
    "org": "org_locked",
}


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
        return sum(1 for d in self.weather if by_id.get(d.block_id, False) and d.matches)


# ---------- Read --------------------------------------------------------------


async def get_imagery_template(
    session: AsyncSession, farm_id: UUID
) -> tuple[ImageryTemplateRow, ...]:
    rows = (
        (
            await session.execute(
                select(FarmImageryTemplate)
                .where(FarmImageryTemplate.farm_id == farm_id)
                .order_by(FarmImageryTemplate.product_id)
            )
        )
        .scalars()
        .all()
    )
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
        (
            await session.execute(
                select(FarmWeatherTemplate)
                .where(FarmWeatherTemplate.farm_id == farm_id)
                .order_by(FarmWeatherTemplate.provider_code)
            )
        )
        .scalars()
        .all()
    )
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
    _reject_duplicates([r.product_id for r in rows], context="imagery template product_id")
    await session.execute(delete(FarmImageryTemplate).where(FarmImageryTemplate.farm_id == farm_id))
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
    _reject_duplicates([r.provider_code for r in rows], context="weather template provider_code")
    await session.execute(delete(FarmWeatherTemplate).where(FarmWeatherTemplate.farm_id == farm_id))
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
        imagery_diffs.append(await _imagery_diff_for_block(session, block_id, imagery_tpl))
        weather_diffs.append(await _weather_diff_for_block(session, block_id, weather_tpl))

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
        )
        .scalars()
        .all()
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
        )
        .scalars()
        .all()
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


# ---------- PR-3: Locks ------------------------------------------------------


async def get_lock_state(session: AsyncSession, *, farm_id: UUID) -> dict[Category, bool]:
    """Return the three lock booleans as ``{category: locked}``."""
    row = (
        await session.execute(
            select(
                Farm.subscriptions_locked,
                Farm.irrigation_locked,
                Farm.org_locked,
            ).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return {
        "subscriptions": bool(row.subscriptions_locked),
        "irrigation": bool(row.irrigation_locked),
        "org": bool(row.org_locked),
    }


async def assert_category_unlocked(
    session: AsyncSession, *, farm_id: UUID, category: Category
) -> None:
    """Raise :class:`CategoryLockedError` if the named category is locked.

    Service-layer guard — direct SQL writes bypass this, which is an
    accepted trade-off per the proposal (keeps the test surface in
    Python and avoids per-table triggers).
    """
    locks = await get_lock_state(session, farm_id=farm_id)
    if locks[category]:
        raise CategoryLockedError(farm_id=farm_id, category=category)


async def lock_category(
    session: AsyncSession,
    *,
    farm_id: UUID,
    category: Category,
    force_overwrite: bool = False,
    updated_by: UUID | None,
) -> dict[str, Any]:
    """Set ``<category>_locked = TRUE``.

    If blocks diverge from the template and ``force_overwrite`` is
    False, raises :class:`LockDivergenceError` with a diff payload so
    the UI can show a "Lock and overwrite" confirm modal.

    If ``force_overwrite`` is True, runs the category's Apply first
    (atomic in the same transaction) then sets the lock.
    """
    diff_payload = await _build_lock_diff(session, farm_id=farm_id, category=category)
    if diff_payload["matched_blocks"] != diff_payload["total_blocks"]:
        if not force_overwrite:
            raise LockDivergenceError(farm_id=farm_id, category=category, diff=diff_payload)
        # Force path — Apply first, then set the lock.
        if category == "subscriptions":
            await apply_template(
                session,
                farm_id=farm_id,
                target_block_ids=None,
                updated_by=updated_by,
            )
        elif category == "irrigation":
            await apply_irrigation_template(
                session, farm_id=farm_id, target_block_ids=None, updated_by=updated_by
            )
        elif category == "org":
            await apply_org_template(
                session, farm_id=farm_id, target_block_ids=None, updated_by=updated_by
            )

    await _set_lock(session, farm_id=farm_id, category=category, value=True)
    return {**diff_payload, "locked": True}


async def unlock_category(
    session: AsyncSession,
    *,
    farm_id: UUID,
    category: Category,
    updated_by: UUID | None,
) -> None:
    """Set ``<category>_locked = FALSE``. Always silent — no diff check."""
    await _set_lock(session, farm_id=farm_id, category=category, value=False)


async def _set_lock(
    session: AsyncSession,
    *,
    farm_id: UUID,
    category: Category,
    value: bool,
) -> None:
    col = _LOCK_COLUMN[category]
    stmt = update(Farm).where(Farm.id == farm_id, Farm.deleted_at.is_(None)).values({col: value})
    result = await session.execute(stmt)
    if (getattr(result, "rowcount", 0) or 0) == 0:
        raise FarmNotFoundError(farm_id)
    await session.flush()


async def _build_lock_diff(
    session: AsyncSession, *, farm_id: UUID, category: Category
) -> dict[str, Any]:
    """Wrap the right apply-preview for the category in a uniform shape."""
    if category == "subscriptions":
        sub_diff = await compute_apply_diff(session, farm_id=farm_id, target_block_ids=None)
        return {
            "imagery": [_diff_dict(d) for d in sub_diff.imagery],
            "weather": [_diff_dict(d) for d in sub_diff.weather],
            "total_blocks": sub_diff.total_blocks,
            "matched_blocks": sub_diff.matched_blocks,
        }
    if category == "irrigation":
        irr_diff = await compute_irrigation_apply_diff(
            session, farm_id=farm_id, target_block_ids=None
        )
        return {
            "blocks": [_simple_diff(d) for d in irr_diff],
            "total_blocks": len(irr_diff),
            "matched_blocks": sum(1 for d in irr_diff if d.matches),
        }
    # org
    org_diff = await compute_org_apply_diff(session, farm_id=farm_id, target_block_ids=None)
    return {
        "blocks": [_simple_diff(d) for d in org_diff],
        "total_blocks": len(org_diff),
        "matched_blocks": sum(1 for d in org_diff if d.matches),
    }


def _diff_dict(d: BlockDiff) -> dict[str, Any]:
    return {
        "block_id": str(d.block_id),
        "will_add": list(d.will_add),
        "will_update": list(d.will_update),
        "will_deactivate": list(d.will_deactivate),
        "matches": d.matches,
    }


def _simple_diff(d: SimpleBlockDiff) -> dict[str, Any]:
    return {
        "block_id": str(d.block_id),
        "before": d.before,
        "after": d.after,
        "matches": d.matches,
    }


# ---------- PR-3: Irrigation template ---------------------------------------
# Single-row template — lives on `farms` (default_irrigation_system /
# _source / _flow_rate_m3_per_hour, added in tenant migration 0027).
# Apply copies those three values to every target block.


@dataclass(frozen=True, slots=True)
class IrrigationTemplate:
    irrigation_system: str | None
    irrigation_source: str | None
    flow_rate_m3_per_hour: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "irrigation_system": self.irrigation_system,
            "irrigation_source": self.irrigation_source,
            "flow_rate_m3_per_hour": self.flow_rate_m3_per_hour,
        }


@dataclass(frozen=True, slots=True)
class SimpleBlockDiff:
    """Used for irrigation + org (single-row templates)."""

    block_id: UUID
    before: dict[str, Any]
    after: dict[str, Any]

    @property
    def matches(self) -> bool:
        return self.before == self.after


async def get_irrigation_template(session: AsyncSession, *, farm_id: UUID) -> IrrigationTemplate:
    row = (
        await session.execute(
            select(
                Farm.default_irrigation_system,
                Farm.default_irrigation_source,
                Farm.default_flow_rate_m3_per_hour,
            ).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return IrrigationTemplate(
        irrigation_system=row.default_irrigation_system,
        irrigation_source=row.default_irrigation_source,
        flow_rate_m3_per_hour=row.default_flow_rate_m3_per_hour,
    )


async def replace_irrigation_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    tpl: IrrigationTemplate,
    updated_by: UUID | None,
) -> None:
    stmt = (
        update(Farm)
        .where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        .values(
            default_irrigation_system=tpl.irrigation_system,
            default_irrigation_source=tpl.irrigation_source,
            default_flow_rate_m3_per_hour=tpl.flow_rate_m3_per_hour,
            updated_by=updated_by,
        )
    )
    result = await session.execute(stmt)
    if (getattr(result, "rowcount", 0) or 0) == 0:
        raise FarmNotFoundError(farm_id)
    await session.flush()


async def compute_irrigation_apply_diff(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None = None,
) -> tuple[SimpleBlockDiff, ...]:
    tpl = await get_irrigation_template(session, farm_id=farm_id)
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    after = tpl.as_dict()
    diffs: list[SimpleBlockDiff] = []
    for bid in block_ids:
        row = (
            await session.execute(
                select(
                    Block.irrigation_system,
                    Block.irrigation_source,
                    Block.flow_rate_m3_per_hour,
                ).where(Block.id == bid)
            )
        ).first()
        if row is None:
            continue
        before = {
            "irrigation_system": row.irrigation_system,
            "irrigation_source": row.irrigation_source,
            "flow_rate_m3_per_hour": row.flow_rate_m3_per_hour,
        }
        diffs.append(SimpleBlockDiff(block_id=bid, before=before, after=after))
    return tuple(diffs)


async def apply_irrigation_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
    updated_by: UUID | None,
) -> dict[str, int]:
    """Copy farm irrigation defaults to every target block. Returns counts."""
    diffs = await compute_irrigation_apply_diff(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    touched = 0
    for d in diffs:
        if d.matches:
            continue
        await session.execute(
            update(Block)
            .where(Block.id == d.block_id, Block.deleted_at.is_(None))
            .values(
                irrigation_system=d.after["irrigation_system"],
                irrigation_source=d.after["irrigation_source"],
                flow_rate_m3_per_hour=d.after["flow_rate_m3_per_hour"],
                updated_by=updated_by,
            )
        )
        touched += 1
    await session.flush()
    return {"blocks_touched": touched, "total_blocks": len(diffs)}


# ---------- PR-3: Org template (additive tags merge) ------------------------


@dataclass(frozen=True, slots=True)
class OrgTemplate:
    default_tags: tuple[str, ...]


async def get_org_template(session: AsyncSession, *, farm_id: UUID) -> OrgTemplate:
    row = (
        await session.execute(
            select(Farm.default_tags).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return OrgTemplate(default_tags=tuple(row.default_tags or []))


async def replace_org_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    tpl: OrgTemplate,
    updated_by: UUID | None,
) -> None:
    stmt = (
        update(Farm)
        .where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        .values(default_tags=list(tpl.default_tags), updated_by=updated_by)
    )
    result = await session.execute(stmt)
    if (getattr(result, "rowcount", 0) or 0) == 0:
        raise FarmNotFoundError(farm_id)
    await session.flush()


async def compute_org_apply_diff(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None = None,
) -> tuple[SimpleBlockDiff, ...]:
    """Additive merge: block matches if every farm tag is already on the block."""
    tpl = await get_org_template(session, farm_id=farm_id)
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    farm_tags = set(tpl.default_tags)
    diffs: list[SimpleBlockDiff] = []
    for bid in block_ids:
        row = (await session.execute(select(Block.tags).where(Block.id == bid))).first()
        if row is None:
            continue
        existing = list(row.tags or [])
        existing_set = set(existing)
        # The "after" state preserves block-local tags AND adds farm tags
        # the block doesn't have yet. Stable ordering: existing first
        # (in order), then new farm tags (sorted) — predictable for tests.
        new_tags = sorted(farm_tags - existing_set)
        after_list = existing + new_tags
        diffs.append(
            SimpleBlockDiff(
                block_id=bid,
                before={"tags": existing},
                after={"tags": after_list},
            )
        )
    return tuple(diffs)


async def apply_org_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
    updated_by: UUID | None,
) -> dict[str, int]:
    """Additively merge farm.default_tags into each target block's tags."""
    diffs = await compute_org_apply_diff(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    touched = 0
    for d in diffs:
        if d.matches:
            continue
        await session.execute(
            update(Block)
            .where(Block.id == d.block_id, Block.deleted_at.is_(None))
            .values(tags=d.after["tags"], updated_by=updated_by)
        )
        touched += 1
    await session.flush()
    return {"blocks_touched": touched, "total_blocks": len(diffs)}
