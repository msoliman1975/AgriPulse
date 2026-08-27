"""Enrol a field worker who signs in with a phone and a PIN (S-1).

One action, five layers. A scout is not one row: they are a Keycloak user, a
``public.users`` row, a tenant membership, a farm scope, and a ``resources``
worker row linked back through ``membership_id``. Doing that by hand across
five screens is how people end up half-provisioned — able to sign in but
scoped to nothing, or scoped to a farm but invisible on the work board.

The PIN is returned **once**, to be read aloud. It is never stored anywhere
readable: Keycloak holds only its hash, and nothing here writes it down.

Why this lives beside ``users_service`` rather than inside it: the invite flow
is built around an email address as both the identity and the delivery channel.
This path has neither, so sharing it would mean threading "is this person real
or synthetic" through every branch of a function that already handles four
cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.logging import get_logger
from app.shared.keycloak.client import KeycloakAdminClient, get_keycloak_client
from app.shared.keycloak.errors import KeycloakRequestError
from app.shared.keycloak.field_identity import (
    InvalidPhoneNumberError,
    generate_pin,
    is_synthetic_email,
    normalise_phone,
    synthetic_email,
)

_log = get_logger(__name__)


def _worker_brief(row: dict[str, Any]) -> dict[str, Any]:
    """Just enough to act on — the audit is a worklist, not a directory.

    "Enough to act on" means the enrolment call itself: the phone is the
    username, so a UI that could only see ``has_phone`` would have to ask the
    operator to retype a number the farm already recorded, and any typo would
    mint a second account under a different username. ``user_id`` is set only
    for people already enrolled, and is what PIN reissue is keyed on.
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "role": row["role"],
        "phone": row["phone"],
        "has_phone": bool(row["phone"]),
        "user_id": row.get("user_id"),
    }


# Farm roles a field enrolment may grant. Deliberately not the whole FarmRole
# vocabulary: enrolling someone straight into FarmManager from the workers
# screen would be a privilege-escalation path dressed up as a convenience.
ENROLLABLE_ROLES: tuple[str, ...] = ("Scout", "FieldOperator")


@dataclass(frozen=True)
class EnrolmentResult:
    user_id: UUID
    membership_id: UUID
    worker_id: UUID | None
    phone: str
    # Shown once, then gone. Not persisted, not logged, not returned again.
    pin: str


class PhoneAlreadyEnrolledError(APIError):
    def __init__(self, phone: str) -> None:
        super().__init__(
            status_code=409,
            title="Phone already enrolled",
            detail=(
                f"{phone} already has app access in this tenant. "
                "Re-issue their PIN instead of enrolling them again."
            ),
            type_="https://agripulse.cloud/problems/phone-already-enrolled",
        )


class PhoneBelongsToAnotherTenantError(APIError):
    """This number already works somewhere else, and cannot work in two places.

    Separate from ``PhoneAlreadyEnrolledError`` because the fix is different
    and neither message fits the other case. "Re-issue their PIN" is the right
    advice for a number already enrolled *here*; it is wrong here, where the
    account exists but belongs to another tenant and reissuing would hand out
    a PIN for somebody else's worker.

    The other tenant is deliberately not named. A farm manager enrolling a
    crew must not be able to discover which of AgriPulse's customers employs a
    given phone number by typing it into this form.
    """

    def __init__(self, phone: str) -> None:
        super().__init__(
            status_code=409,
            title="Phone already in use",
            detail=(
                f"{phone} already has an AgriPulse account with another "
                "organisation. One person works for one organisation, so this "
                "number cannot be enrolled here. Use a different number, or "
                "ask support to release the account."
            ),
            type_="https://agripulse.cloud/problems/phone-in-another-tenant",
        )


class InvalidEnrolmentError(APIError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=422,
            title="Cannot enrol this worker",
            detail=detail,
            type_="https://agripulse.cloud/problems/invalid-enrolment",
        )


class FieldEnrolmentService:
    def __init__(
        self,
        *,
        public_session: AsyncSession,
        tenant_session: AsyncSession,
        keycloak: KeycloakAdminClient | None = None,
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session
        self._kc = keycloak or get_keycloak_client()

    async def enrol(
        self,
        *,
        tenant_id: UUID,
        tenant_slug: str,
        farm_id: UUID,
        phone: str,
        full_name: str,
        full_name_ar: str | None = None,
        role: str = "Scout",
        worker_id: UUID | None = None,
        language: str = "ar",
        actor_user_id: UUID | None,
    ) -> EnrolmentResult:
        """Give one field worker app access. Returns the PIN to read aloud."""
        if role not in ENROLLABLE_ROLES:
            raise InvalidEnrolmentError(
                f"role must be one of {', '.join(ENROLLABLE_ROLES)}, got {role!r}"
            )
        try:
            phone_e164 = normalise_phone(phone)
        except InvalidPhoneNumberError as exc:
            raise InvalidEnrolmentError(str(exc)) from exc

        email = synthetic_email(phone_e164)
        existing = (
            await self._public.execute(
                text("SELECT id, keycloak_subject FROM public.users WHERE email = :e"),
                {"e": email},
            )
        ).first()

        if existing is not None:
            # One query for both cases, because they differ only in which
            # tenant the live membership sits in and the caller needs to be
            # told apart which one it is. Checking only this tenant — what
            # this did before — let the same phone be enrolled again under
            # another customer, producing the second membership the whole
            # one-tenant rule forbids.
            #
            # Archived memberships do not count: a scout who left one farm
            # business can be taken on by another, and that is the case this
            # `deleted_at IS NULL` keeps open.
            membership = (
                await self._public.execute(
                    text(
                        "SELECT tenant_id FROM public.tenant_memberships "
                        "WHERE user_id = :uid AND status = 'active' "
                        "  AND deleted_at IS NULL "
                        "ORDER BY (tenant_id = :tid) DESC "
                        "LIMIT 1"
                    ).bindparams(
                        bindparam("uid", type_=PG_UUID(as_uuid=True)),
                        bindparam("tid", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"uid": existing.id, "tid": tenant_id},
                )
            ).first()
            if membership is not None:
                if membership.tenant_id == tenant_id:
                    raise PhoneAlreadyEnrolledError(phone_e164)
                raise PhoneBelongsToAnotherTenantError(phone_e164)

        pin = generate_pin()
        # Keycloak first: if it fails there is nothing local to unwind, whereas
        # local rows written before a failed provision leave a user who exists
        # in our tables and cannot sign in — the harder state to notice.
        try:
            group_id = await self._kc.ensure_group(tenant_slug)
            kc_subject = await self._kc.enrol_field_user(
                phone_e164=phone_e164,
                full_name=full_name,
                group_id=group_id,
                pin=pin,
                tenant_id=tenant_id,
            )
        except KeycloakRequestError as exc:
            _log.exception("field_enrolment_keycloak_failed", phone=phone_e164)
            raise APIError(
                status_code=502,
                title="Identity provider unavailable",
                detail="Could not create the sign-in for this worker. Nothing was changed.",
                type_="https://agripulse.cloud/problems/keycloak-unavailable",
            ) from exc

        user_id = existing.id if existing is not None else uuid4()
        if existing is None:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.users
                        (id, keycloak_subject, email, full_name, full_name_ar,
                         phone, status, created_by, updated_by)
                    VALUES (:id, :kc, :email, :name, :name_ar, :phone, 'active',
                            :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "id": user_id,
                    "kc": kc_subject,
                    "email": email,
                    "name": full_name,
                    "name_ar": full_name_ar,
                    # The real identity, stored alongside the synthetic address
                    # so support can find someone by the number they know.
                    "phone": phone_e164,
                    "actor": actor_user_id,
                },
            )

        membership_id = uuid4()
        try:
            await self._public.execute(
                text(
                    """
                    INSERT INTO public.tenant_memberships
                        (id, tenant_id, user_id, status, invited_by, joined_at,
                         created_by, updated_by)
                    VALUES (:id, :tid, :uid, 'active',
                            (SELECT id FROM public.users WHERE id = :actor),
                            now(), :actor, :actor)
                    """
                ).bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                ),
                {"id": membership_id, "tid": tenant_id, "uid": user_id, "actor": actor_user_id},
            )
        except IntegrityError as exc:
            raise PhoneAlreadyEnrolledError(phone_e164) from exc

        # No tenant role: a scout is farm-scoped only. That combination works
        # since PR #269/#270 and is what keeps them out of tenant-wide screens.
        await self._public.execute(
            text(
                """
                INSERT INTO public.farm_scopes (membership_id, farm_id, role, granted_by)
                VALUES (:mid, :fid, :role, (SELECT id FROM public.users WHERE id = :actor))
                """
            ).bindparams(
                bindparam("mid", type_=PG_UUID(as_uuid=True)),
                bindparam("fid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"mid": membership_id, "fid": farm_id, "role": role, "actor": actor_user_id},
        )

        # Push notifications, not email: the address is synthetic and nothing
        # can be delivered to it. Left at the system default, a scout would be
        # opted into a channel that silently goes nowhere.
        await self._public.execute(
            text(
                """
                INSERT INTO public.user_preferences (user_id, language, notification_channels)
                VALUES (:uid, :lang, ARRAY['in_app','push'])
                ON CONFLICT (user_id) DO UPDATE
                   SET notification_channels = EXCLUDED.notification_channels,
                       language = EXCLUDED.language
                """
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id, "lang": language},
        )

        linked_worker = await self._link_worker(
            worker_id=worker_id,
            membership_id=membership_id,
            full_name=full_name,
            full_name_ar=full_name_ar,
            phone=phone_e164,
            role=role,
            farm_id=farm_id,
        )

        # The JWT carries farm_scopes, so without this sync the scout signs in
        # successfully and is then 403 on every farm endpoint. It goes through
        # `_sync_scopes` rather than sending just the farm enrolled here: the
        # same person can already be a scout in another tenant, and the
        # attribute is a full replace.
        await self._sync_scopes(keycloak_subject=kc_subject, membership_id=membership_id)

        _log.info(
            "field_worker_enrolled",
            user_id=str(user_id),
            farm_id=str(farm_id),
            role=role,
            worker_id=str(linked_worker) if linked_worker else None,
        )
        return EnrolmentResult(
            user_id=user_id,
            membership_id=membership_id,
            worker_id=linked_worker,
            phone=phone_e164,
            pin=pin,
        )

    async def audit_workers(self, *, farm_id: UUID | None = None) -> dict[str, Any]:
        """Who on this farm can actually be given the app, and who cannot.

        Worth running before a pilot, because two of these buckets are silent
        failures rather than errors:

        * ``FieldWorker`` is a worker-only role with **no capabilities at all**
          (U-2). Someone recorded that way can be scheduled but can never sign
          in, and nothing tells you so until you try to enrol them.
        * a worker with no ``phone`` cannot be enrolled at all under D7, because
          the phone *is* the username.
        """
        # Availability comes from `resource_farms`, not the vestigial
        # `resources.farm_id` (W2-A). Filtering on the column would have made
        # this audit blind to exactly the drift it now reports: a worker lent
        # to a second farm has a link there and a `farm_id` pointing somewhere
        # else entirely.
        where = "kind = 'worker' AND archived_at IS NULL"
        params: dict[str, Any] = {}
        if farm_id is not None:
            where += (
                " AND EXISTS (SELECT 1 FROM resource_farms rf "
                "             WHERE rf.resource_id = resources.id AND rf.farm_id = :fid)"
            )
            params["fid"] = farm_id
        rows = (
            (
                await self._tenant.execute(
                    text(
                        f"SELECT id, name, role, phone, membership_id FROM resources WHERE {where} "  # noqa: S608
                        "ORDER BY name"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        workers = [dict(r) for r in rows]

        # Resolve the linked membership to a user, because PIN reissue is keyed
        # on the user and a worker row does not carry one. Cross-schema, so it
        # is a second query on the public session rather than a join.
        membership_ids = [w["membership_id"] for w in workers if w["membership_id"] is not None]
        if membership_ids:
            owners = (
                await self._public.execute(
                    text(
                        "SELECT id, user_id FROM public.tenant_memberships "
                        "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                    ),
                    {"ids": membership_ids},
                )
            ).all()
            by_membership = {row.id: row.user_id for row in owners}
            for w in workers:
                w["user_id"] = by_membership.get(w["membership_id"])

        # "Enrolled" means the membership is still ACTIVE, not merely that the
        # column is set. Deleting a user archives the membership and leaves the
        # worker row pointing at it, so testing for NOT NULL reported a deleted
        # scout as enrolled forever — and a supervisor reading the worklist
        # would never re-enrol somebody who cannot sign in. The user lookup
        # above already filters to live memberships, so a resolved user_id is
        # the honest test.
        blocked = [w for w in workers if w["role"] == "FieldWorker"]
        no_phone = [w for w in workers if not w["phone"] and w["role"] != "FieldWorker"]
        enrolled = [w for w in workers if w.get("user_id") is not None]
        ready = [
            w
            for w in workers
            if w.get("user_id") is None and w["phone"] and w["role"] in ENROLLABLE_ROLES
        ]
        return {
            "total": len(workers),
            "enrolled": [_worker_brief(w) for w in enrolled],
            "ready_to_enrol": [_worker_brief(w) for w in ready],
            # Re-role these to Scout first — see re_role_field_workers.
            "blocked_by_role": [_worker_brief(w) for w in blocked],
            "missing_phone": [_worker_brief(w) for w in no_phone],
            "scope_mismatch": [
                _worker_brief(w) for w in await self._scope_mismatches(workers, farm_id=farm_id)
            ],
        }

    async def _scope_mismatches(
        self, workers: list[dict[str, Any]], *, farm_id: UUID | None
    ) -> list[dict[str, Any]]:
        """Enrolled people whose two projections disagree (W2-D).

        ``resource_farms`` says where somebody may be **scheduled**;
        ``farm_scopes`` says where they may **look**. Before the roster went
        tenant-level these could not disagree — enrolment wrote both from one
        ``farm_id``. Now they are independent sets, and a worker available on
        a farm they hold no scope for can be assigned work their sign-in does
        not reach.

        Reported as a bucket rather than an error for the same reason
        ``blocked_by_role`` and ``missing_phone`` are: nothing fails, nothing
        logs, and the first sign is a scout standing in a block looking at an
        empty list.
        """
        linked = [w for w in workers if w["membership_id"] is not None]
        if not linked:
            return []
        rows = (
            await self._public.execute(
                text(
                    "SELECT membership_id, farm_id FROM public.farm_scopes "
                    "WHERE membership_id = ANY(:mids) AND revoked_at IS NULL"
                ),
                {"mids": [w["membership_id"] for w in linked]},
            )
        ).all()
        scoped: dict[Any, set[Any]] = {}
        for membership_id, scoped_farm in rows:
            scoped.setdefault(membership_id, set()).add(scoped_farm)

        out = []
        for worker in linked:
            available = await self._tenant.execute(
                text("SELECT farm_id FROM resource_farms WHERE resource_id = :r").bindparams(
                    bindparam("r", type_=PG_UUID(as_uuid=True))
                ),
                {"r": worker["id"]},
            )
            farms_available = {r.farm_id for r in available.all()}
            farms_scoped = scoped.get(worker["membership_id"], set())
            # Scoped-but-unavailable is benign — they can look and simply have
            # nothing assigned. Available-but-unscoped is the harmful
            # direction, and when the audit is filtered to one farm only that
            # farm's disagreement is this farm manager's problem.
            gap = farms_available - farms_scoped
            if farm_id is not None:
                gap &= {farm_id}
            if gap:
                out.append(worker)
        return out

    async def re_role_field_workers(
        self, *, farm_id: UUID, worker_ids: tuple[UUID, ...], role: str = "Scout"
    ) -> int:
        """Promote worker-only rows into a role that can hold capabilities.

        Scoped to ``FieldWorker`` on purpose: this is a bulk action reached
        from an audit list, and a bulk action that can rewrite *any* role is a
        way to quietly grant Agronomist to a dozen people at once.

        Scoped to one ``farm_id`` for the same reason. The caller's capability
        was checked against that farm, so ids belonging to another farm must
        not be rewritten just because they were posted in the same list —
        otherwise the farm check is decoration.
        """
        if role not in ENROLLABLE_ROLES:
            raise InvalidEnrolmentError(
                f"role must be one of {', '.join(ENROLLABLE_ROLES)}, got {role!r}"
            )
        if not worker_ids:
            return 0
        result = await self._tenant.execute(
            text(
                "UPDATE resources SET role = :role, updated_at = now() "
                "WHERE id = ANY(:ids) AND kind = 'worker' "
                "AND role = 'FieldWorker' AND archived_at IS NULL "
                "AND EXISTS (SELECT 1 FROM resource_farms rf "
                "            WHERE rf.resource_id = resources.id AND rf.farm_id = :fid)"
            ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
            {"role": role, "ids": list(worker_ids), "fid": farm_id},
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def reissue_pin(
        self, *, tenant_id: UUID, user_id: UUID, farm_id: UUID | None = None
    ) -> str:
        """Mint a fresh PIN for a field worker who forgot theirs.

        A PIN cannot be looked up — Keycloak stores only its hash — so recovery
        is replacement. Restricted to synthetic-email users: this must never
        become a way to reset a colleague's real password from the workers
        screen.

        ``farm_id`` is the farm the caller's capability was checked against.
        When it is set the target must hold an active scope on that farm, or a
        farm manager could reset the PIN of any scout in the tenant simply by
        naming their own farm.
        """
        row = (
            await self._public.execute(
                text(
                    """
                    SELECT u.email, u.keycloak_subject
                      FROM public.users u
                      JOIN public.tenant_memberships m ON m.user_id = u.id
                     WHERE u.id = :uid AND m.tenant_id = :tid AND m.status = 'active'
                    """
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            raise InvalidEnrolmentError("no active member of this tenant with that id")
        if farm_id is not None:
            scoped = (
                await self._public.execute(
                    text(
                        """
                        SELECT 1
                          FROM public.farm_scopes fs
                          JOIN public.tenant_memberships m ON m.id = fs.membership_id
                         WHERE m.user_id = :uid AND m.tenant_id = :tid
                           AND fs.farm_id = :fid AND fs.revoked_at IS NULL
                        """
                    ).bindparams(
                        bindparam("uid", type_=PG_UUID(as_uuid=True)),
                        bindparam("tid", type_=PG_UUID(as_uuid=True)),
                        bindparam("fid", type_=PG_UUID(as_uuid=True)),
                    ),
                    {"uid": user_id, "tid": tenant_id, "fid": farm_id},
                )
            ).first()
            if scoped is None:
                raise InvalidEnrolmentError("that person does not have access to this farm")
        if not is_synthetic_email(row.email):
            raise InvalidEnrolmentError(
                "that account signs in with an email address; use the password-reset flow"
            )

        pin = generate_pin()
        try:
            await self._kc.set_field_pin(keycloak_user_id=row.keycloak_subject, pin=pin)
        except KeycloakRequestError as exc:
            raise APIError(
                status_code=502,
                title="Identity provider unavailable",
                detail="Could not set a new PIN. The old one still works.",
                type_="https://agripulse.cloud/problems/keycloak-unavailable",
            ) from exc
        _log.info("field_pin_reissued", user_id=str(user_id))
        return pin

    async def grant_farm_access(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        farm_id: UUID,
        role: str = "Scout",
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Give someone who already has the app access to another farm.

        Adding a farm is not re-enrolment. Before W2-A the roster was
        farm-locked, so the only way to put an existing scout on a second farm
        was to enrol them again — which 409s, because one phone is one
        username and one account. This is the operation that was missing.

        It writes **both projections in one action**, which is the invariant
        the whole promotion turns on: ``farm_scopes`` says where they may
        look, ``resource_farms`` says where they may be scheduled, and the two
        drifting apart is how someone ends up assigned work they cannot open.

        No new PIN and no new identity — the same person, one more place.
        """
        if role not in ENROLLABLE_ROLES:
            raise InvalidEnrolmentError(
                f"role must be one of {', '.join(ENROLLABLE_ROLES)}, got {role!r}"
            )
        member = (
            await self._public.execute(
                text(
                    """
                    SELECT m.id AS membership_id, u.keycloak_subject
                      FROM public.tenant_memberships m
                      JOIN public.users u ON u.id = m.user_id
                     WHERE m.user_id = :uid AND m.tenant_id = :tid
                       AND m.status = 'active' AND m.deleted_at IS NULL
                    """
                ).bindparams(
                    bindparam("uid", type_=PG_UUID(as_uuid=True)),
                    bindparam("tid", type_=PG_UUID(as_uuid=True)),
                ),
                {"uid": user_id, "tid": tenant_id},
            )
        ).first()
        if member is None:
            raise InvalidEnrolmentError("no active member of this tenant with that id")

        # Scope first. Idempotent via the partial-unique on active scopes —
        # re-granting a farm somebody already has must not raise.
        await self._public.execute(
            text(
                """
                INSERT INTO public.farm_scopes (membership_id, farm_id, role, granted_by)
                SELECT :mid, :fid, :role, :actor
                 WHERE NOT EXISTS (
                       SELECT 1 FROM public.farm_scopes
                        WHERE membership_id = :mid AND farm_id = :fid AND revoked_at IS NULL
                 )
                """
            ).bindparams(
                bindparam("mid", type_=PG_UUID(as_uuid=True)),
                bindparam("fid", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {"mid": member.membership_id, "fid": farm_id, "role": role, "actor": actor_user_id},
        )

        # Then availability, on the worker row this membership already owns.
        worker = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM resources WHERE membership_id = :mid "
                    "AND kind = 'worker' AND archived_at IS NULL LIMIT 1"
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": member.membership_id},
            )
        ).first()
        if worker is not None:
            await self._link_worker_to_farm(worker_id=worker.id, farm_id=farm_id)

        # The JWT carries farm_scopes, so without this they hold the grant in
        # Postgres and 403 on the new farm until something else re-syncs.
        await self._sync_scopes(
            keycloak_subject=member.keycloak_subject, membership_id=member.membership_id
        )
        _log.info(
            "field_farm_access_granted",
            user_id=str(user_id),
            farm_id=str(farm_id),
            role=role,
        )
        return {
            "user_id": user_id,
            "membership_id": member.membership_id,
            "farm_id": farm_id,
            "role": role,
            "worker_id": worker.id if worker is not None else None,
        }

    async def _sync_scopes(self, *, keycloak_subject: str | None, membership_id: UUID) -> None:
        """Re-project the *user's* active scopes into Keycloak.

        `set_farm_scopes` replaces the whole attribute, and the attribute is
        per-user, not per-membership. Rebuilding it from one membership's rows
        therefore deletes every scope the person holds in their other tenants:
        they keep the grant in Postgres, the JWT loses it, and the app 403s on
        a farm the database still says they hold. So the query starts from the
        user behind `membership_id` and walks back out to all of their active
        memberships.
        """
        if not keycloak_subject or keycloak_subject.startswith("pending::"):
            return
        rows = (
            await self._public.execute(
                text(
                    """
                    SELECT DISTINCT fs.farm_id, fs.role
                      FROM public.tenant_memberships m0
                      JOIN public.tenant_memberships m ON m.user_id = m0.user_id
                      JOIN public.farm_scopes fs ON fs.membership_id = m.id
                     WHERE m0.id = :mid
                       AND fs.revoked_at IS NULL
                       AND m.deleted_at IS NULL
                       AND m.status = 'active'
                    """
                ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
                {"mid": membership_id},
            )
        ).all()
        try:
            await self._kc.set_farm_scopes(
                keycloak_user_id=keycloak_subject,
                scopes=[{"farm_id": str(r.farm_id), "role": str(r.role)} for r in rows],
            )
        except KeycloakRequestError:
            _log.exception("field_scope_sync_failed", membership_id=str(membership_id))

    async def _link_worker(
        self,
        *,
        worker_id: UUID | None,
        membership_id: UUID,
        full_name: str,
        full_name_ar: str | None,
        phone: str,
        role: str,
        farm_id: UUID,
    ) -> UUID | None:
        """Attach the login to a ``resources`` worker row (U-3).

        Without this the person can sign in but does not exist on the work
        board, so nobody can assign them anything — the half-provisioned state
        this whole method exists to prevent.

        Since W2-A the roster is tenant-level, so this also writes the
        ``resource_farms`` link. A worker row with no link is available on no
        farm at all: they would sign in, hold a farm scope, and still be
        invisible to every board.
        """
        if worker_id is not None:
            # The farm check this had been missing. The error text always said
            # "on this farm" while the query never looked, so enrolling onto
            # farm A could adopt farm B's worker row — producing exactly the
            # scope/availability mismatch the audit now reports.
            result = await self._tenant.execute(
                text(
                    "UPDATE resources SET membership_id = :mid, updated_at = now() "
                    "WHERE id = :wid AND kind = 'worker' AND archived_at IS NULL "
                    "  AND EXISTS (SELECT 1 FROM resource_farms rf "
                    "               WHERE rf.resource_id = resources.id AND rf.farm_id = :fid)"
                ).bindparams(
                    bindparam("mid", type_=PG_UUID(as_uuid=True)),
                    bindparam("wid", type_=PG_UUID(as_uuid=True)),
                    bindparam("fid", type_=PG_UUID(as_uuid=True)),
                ),
                {"mid": membership_id, "wid": worker_id, "fid": farm_id},
            )
            if not (getattr(result, "rowcount", 0) or 0):
                raise InvalidEnrolmentError(
                    "that worker does not exist on this farm, or is archived"
                )
            return worker_id

        new_id = uuid4()
        await self._tenant.execute(
            text(
                """
                INSERT INTO resources
                    (id, kind, name, name_ar, role, phone, membership_id)
                VALUES (:id, 'worker', :name, :name_ar, :role, :phone, :mid)
                """
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("mid", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": new_id,
                "name": full_name,
                "name_ar": full_name_ar,
                "role": role,
                "phone": phone,
                "mid": membership_id,
            },
        )
        await self._link_worker_to_farm(worker_id=new_id, farm_id=farm_id)
        return new_id

    async def _link_worker_to_farm(self, *, worker_id: UUID, farm_id: UUID) -> None:
        """Make the worker available on this farm (W2-A).

        Idempotent: enrolling somebody onto a farm they already serve is a
        no-op rather than a constraint violation, which is what makes
        ``grant_farm_access`` safe to retry.
        """
        await self._tenant.execute(
            text(
                "INSERT INTO resource_farms (resource_id, farm_id) VALUES (:r, :f) "
                "ON CONFLICT DO NOTHING"
            ).bindparams(
                bindparam("r", type_=PG_UUID(as_uuid=True)),
                bindparam("f", type_=PG_UUID(as_uuid=True)),
            ),
            {"r": worker_id, "f": farm_id},
        )


def get_field_enrolment_service(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession,
    keycloak: KeycloakAdminClient | None = None,
) -> FieldEnrolmentService:
    return FieldEnrolmentService(
        public_session=public_session, tenant_session=tenant_session, keycloak=keycloak
    )


__all__ = [
    "ENROLLABLE_ROLES",
    "EnrolmentResult",
    "FieldEnrolmentService",
    "InvalidEnrolmentError",
    "PhoneAlreadyEnrolledError",
    "PhoneBelongsToAnotherTenantError",
    "get_field_enrolment_service",
]
