"""The RBAC matrix for the platform admin surface: read, and now write.

The *baseline* policy lives in `app/shared/rbac/*.yaml` and is compiled once
into `CapabilityRegistry`. Runtime deltas live in
`public.rbac_role_capability_overrides` and are cached by
`app/shared/rbac/overlay.py`; this module reads the merged result and is the
only place that writes the deltas.

Nothing here participates in an authorization decision — `role_grants` in
`shared/rbac/check.py` remains the single resolver. This module reads the same
registry the resolver reads, so the admin screen cannot disagree with
enforcement about what is currently in force.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.shared.rbac.check import (
    WILDCARD,
    CapabilityRegistry,
    get_default_registry,
    role_tier,
)
from app.shared.rbac.overlay import IMMUTABLE_ROLES
from app.shared.rbac.overlay import TTL_SECONDS as OVERLAY_TTL_SECONDS

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


class OverrideRow(BaseModel):
    """One runtime delta against the YAML baseline.

    Only ever present when it *differs* from the baseline — `set_override`
    deletes rather than storing a row that agrees (see `apply_override`), so
    the UI can treat "has an override" and "modified from default" as the same
    thing without re-deriving the baseline.
    """

    model_config = ConfigDict(frozen=True)

    capability: str
    granted: bool
    note: str | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None


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
    #: **Effective** grants — baseline merged with any override. This is what
    #: the resolver would answer right now, not what the YAML says.
    capabilities: list[str]
    capability_count: int
    active_count: int
    stub_count: int
    holders: RoleHolders
    #: Deltas only. Empty for a role left at its shipped defaults.
    overrides: list[OverrideRow] = Field(default_factory=list)
    #: True when this role's grants can never be edited (PlatformAdmin).
    immutable: bool = False


class RbacMatrixResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    capabilities: list[CapabilityRow]
    roles: list[RoleRow]
    capability_count: int = Field(description="Total capabilities defined.")
    active_count: int
    stub_count: int
    #: Whether *this caller* may edit. Sent so the UI does not have to resolve
    #: `platform.manage_rbac` itself to decide between the read and edit views.
    can_manage: bool = False
    #: Upper bound, in seconds, on how long a change takes to reach every API
    #: pod. Sent rather than hardcoded in the UI so the number the admin is
    #: promised is the same constant the cache actually uses.
    propagation_seconds: int = 30


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


async def _overrides_by_role(session: AsyncSession) -> dict[str, list[OverrideRow]]:
    """Current deltas, straight from the table rather than the cached overlay.

    Read from the database on purpose: the overlay snapshot may be up to its
    TTL out of date, and an admin screen that showed a stale copy of the very
    rows it edits would be maddening. Enforcement reads the cache; this screen
    reads the truth.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT role, capability, granted, note, updated_at, updated_by
                  FROM public.rbac_role_capability_overrides
                 ORDER BY role, capability
                """
            )
        )
    ).all()
    out: dict[str, list[OverrideRow]] = {}
    for row in rows:
        # PlatformAdmin rows are ignored by the resolver (see overlay
        # IMMUTABLE_ROLES); hiding them here too keeps the screen honest about
        # what is actually in force.
        if row.role in IMMUTABLE_ROLES:
            continue
        out.setdefault(row.role, []).append(
            OverrideRow(
                capability=row.capability,
                granted=bool(row.granted),
                note=row.note,
                updated_at=row.updated_at,
                updated_by=row.updated_by,
            )
        )
    return out


async def build_matrix(
    session: AsyncSession,
    *,
    registry: CapabilityRegistry | None = None,
    can_manage: bool = False,
) -> RbacMatrixResponse:
    """The whole role x capability matrix in one payload.

    ~10 roles x ~94 capabilities is small enough to send at once, which keeps
    both UI views (by-role and by-capability) entirely client-side.

    Grants are **effective**: the YAML baseline merged with the overrides.

    The merge is done here against the rows just read from the database, not by
    calling `registry.role_grants`, which answers from a snapshot that may be
    up to a TTL old. Mixing the two would let this page contradict itself —
    a row flagged "modified" while its granted marker still showed the old
    value — because `overrides` below is always current. Enforcement converges
    within `propagation_seconds`, which the UI states.
    """
    registry = registry or get_default_registry()
    capability_rows = _capability_rows(registry)
    status_by_name = {row.name: row.status for row in capability_rows}
    all_names = [row.name for row in capability_rows]
    holders = await _holder_counts(session)
    overrides = await _overrides_by_role(session)
    stored: dict[str, dict[str, bool]] = {
        role: {o.capability: o.granted for o in rows} for role, rows in overrides.items()
    }

    def effective(role: str, capability: str) -> bool:
        decided = stored.get(role, {}).get(capability)
        if decided is not None:
            return decided
        return registry.baseline_grants(role, capability)

    roles: list[RoleRow] = []
    for name, granted in registry.roles().items():
        wildcard = WILDCARD in granted
        # Expand the wildcard rather than leaking "*" to the client: the UI
        # filters and counts the same way for every role, and `wildcard` alone
        # carries the "this is special" meaning.
        #
        # For every other role, resolve per capability instead of reusing the
        # compiled baseline set — that is what makes an override visible here.
        names = all_names if wildcard else [c for c in all_names if effective(name, c)]
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
                overrides=overrides.get(name, []),
                immutable=name in IMMUTABLE_ROLES,
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
        can_manage=can_manage,
        propagation_seconds=int(OVERLAY_TTL_SECONDS),
    )


# ---------- Writes -------------------------------------------------------


class ChangeLogRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    role: str
    capability: str
    #: grant | revoke | reset
    action: str
    previous_effective: bool
    new_effective: bool
    changed_by: UUID | None = None
    changed_by_email: str | None = None
    note: str | None = None
    changed_at: datetime


class OverrideResult(BaseModel):
    """What the write endpoints hand back, so the UI need not re-fetch."""

    model_config = ConfigDict(frozen=True)

    role: str
    capability: str
    baseline: bool
    effective: bool
    overridden: bool
    action: str
    #: True when the request was a no-op (the effective answer did not move).
    unchanged: bool = False


def _unprocessable(detail: str, **extras: object) -> APIError:
    return APIError(
        status_code=422,
        title="Invalid RBAC change",
        detail=detail,
        type_="https://agripulse.cloud/problems/rbac/invalid-change",
        extras=dict(extras),
    )


def validate_target(role: str, capability: str, registry: CapabilityRegistry) -> None:
    """Reject anything the resolver could never act on, naming the offender.

    Three refusals, in the order an admin is most likely to trip them:

      - an unknown role, which would write a row no resolver reads;
      - an unknown capability, same;
      - `PlatformAdmin`, which is immutable. This is the **second** of the two
        server-side guards — `overlay._load` drops such rows even if one is
        inserted directly into the database. Both exist because a single guard
        on a lock-yourself-out path is one bug away from unrecoverable.
    """
    if role in IMMUTABLE_ROLES:
        raise _unprocessable(
            f"{role} grants every capability and cannot be edited. "
            "Removing its permissions could lock every administrator out of "
            "this page, so the server refuses regardless of the UI.",
            role=role,
        )
    if role not in registry.roles():
        raise _unprocessable(f"Unknown role: {role!r}.", role=role)
    if not registry.known(capability):
        raise _unprocessable(f"Unknown capability: {capability!r}.", capability=capability)


async def _current_override(session: AsyncSession, *, role: str, capability: str) -> bool | None:
    """The stored delta for this pair, or None if there is none.

    Read from the table, not from `registry.role_grants`: the resolver answers
    from a snapshot that can be up to a TTL old, and an audit trail that
    recorded a stale "previous" value would be worse than no trail at all.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT granted FROM public.rbac_role_capability_overrides
                 WHERE role = :role AND capability = :capability
                """
            ),
            {"role": role, "capability": capability},
        )
    ).first()
    return None if row is None else bool(row.granted)


async def _record_change(
    session: AsyncSession,
    *,
    role: str,
    capability: str,
    action: str,
    previous_effective: bool,
    new_effective: bool,
    actor_id: UUID | None,
    actor_email: str | None,
    note: str | None,
) -> None:
    """Append to `rbac_change_log`.

    Not `AuditService`: `audit_events` lives in the per-tenant schema and a
    platform-wide policy change has no tenant to attribute itself to. This log
    is also the *only* durable trace of a reset, which deletes its override row.
    """
    await session.execute(
        text(
            """
            INSERT INTO public.rbac_change_log
                   (role, capability, action, previous_effective, new_effective,
                    changed_by, changed_by_email, note)
            VALUES (:role, :capability, :action, :prev, :new,
                    :actor, :actor_email, :note)
            """
        ),
        {
            "role": role,
            "capability": capability,
            "action": action,
            "prev": previous_effective,
            "new": new_effective,
            "actor": actor_id,
            "actor_email": actor_email,
            "note": note,
        },
    )


async def apply_override(
    session: AsyncSession,
    *,
    role: str,
    capability: str,
    granted: bool,
    actor_id: UUID | None,
    actor_email: str | None,
    note: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> OverrideResult:
    """Set `role` -> `capability` to `granted`, or clear the delta if it agrees.

    An override that matches the baseline is stored as *no override at all*.
    That keeps one invariant the whole UI leans on — "has an override" means
    exactly "differs from the shipped default" — and it means an admin who
    toggles a permission back by hand gets the same state as pressing Reset.
    """
    registry = registry or get_default_registry()
    validate_target(role, capability, registry)

    baseline = registry.baseline_grants(role, capability)
    stored = await _current_override(session, role=role, capability=capability)
    previous = baseline if stored is None else stored

    if granted == baseline:
        # Agrees with the shipped default — this is a reset, however it was
        # phrased. Fall through to the delete path so both routes converge.
        return await clear_override(
            session,
            role=role,
            capability=capability,
            actor_id=actor_id,
            actor_email=actor_email,
            note=note,
            registry=registry,
        )

    await session.execute(
        text(
            """
            INSERT INTO public.rbac_role_capability_overrides
                   (role, capability, granted, note, updated_by, updated_at)
            VALUES (:role, :capability, :granted, :note, :actor, now())
            ON CONFLICT ON CONSTRAINT uq_rbac_override_role_capability
            DO UPDATE SET granted = EXCLUDED.granted,
                          note = EXCLUDED.note,
                          updated_by = EXCLUDED.updated_by,
                          updated_at = now()
            """
        ),
        {
            "role": role,
            "capability": capability,
            "granted": granted,
            "note": note,
            "actor": actor_id,
        },
    )

    if previous != granted:
        await _record_change(
            session,
            role=role,
            capability=capability,
            action="grant" if granted else "revoke",
            previous_effective=previous,
            new_effective=granted,
            actor_id=actor_id,
            actor_email=actor_email,
            note=note,
        )

    return OverrideResult(
        role=role,
        capability=capability,
        baseline=baseline,
        effective=granted,
        overridden=True,
        action="grant" if granted else "revoke",
        unchanged=previous == granted,
    )


async def clear_override(
    session: AsyncSession,
    *,
    role: str,
    capability: str,
    actor_id: UUID | None,
    actor_email: str | None,
    note: str | None = None,
    registry: CapabilityRegistry | None = None,
) -> OverrideResult:
    """Delete the delta so the YAML baseline applies again."""
    registry = registry or get_default_registry()
    validate_target(role, capability, registry)

    baseline = registry.baseline_grants(role, capability)

    # RETURNING rather than rowcount: it says both *whether* a row existed and
    # what it held, in one statement, and it is the DB's answer rather than the
    # cache's.
    removed = (
        await session.execute(
            text(
                """
                DELETE FROM public.rbac_role_capability_overrides
                 WHERE role = :role AND capability = :capability
                RETURNING granted
                """
            ),
            {"role": role, "capability": capability},
        )
    ).first()
    previous = baseline if removed is None else bool(removed.granted)

    # Log only a real reset. A DELETE that removed nothing is an idempotent
    # retry, and filling the trail with those would bury the real entries.
    if removed is not None:
        await _record_change(
            session,
            role=role,
            capability=capability,
            action="reset",
            previous_effective=previous,
            new_effective=baseline,
            actor_id=actor_id,
            actor_email=actor_email,
            note=note,
        )

    return OverrideResult(
        role=role,
        capability=capability,
        baseline=baseline,
        effective=baseline,
        overridden=False,
        action="reset",
        unchanged=previous == baseline,
    )


async def list_changes(session: AsyncSession, *, limit: int = 200) -> list[ChangeLogRow]:
    """The change trail, newest first."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, role, capability, action, previous_effective,
                       new_effective, changed_by, changed_by_email, note, changed_at
                  FROM public.rbac_change_log
                 ORDER BY changed_at DESC, id DESC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).all()
    return [
        ChangeLogRow(
            id=row.id,
            role=row.role,
            capability=row.capability,
            action=row.action,
            previous_effective=bool(row.previous_effective),
            new_effective=bool(row.new_effective),
            changed_by=row.changed_by,
            changed_by_email=row.changed_by_email,
            note=row.note,
            changed_at=row.changed_at,
        )
        for row in rows
    ]
