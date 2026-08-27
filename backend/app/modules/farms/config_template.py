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

from sqlalchemy import and_, bindparam, delete, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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

Category = Literal["subscriptions", "irrigation", "org", "grid"]
_LOCK_COLUMN: dict[Category, str] = {
    "subscriptions": "subscriptions_locked",
    "irrigation": "irrigation_locked",
    "org": "org_locked",
    "grid": "grid_locked",
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
                Farm.grid_locked,
            ).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return {
        "subscriptions": bool(row.subscriptions_locked),
        "irrigation": bool(row.irrigation_locked),
        "org": bool(row.org_locked),
        "grid": bool(row.grid_locked),
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
        elif category == "grid":
            await apply_grid_template(
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
    if category == "grid":
        # Conformance is measured on the anomaly threshold only, because
        # that is the only field Apply can currently write. Locking the
        # category still blocks block-level writes to *both* fields (the
        # guard is on the whole grid-config PUT) — deliberately stricter
        # than the diff, never looser. Cell-size conformance joins here
        # with the bulk-rezone work.
        grid_plan = await compute_grid_apply_plan(session, farm_id=farm_id, target_block_ids=None)
        return {
            "blocks": [_grid_plan_dict(r) for r in grid_plan],
            "total_blocks": len(grid_plan),
            "matched_blocks": sum(1 for r in grid_plan if not r.is_change),
        }
    # org
    org_diff = await compute_org_apply_diff(session, farm_id=farm_id, target_block_ids=None)
    return {
        "blocks": [_simple_diff(d) for d in org_diff],
        "total_blocks": len(org_diff),
        "matched_blocks": sum(1 for d in org_diff if d.matches),
    }


def _grid_plan_dict(r: Any) -> dict[str, Any]:
    """Serialise a ``GridPlanRow`` for the lock-divergence payload."""
    return {
        "block_id": str(r.state.block_id),
        "block_code": r.state.block_code,
        "product_code": r.state.product_code,
        "action": r.action,
        "reason": r.reason,
        "matches": not r.is_change,
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


# ---------- Grid template (cell size + anomaly threshold) -------------------
# Single-row template on `farms` (tenant migration 0053), same shape as
# Irrigation. Apply currently copies the **threshold only** — see
# `app.modules.grid.farm_plan` for why cell size waits on grid valid time.


@dataclass(frozen=True, slots=True)
class GridTemplate:
    cell_size_m: Decimal | None
    anomaly_z_threshold: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_size_m": self.cell_size_m,
            "anomaly_z_threshold": self.anomaly_z_threshold,
        }


async def get_grid_template(session: AsyncSession, *, farm_id: UUID) -> GridTemplate:
    row = (
        await session.execute(
            select(
                Farm.default_grid_cell_size_m,
                Farm.default_anomaly_z_threshold,
            ).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return GridTemplate(
        cell_size_m=row.default_grid_cell_size_m,
        anomaly_z_threshold=row.default_anomaly_z_threshold,
    )


async def replace_grid_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    tpl: GridTemplate,
    updated_by: UUID | None,
) -> None:
    stmt = (
        update(Farm)
        .where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        .values(
            default_grid_cell_size_m=tpl.cell_size_m,
            default_anomaly_z_threshold=tpl.anomaly_z_threshold,
            updated_by=updated_by,
        )
    )
    result = await session.execute(stmt)
    if (getattr(result, "rowcount", 0) or 0) == 0:
        raise FarmNotFoundError(farm_id)
    await session.flush()


async def compute_grid_apply_plan(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None = None,
    clear_override: bool = False,
    scope: str = "threshold",
) -> tuple[Any, ...]:
    """Dry-run the farm's grid template against its blocks.

    Returns ``GridPlanRow`` objects (one per block per active imagery
    subscription). Delegates to the grid module's service rather than
    reimplementing grid semantics here — the grid module owns what a
    config is and which product a block is gridded against.
    """
    from app.modules.grid.service import get_grid_service

    tpl = await get_grid_template(session, farm_id=farm_id)
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    svc = get_grid_service(tenant_session=session)
    if scope == "cell_size":
        return await svc.plan_farm_cell_size(
            block_ids=block_ids, template_cell_size=tpl.cell_size_m
        )
    return await svc.plan_farm_threshold(
        block_ids=block_ids,
        template_z=tpl.anomaly_z_threshold,
        clear_override=clear_override,
    )


async def apply_grid_template(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
    updated_by: UUID | None,
    clear_override: bool = False,
) -> dict[str, int]:
    """Copy the farm's anomaly threshold onto every target block's grid.

    Non-destructive by construction: no geometry is touched, nothing is
    retired, no cells are regenerated. ``updated_by`` is accepted for
    signature symmetry with the other categories but the grid config's
    own ``updated_at`` is stamped by the repository.
    """
    from app.modules.grid.service import get_grid_service

    tpl = await get_grid_template(session, farm_id=farm_id)
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    svc = get_grid_service(tenant_session=session)
    plan, written = await svc.apply_farm_threshold(
        block_ids=block_ids,
        template_z=tpl.anomaly_z_threshold,
        clear_override=clear_override,
    )
    return {
        "blocks_touched": written,
        "total_blocks": len(plan),
    }


async def _ungridded_block_ids(session: AsyncSession, *, farm_id: UUID) -> tuple[UUID, ...]:
    """Live blocks of the farm carrying no grid at all.

    "No grid" is the only state where creating one destroys nothing, which
    is what lets it happen without the rezone confirmation.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT b.id FROM blocks b
                 WHERE b.farm_id = :farm
                   AND b.deleted_at IS NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM grid_configs g
                        WHERE g.block_id = b.id
                          AND g.deleted_at IS NULL
                          AND g.retired_at IS NULL
                          AND g.superseded_at IS NULL
                   )
                 ORDER BY b.id
                """
            ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
            {"farm": farm_id},
        )
    ).all()
    return tuple(r.id for r in rows)


async def grid_blocks_that_have_none(
    session: AsyncSession,
    *,
    farm_id: UUID,
    created_by: UUID | None,
    tenant_schema: str | None,
) -> dict[str, int]:
    """Materialise the farm's cell size on blocks that have no grid yet.

    Saving a cell size was a two-step flow whose first step looked like the
    whole thing: the number landed on `farms.default_grid_cell_size_m` and
    nothing else happened until an explicit apply was confirmed. On prod,
    greenFarm_Test sat with a 20 m template, four blocks, **zero grid
    configs and zero cells** — so the map's grid toggle had nothing to draw
    and said nothing about why.

    Only ungridded blocks are touched, and that restriction is what makes
    this safe to do on a save. Creating a grid where there is none retires
    no geometry and strands no history, so `apply_grid_cell_size` finds
    nothing destructive to plan and never asks for the typed confirmation.
    **Rezoning a block that already has a grid keeps every bit of that
    ceremony** — it is a different act with a different cost.

    Returns zeroed counts when there is no cell size to apply or no block
    lacking a grid, so the caller can report it without a special case.
    """
    tpl = await get_grid_template(session, farm_id=farm_id)
    if tpl.cell_size_m is None:
        return {"blocks_touched": 0, "total_blocks": 0, "scenes_queued": 0, "scenes_stranded": 0}
    targets = await _ungridded_block_ids(session, farm_id=farm_id)
    if not targets:
        return {"blocks_touched": 0, "total_blocks": 0, "scenes_queued": 0, "scenes_stranded": 0}
    return await apply_grid_cell_size(
        session,
        farm_id=farm_id,
        target_block_ids=targets,
        created_by=created_by,
        # Not passed through from the caller: with nothing destructive in the
        # plan there is nothing to confirm, and accepting a name here would
        # invite someone to route a real rezone through this door.
        confirm_farm_name=None,
        backfill_budget_scenes=None,
        tenant_schema=tenant_schema,
    )


class RezoneConfirmationError(ValueError):
    """The typed farm name didn't match. Raised before anything is written."""


async def apply_grid_cell_size(
    session: AsyncSession,
    *,
    farm_id: UUID,
    target_block_ids: tuple[UUID, ...] | None,
    created_by: UUID | None,
    confirm_farm_name: str | None,
    backfill_budget_scenes: int | None,
    tenant_schema: str | None,
) -> dict[str, int]:
    """Rezone / create grids across a farm, then queue the backfill.

    **Destructive.** Every rezoned block's live geometry is retired and
    replaced. Valid time keeps the old geometry serving the scenes it
    produced, so nothing becomes unreadable at the moment of apply — but
    the history only moves onto the new geometry once the backfill has
    recomputed it, and whatever the budget doesn't reach stays behind.

    The confirmation is verified **here**, not in the UI. A destructive
    endpoint that trusts the client to have shown a confirmation dialog
    isn't confirmed at all.
    """
    from app.modules.grid.service import get_grid_service

    tpl = await get_grid_template(session, farm_id=farm_id)
    block_ids = await _resolve_target_blocks(
        session, farm_id=farm_id, target_block_ids=target_block_ids
    )
    svc = get_grid_service(tenant_session=session)

    # Plan first so we know whether this is destructive at all. A farm
    # whose blocks are merely being gridded for the first time destroys
    # nothing and must not be made to type its own name — a confirmation
    # demanded for harmless actions is one operators learn to type past.
    plan = await svc.plan_farm_cell_size(block_ids=block_ids, template_cell_size=tpl.cell_size_m)
    if any(r.is_destructive for r in plan):
        farm_name = await _farm_name(session, farm_id=farm_id)
        if (confirm_farm_name or "").strip() != farm_name:
            raise RezoneConfirmationError(
                "This rezone retires live geometry. Type the farm name "
                f"({farm_name!r}) to confirm."
            )

    applied, written = await svc.apply_farm_cell_size(
        block_ids=block_ids,
        template_cell_size=tpl.cell_size_m,
        created_by=created_by,
    )

    scenes_queued = 0
    scenes_stranded = 0
    farm_scenes_queued = 0
    scenes_unreplayable = 0
    if written and tenant_schema:
        # Queued, never inline: recomputing a farm's history is heavy-worker
        # work measured in thousands of scene jobs.
        from app.modules.grid.backfill import (
            DEFAULT_PER_PAIR_CAP,
            count_farm_backfill_candidates,
            count_farm_scene_candidates,
            count_unreplayable_scenes,
            split_budget,
        )
        from app.modules.grid.tasks import backfill_farm

        backfill_farm.delay(tenant_schema, str(farm_id), backfill_budget_scenes)
        # Counted from the ingestion jobs the backfill will actually walk,
        # NOT from `scenes_affected`. That field is the *destructive* cost
        # — history a rezone strands, measured through the geometry being
        # replaced — so it is structurally 0 for a `create`, which has no
        # prior geometry to count through. Deriving queued work from it
        # meant a farm gridded for the first time reported "0 scenes
        # queued" while the task it had just fired recomputed its entire
        # imagery history.
        # Capped exactly as the task caps its own fetch — see the note on
        # `per_pair_cap` in `grid.tasks._backfill_farm_async`. Narrowing
        # this to the budget would make `scenes_stranded` count only what
        # the budget already excluded, which is always zero.
        planned_scenes = await count_farm_backfill_candidates(
            session,
            farm_id=farm_id,
            since=None,
            per_pair_cap=DEFAULT_PER_PAIR_CAP,
        )
        scenes_queued, scenes_stranded = split_budget(planned_scenes, budget=backfill_budget_scenes)
        # The farm-AOI share of what was queued, and the scenes nothing can
        # replay. Both exist so a small number is readable: "queued 40 of
        # 340" means one thing under a budget and a different thing when
        # 300 scenes kept no bands, and the caller cannot tell them apart
        # from a single total.
        farm_candidates = await count_farm_scene_candidates(
            session,
            farm_id=farm_id,
            since=None,
            per_product_cap=DEFAULT_PER_PAIR_CAP,
        )
        # The budget is spread round-robin across pools, so the farm share
        # of a truncated run cannot be derived here exactly. Reported as
        # "at most", clamped to what was queued.
        farm_scenes_queued = min(farm_candidates, scenes_queued)
        scenes_unreplayable = await count_unreplayable_scenes(session, farm_id=farm_id, since=None)

    return {
        "blocks_touched": written,
        "total_blocks": len(applied),
        "scenes_queued": scenes_queued,
        "scenes_stranded": scenes_stranded,
        "farm_scenes_queued": farm_scenes_queued,
        "scenes_unreplayable": scenes_unreplayable,
    }


async def _farm_name(session: AsyncSession, *, farm_id: UUID) -> str:
    row = (
        await session.execute(
            select(Farm.name).where(Farm.id == farm_id, Farm.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        raise FarmNotFoundError(farm_id)
    return str(row.name)


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
