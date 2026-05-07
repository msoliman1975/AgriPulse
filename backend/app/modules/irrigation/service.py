"""Irrigation service — engine driver + state transitions + reads."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.farms.crop_thresholds import resolve_phenology_stages
from app.modules.irrigation.engine import (
    IrrigationInputs,
    compute_recommendation,
)
from app.modules.irrigation.errors import IrrigationScheduleNotFoundError
from app.modules.irrigation.events import (
    IrrigationAppliedV1,
    IrrigationRecommendedV1,
    IrrigationSkippedV1,
)
from app.modules.irrigation.repository import IrrigationRepository
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus

# Per-irrigation-system efficiency factors. Could move to settings or
# the catalog later; the engine accepts whatever the service passes.
_DEFAULT_EFFICIENCY: Decimal = Decimal("0.85")
_EFFICIENCY_BY_SYSTEM: dict[str, Decimal] = {
    "drip": Decimal("0.90"),
    "micro_sprinkler": Decimal("0.80"),
    "pivot": Decimal("0.80"),
    "furrow": Decimal("0.65"),
    "flood": Decimal("0.55"),
    "surface": Decimal("0.65"),
}


class IrrigationService(Protocol):
    async def generate_for_block(
        self,
        *,
        block_id: UUID,
        scheduled_for: date_type | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any] | None: ...

    async def list_for_farm(
        self,
        *,
        farm_id: UUID,
        from_date: date_type | None,
        to_date: date_type | None,
        status_filter: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], ...]: ...

    async def transition(
        self,
        *,
        schedule_id: UUID,
        action: str,
        applied_volume_mm: Decimal | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...


class IrrigationServiceImpl:
    """Tenant-session-scoped service."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        public_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repo = IrrigationRepository(
            tenant_session=tenant_session, public_session=public_session
        )
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

    async def generate_for_block(
        self,
        *,
        block_id: UUID,
        scheduled_for: date_type | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any] | None:
        """Build the inputs, run the engine, write a pending row.

        Returns the schedule dict on success, ``None`` when:
          * the block is missing or has no current crop;
          * a pending row already exists for the same date (the
            partial UNIQUE rejected the insert — re-running the daily
            sweep is intentionally idempotent).
        """
        target = scheduled_for or datetime.now(UTC).date()

        ctx = await self._repo.get_block_context(block_id=block_id)
        if ctx is None or ctx.get("crop_id") is None:
            return None
        farm_id: UUID = ctx["farm_id"]

        weather = await self._repo.get_recent_weather(farm_id=farm_id, target_date=target)
        phenology = resolve_phenology_stages(
            crop_stages=ctx.get("crop_phenology_stages"),
            variety_override=ctx.get("variety_phenology_override"),
        )

        inputs = IrrigationInputs(
            et0_mm_today=weather["et0_mm_today"],
            recent_precip_mm=weather["recent_precip_mm"],
            growth_stage=ctx.get("growth_stage"),
            phenology_stages=phenology,
            application_efficiency=_efficiency_for_block_irrigation_system(
                ctx.get("irrigation_system")
            ),
        )
        rec = compute_recommendation(inputs)

        schedule_id = uuid7()
        inserted = await self._repo.insert_schedule(
            schedule_id=schedule_id,
            block_id=block_id,
            scheduled_for=target,
            recommended_mm=rec.recommended_mm,
            kc_used=rec.kc_used,
            et0_mm_used=rec.et0_mm_used,
            recent_precip_mm=rec.recent_precip_mm,
            growth_stage_context=rec.growth_stage_context,
            actor_user_id=actor_user_id,
        )
        if not inserted:
            # Existing pending row holds the canonical recommendation
            # for the day. The Beat sweep is idempotent on purpose.
            return None

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="irrigation.recommended",
            actor_user_id=actor_user_id,
            actor_kind="system" if actor_user_id is None else "user",
            subject_kind="irrigation_schedule",
            subject_id=schedule_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "scheduled_for": target.isoformat(),
                "recommended_mm": str(rec.recommended_mm),
                "kc_used": str(rec.kc_used),
                "et0_mm_used": str(rec.et0_mm_used),
                "growth_stage": rec.growth_stage_context,
            },
        )
        self._bus.publish(
            IrrigationRecommendedV1(
                schedule_id=schedule_id,
                block_id=block_id,
                scheduled_for=target,
                recommended_mm=rec.recommended_mm,
            )
        )
        out = await self._repo.get_schedule(schedule_id=schedule_id)
        return out

    async def list_for_farm(
        self,
        *,
        farm_id: UUID,
        from_date: date_type | None,
        to_date: date_type | None,
        status_filter: tuple[str, ...] = (),
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_for_farm(
            farm_id=farm_id,
            from_date=from_date,
            to_date=to_date,
            status_filter=status_filter,
        )

    async def transition(
        self,
        *,
        schedule_id: UUID,
        action: str,
        applied_volume_mm: Decimal | None,
        notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        before = await self._repo.get_schedule(schedule_id=schedule_id)
        if before is None:
            raise IrrigationScheduleNotFoundError(schedule_id)
        after = await self._repo.transition_schedule(
            schedule_id=schedule_id,
            action=action,
            applied_volume_mm=applied_volume_mm,
            notes=notes,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type=f"irrigation.{after['status']}",
            actor_user_id=actor_user_id,
            subject_kind="irrigation_schedule",
            subject_id=schedule_id,
            farm_id=None,
            details={
                "block_id": str(after["block_id"]),
                "applied_volume_mm": (
                    str(after["applied_volume_mm"])
                    if after["applied_volume_mm"] is not None
                    else None
                ),
            },
        )
        if after["status"] == "applied":
            self._bus.publish(
                IrrigationAppliedV1(
                    schedule_id=schedule_id,
                    block_id=after["block_id"],
                    applied_volume_mm=after["applied_volume_mm"] or after["recommended_mm"],
                    actor_user_id=actor_user_id,
                )
            )
        elif after["status"] == "skipped":
            self._bus.publish(
                IrrigationSkippedV1(
                    schedule_id=schedule_id,
                    block_id=after["block_id"],
                    actor_user_id=actor_user_id,
                )
            )
        return after


def _efficiency_for_block_irrigation_system(
    system: str | None,
) -> Decimal:
    if system is None:
        return _DEFAULT_EFFICIENCY
    return _EFFICIENCY_BY_SYSTEM.get(system, _DEFAULT_EFFICIENCY)


def get_irrigation_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> IrrigationServiceImpl:
    return IrrigationServiceImpl(tenant_session=tenant_session, public_session=public_session)


def _check(impl: IrrigationServiceImpl) -> IrrigationService:
    return impl
