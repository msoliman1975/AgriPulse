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

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService, get_audit_service
from app.modules.iam.users_service import TenantUsersService
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
from app.shared import clock
from app.shared.auth.context import TenantRole
from app.shared.db.ids import uuid7

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
        }
        if row["current_ownership_id"] is not None
        else None
    )
    out["share_pct"] = row["share_pct"] if row["share_pct"] is not None else Decimal("0")
    return out


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

    async def create_holding(
        self,
        *,
        farm_id: UUID,
        block_id: UUID,
        payload: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
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
            status=payload.get("status") or "draft",
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
        if changes.get("name") is None:
            changes.pop("name", None)
        if changes.get("status") is None:
            changes.pop("status", None)
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
        result = await users.invite_user(
            email=investor["email"],
            full_name=investor["full_name"],
            full_name_ar=investor["full_name_ar"],
            phone=investor["phone"],
            tenant_role=TenantRole.INVESTOR.value,
            tenant_schema=self._schema or "",
            actor_user_id=actor_user_id,
        )
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

    async def overview(self) -> dict[str, Any]:
        farms = await self._repo.overview_farms()
        for f in farms:
            f["area_not_sold_m2"] = max(
                Decimal(f["block_area_m2"]) - Decimal(f["area_sold_m2"]), Decimal("0")
            )
        return {
            "investors": await self._repo.count_live_investors(),
            "holdings": sum(f["holdings"] for f in farms),
            "sold": sum(f["sold"] for f in farms),
            "for_sale": sum(f["for_sale"] for f in farms),
            "draft": sum(f["draft"] for f in farms),
            "area_sold_m2": sum((Decimal(f["area_sold_m2"]) for f in farms), Decimal("0")),
            "area_not_sold_m2": sum((f["area_not_sold_m2"] for f in farms), Decimal("0")),
            "farms": farms,
            "recent": await self._repo.recent_ownerships(limit=10),
        }

    async def farm_map(self, *, farm_id: UUID) -> dict[str, Any]:
        blocks = await self._repo.farm_blocks(farm_id=farm_id)
        holdings = await self.list_holdings(farm_id=farm_id)
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
        return await self._repo.investor_app_holdings(investor_id=investor["id"])

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
        return rows[0]


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
