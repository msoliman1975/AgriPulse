"""Assembles the read-only RBAC matrix for the platform admin surface.

The policy itself lives in `app/shared/rbac/*.yaml` and is compiled once into
`CapabilityRegistry`. This module only *reads* that registry and joins it to
per-role holder counts from the public schema; nothing here participates in
an authorization decision.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.rbac.check import (
    WILDCARD,
    CapabilityRegistry,
    get_default_registry,
    role_tier,
)

# One pass over the three assignment tables. All of them live in `public`, so
# this is a plain aggregate — no per-tenant loop and no savepoint dance.
#
# count(DISTINCT user_id) is the point: a FarmManager scoped to five farms has
# five farm_scopes rows but is one person. The membership predicates
# (deleted_at / status) mirror platform_admins/guardrails.py so "who holds this
# role" means the same thing on both screens.
_HOLDER_COUNTS_SQL = text(
    """
    SELECT role, tier, count(DISTINCT user_id) AS holders
    FROM (
        SELECT pra.role AS role, pra.user_id AS user_id, 'platform' AS tier
          FROM public.platform_role_assignments pra
         WHERE pra.revoked_at IS NULL
        UNION ALL
        SELECT tra.role, m.user_id, 'tenant'
          FROM public.tenant_role_assignments tra
          JOIN public.tenant_memberships m ON m.id = tra.membership_id
         WHERE tra.revoked_at IS NULL
           AND m.deleted_at IS NULL
           AND m.status = 'active'
        UNION ALL
        SELECT fs.role, m.user_id, 'farm'
          FROM public.farm_scopes fs
          JOIN public.tenant_memberships m ON m.id = fs.membership_id
         WHERE fs.revoked_at IS NULL
           AND m.deleted_at IS NULL
           AND m.status = 'active'
    ) assignments
    GROUP BY role, tier
    """
)


class CapabilityRow(BaseModel):
    """One capability from capabilities.yaml."""

    model_config = ConfigDict(frozen=True)

    name: str
    #: Noun before the dot, computed server-side so the UI can group without
    #: re-deriving a second source of truth from the name.
    resource: str
    action: str
    description: str
    #: Which JWT layer is *documented* as able to grant this. The resolver
    #: treats it as documentation only — enforcement reads role_capabilities.yaml.
    scope: str
    #: `active` = some route enforces it today. `stub` = reserved for a module
    #: that has not shipped, so granting it has no effect yet.
    status: str


class RoleHolders(BaseModel):
    """Distinct users holding a role, split by the tier they hold it at.

    Split because `Viewer` is defined as a farm role yet public migration 0036
    also permits it in `tenant_role_assignments`; a single merged number would
    quietly conflate the two.
    """

    model_config = ConfigDict(frozen=True)

    total: int = 0
    platform: int = 0
    tenant: int = 0
    farm: int = 0


class RoleRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    #: platform | tenant | farm — the layer the role is *defined* at.
    tier: str
    description: str
    #: True only for PlatformAdmin, whose YAML entry is the literal "*".
    #: `capabilities` is expanded to every known name so the UI can filter and
    #: search uniformly; this flag drives the "grants everything" badge.
    wildcard: bool
    capabilities: list[str]
    capability_count: int
    active_count: int
    stub_count: int
    holders: RoleHolders


class RbacMatrixResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    capabilities: list[CapabilityRow]
    roles: list[RoleRow]
    capability_count: int = Field(description="Total capabilities defined.")
    active_count: int
    stub_count: int


async def _holder_counts(session: AsyncSession) -> dict[str, RoleHolders]:
    rows = (await session.execute(_HOLDER_COUNTS_SQL)).all()
    per_tier: dict[str, dict[str, int]] = {}
    for row in rows:
        per_tier.setdefault(row.role, {})[row.tier] = int(row.holders)
    counts: dict[str, RoleHolders] = {}
    for role, tiers in per_tier.items():
        counts[role] = RoleHolders(
            # Summed rather than a second count(DISTINCT) over the union: the
            # same person holding one role at two tiers is a real distinction
            # here, not a duplicate to collapse.
            total=sum(tiers.values()),
            platform=tiers.get("platform", 0),
            tenant=tiers.get("tenant", 0),
            farm=tiers.get("farm", 0),
        )
    return counts


def _capability_rows(registry: CapabilityRegistry) -> list[CapabilityRow]:
    rows: list[CapabilityRow] = []
    for name, meta in registry.capabilities().items():
        resource, _, action = name.partition(".")
        rows.append(
            CapabilityRow(
                name=name,
                resource=resource,
                action=action,
                description=str(meta.get("description") or "").strip(),
                scope=str(meta.get("scope") or "unknown"),
                status=str(meta.get("status") or "active"),
            )
        )
    rows.sort(key=lambda r: r.name)
    return rows


async def build_matrix(
    session: AsyncSession,
    *,
    registry: CapabilityRegistry | None = None,
) -> RbacMatrixResponse:
    """The whole role x capability matrix in one payload.

    ~10 roles x ~94 capabilities is small enough to send at once, which keeps
    both UI views (by-role and by-capability) entirely client-side.
    """
    registry = registry or get_default_registry()
    capability_rows = _capability_rows(registry)
    status_by_name = {row.name: row.status for row in capability_rows}
    all_names = [row.name for row in capability_rows]
    holders = await _holder_counts(session)

    roles: list[RoleRow] = []
    for name, granted in registry.roles().items():
        wildcard = WILDCARD in granted
        # Expand the wildcard rather than leaking "*" to the client: the UI
        # filters and counts the same way for every role, and `wildcard` alone
        # carries the "this is special" meaning.
        names = all_names if wildcard else sorted(granted)
        roles.append(
            RoleRow(
                name=name,
                tier=role_tier(name),
                description=registry.role_description(name),
                wildcard=wildcard,
                capabilities=names,
                capability_count=len(names),
                active_count=sum(1 for c in names if status_by_name.get(c) == "active"),
                stub_count=sum(1 for c in names if status_by_name.get(c) == "stub"),
                holders=holders.get(name, RoleHolders()),
            )
        )

    tier_order = {"platform": 0, "tenant": 1, "farm": 2}
    roles.sort(key=lambda r: (tier_order.get(r.tier, 9), -r.capability_count, r.name))

    return RbacMatrixResponse(
        generated_at=datetime.now(UTC),
        capabilities=capability_rows,
        roles=roles,
        capability_count=len(capability_rows),
        active_count=sum(1 for r in capability_rows if r.status == "active"),
        stub_count=sum(1 for r in capability_rows if r.status == "stub"),
    )
