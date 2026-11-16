"""Investors service: investors, holdings, and ownership.

The database holds rules R1, R2, R6 and R9 (see tenant migration 0098). This
service adds the ones that need context the database does not have:

* R3 — the polygon is a valid, simple polygon with no holes.
* R4 — a holding sits on an active leaf unit, never on a pivot with sectors.
* R7 — a block with an owned holding cannot be inactivated
  (:func:`block_holding_conflicts`, called by the farms module).
* R8 — a holding's boundary cannot change while it has an owner, unless the
  caller holds ``holding.redraw_sold``.
* Transfers: a new owner ends the previous open-ended owner on the day before.

``status`` is stored as draft / available / archived. "sold" is derived on
read: it means the holding has a current owner today.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit.service import AuditService, get_audit_service
from app.modules.harvest.service import get_harvest_service
from app.modules.iam.users_service import (
    AlreadyInAnotherTenantError,
    TenantUserAlreadyExistsError,
    TenantUsersService,
)
from app.modules.investors.errors import (
    BlockHasHoldingsError,
    BlockNotEligibleError,
    HoldingCodeTakenError,
    HoldingGeometryError,
    HoldingNotFoundError,
    HoldingOwnedError,
    InvestorConflictError,
    InvestorNotFoundError,
    OwnershipConflictError,
    OwnershipNotFoundError,
)
from app.modules.investors.repository import InvestorsRepository
from app.modules.investors.stage_dates import (
    expected_harvest_on,
    season_stages,
    stage_expected_end,
)
from app.shared import clock
from app.shared.auth.context import TenantRole
from app.shared.db.ids import uuid7
from app.shared.storage import crop_image_urls, get_storage_client

_MAX_VERTICES = 2000


# ---- Geometry -------------------------------------------------------------


def polygon_to_ewkt(geom: dict[str, Any]) -> str:
    """Validate a GeoJSON Polygon's shape and return EWKT in SRID 4326.

    Holdings have no holes in the first release (rule R3), so exactly one
    ring is accepted. PostGIS checks self-crossing afterwards.
    """
    if not isinstance(geom, dict) or geom.get("type") != "Polygon":
        raise HoldingGeometryError("The shape must be a GeoJSON Polygon.")
    rings = geom.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise HoldingGeometryError("The polygon has no coordinates.")
    if len(rings) > 1:
        raise HoldingGeometryError("A holding cannot have holes.")
    ring = rings[0]
    if not isinstance(ring, list) or len(ring) < 4:
        raise HoldingGeometryError("A polygon needs at least 3 corners.")
    if len(ring) > _MAX_VERTICES:
        raise HoldingGeometryError(f"A polygon may have at most {_MAX_VERTICES} corners.")
    points: list[tuple[float, float]] = []
    for point in ring:
        if not isinstance(point, list | tuple) or len(point) < 2:
            raise HoldingGeometryError("Each corner must be [longitude, latitude].")
        lon, lat = float(point[0]), float(point[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise HoldingGeometryError("A corner is outside valid longitude or latitude.")
        points.append((lon, lat))
    if points[0] != points[-1]:
        raise HoldingGeometryError("The polygon must be closed.")
    body = ", ".join(f"{lon} {lat}" for lon, lat in points)
    return f"SRID=4326;POLYGON(({body}))"


# ---- Shaping --------------------------------------------------------------


def _shape_holding(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if row["archived_at"] is not None:
        out["status"] = "archived"
    elif row["current_ownership_id"] is not None:
        out["status"] = "sold"
    out["current_owner"] = (
        {
            "ownership_id": row["current_ownership_id"],
            "investor_id": row["current_investor_id"],
            "investor_code": row["current_investor_code"],
            "investor_name": row["current_investor_name"],
            "investor_name_ar": row["current_investor_name_ar"],
            "since": row["current_since"],
            "other_farm_holdings": row.get("current_investor_other_farm_holdings") or 0,
        }
        if row["current_ownership_id"] is not None
        else None
    )
    out["share_pct"] = row["share_pct"] if row["share_pct"] is not None else Decimal("0")
    return out


_log = get_logger(__name__)


class InvestorsService:
    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        tenant_schema: str | None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._session = tenant_session
        self._schema = tenant_schema
        self._repo = InvestorsRepository(tenant_session)
        self._audit = audit_service or get_audit_service()

    async def _record(
        self,
        event_type: str,
        *,
        actor_user_id: UUID | None,
        subject_kind: str,
        subject_id: UUID,
        details: dict[str, Any],
        farm_id: UUID | None = None,
    ) -> None:
        await self._audit.record(
            tenant_schema=self._schema,
            event_type=event_type,
            actor_user_id=actor_user_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            farm_id=farm_id,
            details=details,
        )

    # ---- Investors --------------------------------------------------------

    async def list_investors(
        self, *, status: str | None, query: str | None, include_archived: bool
    ) -> list[dict[str, Any]]:
        return await self._repo.list_investors(
            status=status, query=query, include_archived=include_archived
        )

    async def list_investors_for_farm(
        self,
        *,
        farm_id: UUID,
        status: str | None,
        query: str | None,
        include_archived: bool,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_investors_for_farm(
            farm_id=farm_id, status=status, query=query, include_archived=include_archived
        )

    async def get_investor(self, *, investor_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_investor(investor_id=investor_id)
        if row is None:
            raise InvestorNotFoundError(investor_id)
        return row

    async def get_investor_detail(self, *, investor_id: UUID) -> dict[str, Any]:
        row = await self.get_investor(investor_id=investor_id)
        row["ownerships"] = await self._repo.list_ownerships(investor_id=investor_id)
        return row

    async def create_investor(
        self, *, fields: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        fields = dict(fields)
        code = fields.pop("code", None) or await self._repo.next_code(
            table="investors", prefix="INV"
        )
        fields["code"] = code
        fields["email"] = str(fields["email"]).strip().lower()
        investor_id = uuid7()
        await self._repo.insert_investor(
            investor_id=investor_id, fields=fields, actor_user_id=actor_user_id
        )
        await self._record(
            "investors.investor_created",
            actor_user_id=actor_user_id,
            subject_kind="investor",
            subject_id=investor_id,
            details={"code": code},
        )
        return await self.get_investor(investor_id=investor_id)

    async def update_investor(
        self, *, investor_id: UUID, changes: dict[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        current = await self.get_investor(investor_id=investor_id)
        if current["archived_at"] is not None:
            raise InvestorConflictError("An archived investor cannot be edited.")
        changes = dict(changes)
        if "email" in changes and changes["email"] is not None:
            changes["email"] = str(changes["email"]).strip().lower()
        for required in ("full_name", "email", "investor_type", "preferred_language"):
            if required in changes and changes[required] is None:
                changes.pop(required)
        await self._repo.update_investor(
            investor_id=investor_id, changes=changes, actor_user_id=actor_user_id
        )
        await self._record(
            "investors.investor_updated",
            actor_user_id=actor_user_id,
            subject_kind="investor",
            subject_id=investor_id,
            details={"changed_fields": sorted(changes)},
        )
        return await self.get_investor(investor_id=investor_id)

    async def archive_investor(
        self, *, investor_id: UUID, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        current = await self.get_investor(investor_id=investor_id)
        if current["archived_at"] is not None:
            return current
        if await self._repo.investor_has_open_ownership(investor_id=investor_id):
            raise InvestorConflictError(
                "This investor still owns a holding. End or move the ownership first."
            )
        await self._repo.update_investor(
            investor_id=investor_id,
            changes={"archived_at": clock.now(), "status": "archived"},
            actor_user_id=actor_user_id,
        )
        await self._record(
            "investors.investor_archived",
            actor_user_id=actor_user_id,
            subject_kind="investor",
            subject_id=investor_id,
            details={"code": current["code"]},
        )
        return await self.get_investor(investor_id=investor_id)

    # ---- Holdings ---------------------------------------------------------

    async def _eligible_block(self, *, block_id: UUID, farm_id: UUID) -> dict[str, Any]:
        block = await self._repo.get_block(block_id=block_id)
        if block is None or block["farm_id"] != farm_id or block["deleted_at"] is not None:
            raise BlockNotEligibleError("This block does not exist on this farm.")
        reason = _ineligible_reason(block)
        if reason is not None:
            raise BlockNotEligibleError(reason)
        return block

    async def block_context(self, *, farm_id: UUID, block_id: UUID) -> dict[str, Any]:
        block = await self._repo.get_block(block_id=block_id)
        if block is None or block["farm_id"] != farm_id or block["deleted_at"] is not None:
            raise BlockNotEligibleError("This block does not exist on this farm.")
        holdings = [_shape_holding(r) for r in await self._repo.list_holdings(block_id=block_id)]
        sold = sum((h["area_m2"] for h in holdings if h["status"] == "sold"), Decimal("0"))
        reason = _ineligible_reason(block)
        return {
            "block_id": block["id"],
            "block_code": block["code"],
            "block_name": block["name"],
            "block_name_ar": block["name_ar"],
            "farm_id": block["farm_id"],
            "boundary": block["boundary"],
            "block_area_m2": block["area_m2"],
            "eligible": reason is None,
            "ineligible_reason": reason,
            "holdings": holdings,
            "sold_area_m2": sold,
            "unsold_area_m2": max(Decimal(block["area_m2"]) - sold, Decimal("0")),
        }

    async def list_holdings(
        self,
        *,
        farm_id: UUID,
        block_id: UUID | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_holdings(
            farm_id=farm_id, block_id=block_id, include_archived=include_archived
        )
        return [_shape_holding(r) for r in rows]

    async def get_holding(self, *, farm_id: UUID, holding_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_holding(holding_id=holding_id)
        if row is None or row["farm_id"] != farm_id:
            raise HoldingNotFoundError(holding_id)
        return _shape_holding(row)

    async def get_holding_detail(self, *, farm_id: UUID, holding_id: UUID) -> dict[str, Any]:
        row = await self.get_holding(farm_id=farm_id, holding_id=holding_id)
        row["ownerships"] = await self._repo.list_ownerships(holding_id=holding_id)
        return row

    async def _checked_ewkt(self, boundary: dict[str, Any]) -> str:
        ewkt = polygon_to_ewkt(boundary)
        problem = await self._repo.geometry_problem(boundary_ewkt=ewkt)
        if problem is not None:
            raise HoldingGeometryError(f"The polygon is not valid: {problem}.")
        return ewkt

    async def check_shape(self, *, farm_id: UUID, boundary: dict[str, Any]) -> dict[str, Any]:
        """Which block fully contains this shape, or why none does.

        Never raises for a bad shape: the upload screen checks many shapes at
        once and shows each one's problem in its own row.
        """
        try:
            ewkt = await self._checked_ewkt(boundary)
        except HoldingGeometryError as exc:
            return {"problem": "invalid_shape", "detail": exc.detail}
        touching = await self._repo.blocks_touching(farm_id=farm_id, boundary_ewkt=ewkt)
        if not touching:
            return {
                "problem": "outside_farm",
                "detail": "The shape is outside every block of this farm.",
            }
        # A pivot split into sectors covers its sectors' land; the sector is
        # the leaf that takes the holding, so leaves win.
        covering = [b for b in touching if b["covers"]]
        leaf = next((b for b in covering if not b["has_children"]), None)
        if leaf is None:
            if covering:
                return {
                    "problem": "block_not_eligible",
                    "detail": f"Block {covering[0]['code']} is split into sectors. "
                    "Draw the holding inside one sector.",
                }
            inside = [b for b in touching if b["inside_m2"] > 1.0]
            if len(inside) > 1:
                codes = ", ".join(b["code"] for b in inside)
                return {
                    "problem": "crosses_blocks",
                    "detail": f"The shape crosses blocks {codes}. A holding must sit in one block.",
                }
            return {
                "problem": "outside_block",
                "detail": f"The shape goes outside block {touching[0]['code']}.",
            }
        result: dict[str, Any] = {
            "block_id": leaf["id"],
            "block_code": leaf["code"],
            "area_m2": leaf["area_m2"],
            "share_pct": (
                (Decimal(leaf["area_m2"]) * 100 / Decimal(leaf["block_area_m2"])).quantize(
                    Decimal("0.01")
                )
                if leaf["block_area_m2"]
                else None
            ),
        }
        overlaps = await self._repo.overlapping_holding_codes(
            block_id=leaf["id"], boundary_ewkt=ewkt
        )
        if overlaps:
            result["problem"] = "overlaps_holding"
            result["detail"] = "The shape overlaps holding " + ", ".join(overlaps) + "."
        return result

    async def create_holding(
        self,
        *,
        farm_id: UUID,
        block_id: UUID | None,
        payload: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Create a holding; find its block from the shape when none is given.

        Status "sold" stores the holding as available and gives it an owner
        from `owner_since` (default today) in the same transaction.
        """
        if block_id is None:
            found = await self.check_shape(farm_id=farm_id, boundary=payload["boundary"])
            if found.get("block_id") is None:
                if found.get("problem") == "invalid_shape":
                    raise HoldingGeometryError(found["detail"])
                raise BlockNotEligibleError(found["detail"])
            block_id = found["block_id"]
        await self._eligible_block(block_id=block_id, farm_id=farm_id)
        ewkt = await self._checked_ewkt(payload["boundary"])
        code = payload.get("code")
        if code:
            if await self._repo.holding_code_taken(code=code):
                raise HoldingCodeTakenError(code)
        else:
            code = await self._repo.next_code(table="holdings", prefix="H")
        holding_id = uuid7()
        await self._repo.insert_holding(
            holding_id=holding_id,
            code=code,
            block_id=block_id,
            name=payload["name"].strip(),
            name_ar=payload.get("name_ar"),
            boundary_ewkt=ewkt,
            tree_count=payload.get("tree_count"),
            status=(
                "available"
                if payload.get("status") == "sold"
                else (payload.get("status") or "draft")
            ),
            notes_internal=payload.get("notes_internal"),
            actor_user_id=actor_user_id,
        )
        await self._record(
            "investors.holding_created",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=holding_id,
            farm_id=farm_id,
            details={"code": code, "block_id": str(block_id)},
        )
        if payload.get("status") == "sold":
            await self.assign_owner(
                farm_id=farm_id,
                holding_id=holding_id,
                payload={
                    "investor_id": payload["investor_id"],
                    "start_date": payload.get("owner_since") or clock.today(),
                    "acquired_by": "purchase",
                },
                actor_user_id=actor_user_id,
            )
        return await self.get_holding(farm_id=farm_id, holding_id=holding_id)

    async def update_holding(
        self,
        *,
        farm_id: UUID,
        holding_id: UUID,
        changes: dict[str, Any],
        can_redraw_sold: bool,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        current = await self.get_holding(farm_id=farm_id, holding_id=holding_id)
        if current["archived_at"] is not None:
            raise HoldingOwnedError("An archived holding cannot be edited.")
        changes = dict(changes)
        boundary = changes.pop("boundary", None)
        investor_id = changes.pop("investor_id", None)
        owner_since = changes.pop("owner_since", None)
        if changes.get("name") is None:
            changes.pop("name", None)
        if changes.get("status") is None:
            changes.pop("status", None)
        sell = False
        if changes.get("status") == "sold":
            # "sold" is not stored: it means "give this holding an owner".
            changes.pop("status")
            if current["current_owner"] is None:
                if investor_id is None:
                    raise OwnershipConflictError("A sold holding needs an investor.")
                sell = True
        elif "status" in changes and current["current_owner"] is not None:
            raise HoldingOwnedError(
                "This holding has an owner. End the ownership before you change its status."
            )
        ewkt: str | None = None
        if boundary is not None:
            if not can_redraw_sold and await self._repo.holding_has_open_ownership(
                holding_id=holding_id
            ):
                raise HoldingOwnedError(
                    "This holding has an owner. Only a user allowed to redraw sold "
                    "holdings can change its boundary."
                )
            ewkt = await self._checked_ewkt(boundary)
        await self._repo.update_holding(
            holding_id=holding_id,
            changes=changes,
            boundary_ewkt=ewkt,
            actor_user_id=actor_user_id,
        )
        details: dict[str, Any] = {
            "changed_fields": sorted({*changes, *(("boundary",) if ewkt else ())})
        }
        if ewkt is not None:
            details["area_m2_before"] = str(current["area_m2"])
        await self._record(
            "investors.holding_updated",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=holding_id,
            farm_id=farm_id,
            details=details,
        )
        if sell:
            await self.assign_owner(
                farm_id=farm_id,
                holding_id=holding_id,
                payload={
                    "investor_id": investor_id,
                    "start_date": owner_since or clock.today(),
                    "acquired_by": "purchase",
                },
                actor_user_id=actor_user_id,
            )
        return await self.get_holding(farm_id=farm_id, holding_id=holding_id)

    async def archive_holding(
        self, *, farm_id: UUID, holding_id: UUID, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        current = await self.get_holding(farm_id=farm_id, holding_id=holding_id)
        if current["archived_at"] is not None:
            return current
        if await self._repo.holding_has_open_ownership(holding_id=holding_id):
            raise HoldingOwnedError(
                "This holding has a current or future owner. End the ownership first."
            )
        await self._repo.update_holding(
            holding_id=holding_id,
            changes={"archived_at": clock.now()},
            boundary_ewkt=None,
            actor_user_id=actor_user_id,
        )
        await self._record(
            "investors.holding_archived",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=holding_id,
            farm_id=farm_id,
            details={"code": current["code"]},
        )
        return await self.get_holding(farm_id=farm_id, holding_id=holding_id)

    async def delete_holding(
        self, *, farm_id: UUID, holding_id: UUID, actor_user_id: UUID | None
    ) -> None:
        """Delete a holding that was never used: no owner, past or present.

        A holding with any ownership entry is part of an investor's history,
        so it can only be archived.
        """
        current = await self.get_holding(farm_id=farm_id, holding_id=holding_id)
        if await self._repo.holding_has_ownership_history(holding_id=holding_id):
            raise HoldingOwnedError(
                "This holding has ownership history, so it cannot be deleted. "
                "Archive it instead."
            )
        await self._repo.soft_delete_holding(holding_id=holding_id, actor_user_id=actor_user_id)
        await self._record(
            "investors.holding_deleted",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=holding_id,
            farm_id=farm_id,
            details={"code": current["code"], "name": current["name"]},
        )

    # ---- Ownership --------------------------------------------------------

    async def assign_owner(
        self,
        *,
        farm_id: UUID,
        holding_id: UUID,
        payload: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        holding = await self.get_holding(farm_id=farm_id, holding_id=holding_id)
        if holding["archived_at"] is not None:
            raise HoldingOwnedError("An archived holding cannot get an owner.")
        investor = await self.get_investor(investor_id=payload["investor_id"])
        if investor["archived_at"] is not None:
            raise InvestorConflictError("An archived investor cannot own a holding.")

        start = payload["start_date"]
        open_row = await self._repo.get_open_ended_ownership(holding_id=holding_id)
        if open_row is not None:
            if open_row["investor_id"] == investor["id"]:
                raise OwnershipConflictError("This investor already owns this holding.")
            if start <= open_row["start_date"]:
                raise OwnershipConflictError(
                    "The new owner must start after the current owner's start date "
                    f"({open_row['start_date'].isoformat()})."
                )
            await self._repo.end_ownership(
                ownership_id=open_row["id"],
                end_date=start - timedelta(days=1),
                ended_by=payload.get("previous_ended_by") or "resale",
                actor_user_id=actor_user_id,
            )

        ownership_id = uuid7()
        await self._repo.insert_ownership(
            ownership_id=ownership_id,
            holding_id=holding_id,
            investor_id=investor["id"],
            start_date=start,
            acquired_by=payload.get("acquired_by") or "purchase",
            contract_ref=payload.get("contract_ref"),
            actor_user_id=actor_user_id,
        )
        if holding["status"] == "draft":
            # An owned holding is on sale by definition; leaving it "draft"
            # would hide it the moment the ownership ends.
            await self._repo.update_holding(
                holding_id=holding_id,
                changes={"status": "available"},
                boundary_ewkt=None,
                actor_user_id=actor_user_id,
            )
        await self._record(
            "investors.ownership_assigned",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=holding_id,
            farm_id=farm_id,
            details={
                "ownership_id": str(ownership_id),
                "investor_id": str(investor["id"]),
                "start_date": start.isoformat(),
                "transferred_from": (
                    str(open_row["investor_id"]) if open_row is not None else None
                ),
            },
        )
        return await self.get_holding_detail(farm_id=farm_id, holding_id=holding_id)

    async def _ownership_on_farm(self, *, farm_id: UUID, ownership_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_ownership(ownership_id=ownership_id)
        if row is None or row["farm_id"] != farm_id:
            raise OwnershipNotFoundError(ownership_id)
        return row

    async def end_ownership(
        self,
        *,
        farm_id: UUID,
        ownership_id: UUID,
        end_date: Any,
        ended_by: str,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        row = await self._ownership_on_farm(farm_id=farm_id, ownership_id=ownership_id)
        if end_date < row["start_date"]:
            raise OwnershipConflictError("The end date is before the start date.")
        await self._repo.end_ownership(
            ownership_id=ownership_id,
            end_date=end_date,
            ended_by=ended_by,
            actor_user_id=actor_user_id,
        )
        await self._record(
            "investors.ownership_ended",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=row["holding_id"],
            farm_id=farm_id,
            details={
                "ownership_id": str(ownership_id),
                "end_date": end_date.isoformat(),
                "ended_by": ended_by,
            },
        )
        return await self.get_holding_detail(farm_id=farm_id, holding_id=row["holding_id"])

    async def delete_ownership(
        self, *, farm_id: UUID, ownership_id: UUID, actor_user_id: UUID | None
    ) -> None:
        """Remove an ownership entered by mistake. Audited; the row is soft-deleted."""
        row = await self._ownership_on_farm(farm_id=farm_id, ownership_id=ownership_id)
        await self._repo.delete_ownership(ownership_id=ownership_id, actor_user_id=actor_user_id)
        await self._record(
            "investors.ownership_deleted",
            actor_user_id=actor_user_id,
            subject_kind="holding",
            subject_id=row["holding_id"],
            farm_id=farm_id,
            details={
                "ownership_id": str(ownership_id),
                "investor_id": str(row["investor_id"]),
                "start_date": row["start_date"].isoformat(),
            },
        )

    # ---- App login (the investor's user account) ---------------------------

    def _login_result(self, investor: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {
            "investor": investor,
            "email_sent": bool(result.get("keycloak_email_sent")),
            "temporary_password": result.get("temporary_password"),
            "provisioning": result.get("keycloak_provisioning"),
        }

    async def create_login(
        self,
        *,
        investor_id: UUID,
        users: TenantUsersService,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Create the investor's user, with the Investor role, and link it.

        The IAM invite flow creates the Keycloak user, the public.users row,
        the membership and the role, and sends the set-password email. This
        is the only place the Investor role is granted.
        """
        investor = await self.get_investor(investor_id=investor_id)
        if investor["archived_at"] is not None:
            raise InvestorConflictError("An archived investor cannot get an app login.")
        if investor["user_id"] is not None:
            raise InvestorConflictError("This investor already has an app login.")
        # The invite flow raises plain exceptions for an email that already
        # has a user. Left alone they became a 500 with no CORS headers, which
        # the browser shows as "Network Error".
        try:
            result = await users.invite_user(
                email=investor["email"],
                full_name=investor["full_name"],
                full_name_ar=investor["full_name_ar"],
                phone=investor["phone"],
                tenant_role=TenantRole.INVESTOR.value,
                tenant_schema=self._schema or "",
                actor_user_id=actor_user_id,
            )
        except TenantUserAlreadyExistsError as exc:
            raise InvestorConflictError(
                f"{investor['email']} already belongs to a user of this company. "
                "An investor login needs an email that no other user has. "
                "Change the investor's email, then try again."
            ) from exc
        except AlreadyInAnotherTenantError as exc:
            raise InvestorConflictError(
                f"{investor['email']} already has an AgriPulse account with another "
                "organisation. Change the investor's email, then try again."
            ) from exc
        # Link by the Keycloak id when Keycloak gave one. `/me` re-keys
        # `public.users.id` to it on the first sign-in, and the token's `sub`
        # is that same id, so this link survives the re-key. A pending
        # provisioning has no real subject yet; fall back to the users id.
        link = _uuid_or_none(result.get("keycloak_subject")) or result["user_id"]
        await self._repo.update_investor(
            investor_id=investor_id,
            changes={
                "user_id": link,
                "status": "invited",
                "invited_at": clock.now(),
            },
            actor_user_id=actor_user_id,
        )
        await self._record(
            "investors.login_created",
            actor_user_id=actor_user_id,
            subject_kind="investor",
            subject_id=investor_id,
            details={"user_id": str(result["user_id"])},
        )
        return self._login_result(await self.get_investor(investor_id=investor_id), result)

    async def _linked(self, investor_id: UUID) -> dict[str, Any]:
        """The investor, with `login_user_id`: the current users id behind the link."""
        investor = await self.get_investor(investor_id=investor_id)
        if investor["user_id"] is None:
            raise InvestorConflictError("This investor has no app login yet.")
        current = await self._repo.resolve_login_user_id(stored=investor["user_id"])
        if current is None:
            raise InvestorConflictError("The app login user for this investor no longer exists.")
        investor["login_user_id"] = current
        return investor

    async def resend_login(
        self,
        *,
        investor_id: UUID,
        users: TenantUsersService,
        tenant_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        investor = await self._linked(investor_id)
        result = await users.resend_invite(
            user_id=investor["login_user_id"],
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            tenant_schema=self._schema or "",
        )
        await self._repo.update_investor(
            investor_id=investor_id,
            changes={"invited_at": clock.now()},
            actor_user_id=actor_user_id,
        )
        return self._login_result(await self.get_investor(investor_id=investor_id), result)

    async def set_login_enabled(
        self,
        *,
        investor_id: UUID,
        enabled: bool,
        users: TenantUsersService,
        tenant_id: UUID,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Disable signs the investor out and blocks sign-in; enable undoes it."""
        investor = await self._linked(investor_id)
        if enabled:
            await users.reactivate_user(
                user_id=investor["login_user_id"],
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                tenant_schema=self._schema or "",
            )
            status = "active" if investor["last_app_seen_at"] is not None else "invited"
        else:
            await users.suspend_user(
                user_id=investor["login_user_id"],
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                tenant_schema=self._schema or "",
            )
            status = "suspended"
        await self._repo.update_investor(
            investor_id=investor_id, changes={"status": status}, actor_user_id=actor_user_id
        )
        await self._record(
            "investors.login_enabled" if enabled else "investors.login_disabled",
            actor_user_id=actor_user_id,
            subject_kind="investor",
            subject_id=investor_id,
            details={},
        )
        return await self.get_investor(investor_id=investor_id)

    # ---- Investments overview and farm map -------------------------------

    async def overview(self, *, farm_id: UUID) -> dict[str, Any]:
        """One farm's investments, and a one-line total across all farms."""

        def not_sold(f: dict[str, Any]) -> Decimal:
            return max(Decimal(f["block_area_m2"]) - Decimal(f["area_sold_m2"]), Decimal("0"))

        everything = await self._repo.overview_farms()
        for f in everything:
            f["area_not_sold_m2"] = not_sold(f)
        here = next((f for f in everything if f["farm_id"] == farm_id), None)
        if here is None:
            rows = await self._repo.overview_farms(farm_id=farm_id)
            if not rows:
                raise BlockNotEligibleError("This farm does not exist or is not active.")
            here = rows[0]
            here["area_not_sold_m2"] = not_sold(here)
        return {
            "farm": here,
            "investors": await self._repo.count_investors_in_farm(farm_id=farm_id),
            "recent": await self._repo.recent_ownerships(farm_id=farm_id, limit=10),
            "all_farms": {
                "farms": len(everything),
                "sold": sum(f["sold"] for f in everything),
                "area_sold_m2": sum((Decimal(f["area_sold_m2"]) for f in everything), Decimal("0")),
                "area_not_sold_m2": sum((f["area_not_sold_m2"] for f in everything), Decimal("0")),
            },
        }

    async def farm_map(self, *, farm_id: UUID, geometry: bool = True) -> dict[str, Any]:
        """Blocks and holdings of a farm. ``geometry=False`` leaves every
        ``boundary`` null, for screens that count and sum but draw nothing."""
        blocks = await self._repo.farm_blocks(farm_id=farm_id, geometry=geometry)
        rows = await self._repo.list_holdings(farm_id=farm_id, geometry=geometry)
        holdings = [_shape_holding(r) for r in rows]
        return {"farm_id": farm_id, "blocks": blocks, "holdings": holdings}

    # ---- Investor app (the signed-in investor's own rows) -----------------

    async def _me(
        self, *, user_id: UUID | None, keycloak_subject: str | None, email: str | None
    ) -> dict[str, Any]:
        if user_id is None:
            raise InvestorNotFoundError(UUID(int=0))
        investor = await self._repo.get_investor_by_user(
            user_id=user_id, keycloak_subject=keycloak_subject, email=email
        )
        if investor is None or investor["archived_at"] is not None:
            raise InvestorNotFoundError(UUID(int=0))
        if investor["user_id"] != user_id:
            # Repair an old link to the stable Keycloak id, so the next
            # lookup is a direct match and survives any later re-key.
            await self._repo.update_investor(
                investor_id=investor["id"],
                changes={"user_id": user_id},
                actor_user_id=user_id,
            )
            investor["user_id"] = user_id
        return investor

    async def app_me(
        self, *, user_id: UUID | None, keycloak_subject: str | None, email: str | None = None
    ) -> dict[str, Any]:
        """The signed-in investor. Also marks that they used the app."""
        investor = await self._me(user_id=user_id, keycloak_subject=keycloak_subject, email=email)
        changes: dict[str, Any] = {"last_app_seen_at": clock.now()}
        if investor["status"] == "invited":
            changes["status"] = "active"
        await self._repo.update_investor(
            investor_id=investor["id"], changes=changes, actor_user_id=user_id
        )
        investor = await self.get_investor(investor_id=investor["id"])
        investor["company_name"] = await self._repo.company_name()
        return investor

    async def app_holdings(
        self, *, user_id: UUID | None, keycloak_subject: str | None, email: str | None = None
    ) -> list[dict[str, Any]]:
        investor = await self._me(user_id=user_id, keycloak_subject=keycloak_subject, email=email)
        rows = await self._repo.investor_app_holdings(investor_id=investor["id"])
        return [_with_stage_end(r) for r in rows]

    async def app_holding_activities(
        self,
        *,
        user_id: UUID | None,
        keycloak_subject: str | None,
        holding_id: UUID,
        email: str | None = None,
    ) -> list[dict[str, Any]]:
        """The season's activities on the holding's block, inside the ownership.

        Ownership is checked first, through the same read as the holding, so
        someone else's holding answers 404.
        """
        holding = await self.app_holding(
            user_id=user_id, keycloak_subject=keycloak_subject, email=email, holding_id=holding_id
        )
        window = ownership_window(holding, clock.today())
        if window is None:
            return []
        rows = await self._repo.investor_block_activities(
            block_id=holding["block_id"], from_date=window[0], to_date=window[1]
        )
        storage = get_storage_client()
        out: list[dict[str, Any]] = []
        for row in rows:
            status = _INVESTOR_STATUS.get(row["status"])
            if status is None:
                continue
            photos = []
            for photo in row["photos"] or []:
                url = _photo_link(storage, photo["s3_key"])
                if url:
                    # No thumbnail renditions exist for activity photos yet:
                    # the app scales the same image.
                    photos.append({"thumb_url": url, "url": url, "taken_at": photo["taken_at"]})
            out.append({**row, "status": status, "photos": photos})
        return out

    async def app_holding_site_photo(
        self,
        *,
        user_id: UUID | None,
        keycloak_subject: str | None,
        holding_id: UUID,
        email: str | None = None,
    ) -> dict[str, Any]:
        """The newest photo of the holding's block, up to the end of the ownership."""
        holding = await self.app_holding(
            user_id=user_id, keycloak_subject=keycloak_subject, email=email, holding_id=holding_id
        )
        found = await self._repo.investor_block_site_photo(
            block_id=holding["block_id"], until=holding.get("end_date")
        )
        url = _photo_link(get_storage_client(), found["s3_key"]) if found else None
        return {
            "holding_id": holding_id,
            "photo": {"url": url, "taken_at": found["taken_at"]} if found and url else None,
        }

    async def app_holding_harvest(
        self,
        *,
        user_id: UUID | None,
        keycloak_subject: str | None,
        holding_id: UUID,
        season: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """The holding's share of the block's picks inside the ownership (D1, D2).

        A future holding has none yet; a past one stops at its end date.
        """
        holding = await self.app_holding(
            user_id=user_id, keycloak_subject=keycloak_subject, email=email, holding_id=holding_id
        )
        empty = {"holding_id": holding_id, **scale_harvest([], share=Decimal(0), season=None)}
        if holding["start_date"] > clock.today():
            return empty
        picks = await get_harvest_service(
            tenant_session=self._session, tenant_schema=self._schema or ""
        ).picks_between(
            block_id=holding["block_id"],
            from_date=holding["start_date"],
            to_date=holding.get("end_date"),
        )
        share = harvest_share(
            holding_trees=holding.get("tree_count"),
            block_trees=holding.get("block_plant_count"),
            holding_area_m2=holding.get("area_m2"),
            block_area_m2=holding.get("block_area_m2"),
        )
        return {"holding_id": holding_id, **scale_harvest(picks, share=share, season=season)}

    async def app_holding(
        self,
        *,
        user_id: UUID | None,
        keycloak_subject: str | None,
        holding_id: UUID,
        email: str | None = None,
    ) -> dict[str, Any]:
        investor = await self._me(user_id=user_id, keycloak_subject=keycloak_subject, email=email)
        rows = await self._repo.investor_app_holdings(
            investor_id=investor["id"], holding_id=holding_id
        )
        if not rows:
            # Someone else's holding answers exactly like a missing one.
            raise HoldingNotFoundError(holding_id)
        return _with_stage_end(rows[0])


#: How long an investor's photo link stays valid. Short: the app asks again
#: every time it opens the tab.
INVESTOR_PHOTO_LINK_SECONDS = 600

#: Activity status as the investor sees it. Skipped never gets here (D4).
_INVESTOR_STATUS = {"scheduled": "upcoming", "in_progress": "in_progress", "completed": "completed"}


def season_window(current_season: str | None, today: date) -> tuple[date, date]:
    """The calendar year of the farm's active plan's season, else this year.

    Plans carry a ``season_year`` and no start or end date, so the season is
    that year, January to December.
    """
    digits = "".join(ch for ch in (current_season or "")[:4] if ch.isdigit())
    year = int(digits) if len(digits) == 4 else today.year
    return date(year, 1, 1), date(year, 12, 31)


def ownership_window(holding: dict[str, Any], today: date) -> tuple[date, date] | None:
    """The season clipped to the investor's ownership, or None when they do not meet."""
    season_start, season_end = season_window(holding.get("current_season"), today)
    start = max(season_start, holding["start_date"])
    end = min(season_end, holding["end_date"]) if holding.get("end_date") else season_end
    return (start, end) if start <= end else None


_KG = Decimal("0.01")


def harvest_share(
    *,
    holding_trees: int | None,
    block_trees: int | None,
    holding_area_m2: Decimal | None,
    block_area_m2: Decimal | None,
) -> Decimal:
    """The holding's part of the block's harvest (decision D1).

    By tree count when both the holding and the block have one, otherwise by
    area. Never above 1: a holding cannot own more than its block.
    """
    if holding_trees and block_trees and holding_trees > 0 and block_trees > 0:
        share = Decimal(holding_trees) / Decimal(block_trees)
    elif holding_area_m2 and block_area_m2 and block_area_m2 > 0:
        share = Decimal(holding_area_m2) / Decimal(block_area_m2)
    else:
        share = Decimal(0)
    return min(share, Decimal(1))


def scale_harvest(
    picks: list[dict[str, Any]], *, share: Decimal, season: str | None
) -> dict[str, Any]:
    """The picks of one season, scaled to the holding, with totals (D1, D2)."""
    seasons = sorted({p["season_label"] for p in picks}, reverse=True)
    chosen = season if season in seasons else (seasons[0] if seasons else None)
    out: list[dict[str, Any]] = []
    total_weight = Decimal(0)
    priced_weight = Decimal(0)
    total_revenue = Decimal(0)
    for pick in picks:
        if pick["season_label"] != chosen:
            continue
        weight = (Decimal(pick["weight_kg"]) * share).quantize(_KG, rounding=ROUND_HALF_UP)
        price = pick["price_per_kg"]
        revenue = (
            (weight * Decimal(price)).quantize(_KG, rounding=ROUND_HALF_UP)
            if price is not None
            else None
        )
        total_weight += weight
        if revenue is not None:
            priced_weight += weight
            total_revenue += revenue
        out.append(
            {
                "pick_no": pick["pick_no"],
                "label": pick["label"],
                "label_ar": pick["label_ar"],
                "harvested_on": pick["harvested_on"],
                "weight_kg": weight,
                "price_per_kg": price,
                "revenue": revenue,
            }
        )
    any_price = priced_weight > 0
    return {
        "season": chosen,
        "seasons": seasons,
        "currency": next((p["currency"] for p in picks if p["season_label"] == chosen), None),
        "picks": out,
        "total_weight_kg": total_weight,
        "total_revenue": total_revenue if any_price else None,
        "average_price_per_kg": (
            (total_revenue / priced_weight).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if any_price
            else None
        ),
    }


def _with_stage_end(row: dict[str, Any]) -> dict[str, Any]:
    """Swap the stage's advance rule for the date it is expected to end,
    and the crop image keys for their public URLs."""
    out = dict(row)
    out.update(crop_image_urls(out.pop("crop_image_key", None), out.pop("variety_image_key", None)))
    # The season's stages with their expected dates, and when picking starts.
    stages = season_stages(
        out.pop("stage_list", None), planting_date=out.get("planting_date"), today=clock.today()
    )
    out["stages"] = stages
    out["expected_harvest_on"] = expected_harvest_on(stages)
    advance = out.pop("stage_advance", None)
    out["stage_expected_end"] = (
        stage_expected_end(advance, planting_date=out.get("planting_date"), today=clock.today())
        if out.get("stage_name_en") or out.get("stage_name_ar")
        else None
    )
    return out


def _photo_link(storage: Any, key: str) -> str | None:
    try:
        link: str = storage.presign_download(
            key=key, expires_seconds=INVESTOR_PHOTO_LINK_SECONDS
        ).url
    except Exception as exc:  # one broken link must not break the tab
        _log.warning("investor_photo_link_failed", error=str(exc))
        return None
    return link


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _ineligible_reason(block: dict[str, Any]) -> str | None:
    if block["deleted_at"] is not None or not block["is_active"]:
        return "This block is not active."
    if block["has_children"]:
        return (
            "This block is split into sectors. Draw holdings on a sector, so one "
            "harvest is never counted twice."
        )
    return None


def get_investors_service(
    *, tenant_session: AsyncSession, tenant_schema: str | None
) -> InvestorsService:
    return InvestorsService(tenant_session=tenant_session, tenant_schema=tenant_schema)


# ---- Called by the farms module ------------------------------------------


async def block_holding_conflicts(
    *,
    tenant_session: AsyncSession,
    block_id: UUID,
    new_boundary_ewkt: str | None = None,
    inactivating: bool = False,
) -> None:
    """Raise when a block change would break a holding (rules R6 and R7).

    The farms module calls this before it writes, so the user gets the list
    of holdings in the error. The database triggers stay as the backstop for
    any path that skips this call.
    """
    repo = InvestorsRepository(tenant_session)
    if new_boundary_ewkt is not None:
        codes = await repo.holdings_outside(block_id=block_id, boundary_ewkt=new_boundary_ewkt)
        if codes:
            raise BlockHasHoldingsError(
                "The new boundary leaves these holdings outside the block: "
                + ", ".join(codes)
                + ". Redraw or archive them in Investments > Holdings first.",
                holding_codes=codes,
            )
    if inactivating:
        codes = await repo.owned_holding_codes(block_ids=[block_id])
        if codes:
            raise BlockHasHoldingsError(
                "Investors own these holdings in this block: "
                + ", ".join(codes)
                + ". End their ownership in Investments > Holdings before you "
                "inactivate the block.",
                holding_codes=codes,
            )
