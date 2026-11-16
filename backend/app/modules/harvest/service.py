"""Harvest records service (build plan 3.5).

Staff record one row per pick on a block. Defaults keep the form short: the
crop assignment and season come from what the block grew that day, the pick
number is the next in that season, and the currency is the tenant's
``default_currency`` at the time of writing (so a later change of the tenant
setting never reprices history). Every write is audited.

Public surface: `HarvestService`, `get_harvest_service`, the errors, and
`revenue_of` (used by PR 6's investor view).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import AuditService, get_audit_service
from app.modules.harvest.repository import HarvestRepository

FALLBACK_CURRENCY = "EGP"


class HarvestBlockNotFoundError(Exception):
    pass


class HarvestLotNotFoundError(Exception):
    pass


class HarvestLotRejectedError(Exception):
    """A pick number already used in the season, or an assignment from another block."""


def revenue_of(weight_kg: Decimal, price_per_kg: Decimal | None) -> Decimal | None:
    """Gross revenue (weight x price), rounded to 2 places; None without a price."""
    if price_per_kg is None:
        return None
    return (weight_kg * price_per_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "revenue": revenue_of(row["weight_kg"], row["price_per_kg"])}


class HarvestService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_schema: str,
        audit_service: AuditService | None = None,
    ) -> None:
        self._repo = HarvestRepository(session)
        self._schema = tenant_schema
        self._audit = audit_service or get_audit_service()

    async def farm_for_block(self, block_id: UUID) -> UUID:
        farm_id = await self._repo.farm_for_block(block_id)
        if farm_id is None:
            raise HarvestBlockNotFoundError(str(block_id))
        return farm_id

    async def get(self, lot_id: UUID) -> dict[str, Any]:
        row = await self._repo.get(lot_id)
        if row is None:
            raise HarvestLotNotFoundError(str(lot_id))
        return _public(row)

    async def picks_between(
        self, *, block_id: UUID, from_date: date, to_date: date | None
    ) -> list[dict[str, Any]]:
        """Raw picks for a read-only view such as the investor app (PR 6).

        Includes ``notes_internal``: callers that face outside staff must
        build their own allowlisted response from these rows.
        """
        return await self._repo.list_between(
            block_id=block_id, from_date=from_date, to_date=to_date
        )

    async def list_for_block(self, block_id: UUID) -> list[dict[str, Any]]:
        await self.farm_for_block(block_id)
        return [_public(r) for r in await self._repo.list_for_block(block_id)]

    async def create(
        self,
        *,
        block_id: UUID,
        tenant_id: UUID | None,
        fields: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        farm_id = await self.farm_for_block(block_id)
        if fields.get("block_crop_id"):
            crop = await self._repo.block_crop(
                block_id=block_id, block_crop_id=fields["block_crop_id"]
            )
            if crop is None:
                raise HarvestLotRejectedError("That crop assignment is not on this block.")
        else:
            crop = await self._repo.block_crop_on(block_id=block_id, on=fields["harvested_on"])
        season = (
            fields.get("season_label")
            or (crop["season_label"] if crop else None)
            or str(fields["harvested_on"].year)
        )
        pick_no = fields.get("pick_no") or await self._repo.next_pick_no(
            block_id=block_id, season_label=season
        )
        if fields.get("pick_no") and await self._repo.pick_taken(
            block_id=block_id, season_label=season, pick_no=pick_no, exclude_id=None
        ):
            raise HarvestLotRejectedError(f"Pick {pick_no} already exists in season {season}.")
        currency = (
            await self._repo.tenant_currency(tenant_id) if tenant_id else None
        ) or FALLBACK_CURRENCY
        row = await self._repo.insert(
            {
                "farm_id": farm_id,
                "block_id": block_id,
                "block_crop_id": crop["id"] if crop else None,
                "season_label": season,
                "pick_no": pick_no,
                "label": fields.get("label"),
                "label_ar": fields.get("label_ar"),
                "harvested_on": fields["harvested_on"],
                "weight_kg": fields["weight_kg"],
                "price_per_kg": fields.get("price_per_kg"),
                "currency": currency,
                "notes_internal": fields.get("notes_internal"),
                "created_by": actor_user_id,
            }
        )
        await self._record("harvest.lot_created", row, actor_user_id, {"pick_no": pick_no})
        return _public(row)

    async def update(
        self, *, lot_id: UUID, changes: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        before = await self._repo.get(lot_id)
        if before is None:
            raise HarvestLotNotFoundError(str(lot_id))
        if "pick_no" in changes and await self._repo.pick_taken(
            block_id=before["block_id"],
            season_label=before["season_label"],
            pick_no=changes["pick_no"],
            exclude_id=lot_id,
        ):
            raise HarvestLotRejectedError(
                f"Pick {changes['pick_no']} already exists in season {before['season_label']}."
            )
        row = await self._repo.update(lot_id, changes, actor_user_id)
        if row is None:
            raise HarvestLotNotFoundError(str(lot_id))
        await self._record("harvest.lot_updated", row, actor_user_id, {"fields": sorted(changes)})
        return _public(row)

    async def delete(self, *, lot_id: UUID, actor_user_id: UUID | None) -> None:
        before = await self._repo.get(lot_id)
        if before is None or not await self._repo.soft_delete(lot_id, actor_user_id):
            raise HarvestLotNotFoundError(str(lot_id))
        await self._record("harvest.lot_deleted", before, actor_user_id, {})

    async def _record(
        self, event: str, row: dict[str, Any], actor: UUID | None, extra: dict[str, Any]
    ) -> None:
        await self._audit.record(
            tenant_schema=self._schema,
            event_type=event,
            actor_user_id=actor,
            subject_kind="harvest_lot",
            subject_id=row["id"],
            farm_id=row["farm_id"],
            details={
                "block_id": str(row["block_id"]),
                "harvested_on": row["harvested_on"].isoformat(),
                "weight_kg": str(row["weight_kg"]),
                **extra,
            },
        )


def get_harvest_service(*, tenant_session: AsyncSession, tenant_schema: str) -> HarvestService:
    return HarvestService(tenant_session, tenant_schema=tenant_schema)
