"""In-memory KeycloakAdminClient for tests.

Behaves enough like the real client that tenancy/IAM tests can assert on
state (groups, users, role assignments) without standing up a real
Keycloak. Inject via:

    from app.shared.keycloak import FakeKeycloakClient, set_keycloak_client
    fake = FakeKeycloakClient()
    set_keycloak_client(fake)

`fail_on` is the trapdoor for testing the `pending_provision` recovery
path: set ``fake.fail_on = "ensure_group"`` (or another method name) to
force the next call to raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.shared.keycloak.client import group_name_for
from app.shared.keycloak.errors import KeycloakRequestError


@dataclass
class FakeUser:
    id: str
    email: str
    full_name: str | None
    enabled: bool = True
    actions_emailed: tuple[str, ...] = ()
    realm_roles: tuple[str, ...] = ()
    platform_role: str | None = None


@dataclass
class FakeGroup:
    id: str
    name: str
    slug: str
    member_ids: list[str] = field(default_factory=list)


class FakeKeycloakClient:
    """In-memory client. State persists across calls for the test's lifetime."""

    def __init__(self) -> None:
        self.groups: dict[str, FakeGroup] = {}  # group_id -> FakeGroup
        self.users: dict[str, FakeUser] = {}  # user_id -> FakeUser
        self._closed = False
        # A method name; the next call to that method raises once.
        self.fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            self.fail_on = None
            raise KeycloakRequestError(500, "fake forced failure", operation=name)

    async def ensure_group(self, slug: str) -> str:
        self._maybe_fail("ensure_group")
        for grp in self.groups.values():
            if grp.slug == slug:
                return grp.id
        gid = uuid4().hex
        self.groups[gid] = FakeGroup(id=gid, name=group_name_for(slug), slug=slug)
        return gid

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str | None,
        group_id: str,
        roles: tuple[str, ...] = ("TenantOwner",),
    ) -> str:
        self._maybe_fail("invite_user")
        if group_id not in self.groups:
            raise KeycloakRequestError(404, "group not found", operation="invite_user")
        # Idempotency: if user already exists by email, reuse.
        for user in self.users.values():
            if user.email == email:
                self.groups[group_id].member_ids.append(user.id)
                user.realm_roles = tuple(set(user.realm_roles).union(roles))
                user.actions_emailed = tuple(
                    set(user.actions_emailed).union({"UPDATE_PASSWORD"})
                )
                return user.id
        uid = uuid4().hex
        self.users[uid] = FakeUser(
            id=uid,
            email=email,
            full_name=full_name,
            enabled=True,
            actions_emailed=("UPDATE_PASSWORD",),
            realm_roles=tuple(roles),
        )
        self.groups[group_id].member_ids.append(uid)
        return uid

    async def add_existing_user_to_group(
        self,
        *,
        keycloak_user_id: str,
        group_id: str,
        roles: tuple[str, ...] = (),
    ) -> None:
        self._maybe_fail("add_existing_user_to_group")
        if group_id not in self.groups:
            raise KeycloakRequestError(
                404, "group not found", operation="add_existing_user_to_group"
            )
        if keycloak_user_id not in self.users:
            raise KeycloakRequestError(
                404, "user not found", operation="add_existing_user_to_group"
            )
        members = self.groups[group_id].member_ids
        if keycloak_user_id not in members:
            members.append(keycloak_user_id)
        if roles:
            user = self.users[keycloak_user_id]
            user.realm_roles = tuple(set(user.realm_roles).union(roles))

    async def disable_users_in_group(self, slug: str) -> int:
        self._maybe_fail("disable_users_in_group")
        return self._toggle_users_in_group(slug, enabled=False)

    async def enable_users_in_group(self, slug: str) -> int:
        self._maybe_fail("enable_users_in_group")
        return self._toggle_users_in_group(slug, enabled=True)

    async def delete_users_and_group(self, slug: str) -> int:
        self._maybe_fail("delete_users_and_group")
        for gid, grp in list(self.groups.items()):
            if grp.slug != slug:
                continue
            for uid in list(grp.member_ids):
                self.users.pop(uid, None)
            count = len(grp.member_ids)
            self.groups.pop(gid)
            return count
        return 0

    async def disable_user(self, *, keycloak_user_id: str) -> None:
        self._maybe_fail("disable_user")
        user = self.users.get(keycloak_user_id)
        if user is not None:
            user.enabled = False

    async def enable_user(self, *, keycloak_user_id: str) -> None:
        self._maybe_fail("enable_user")
        user = self.users.get(keycloak_user_id)
        if user is not None:
            user.enabled = True

    async def delete_user(self, *, keycloak_user_id: str) -> None:
        self._maybe_fail("delete_user")
        self.users.pop(keycloak_user_id, None)
        for grp in self.groups.values():
            if keycloak_user_id in grp.member_ids:
                grp.member_ids.remove(keycloak_user_id)

    async def invite_platform_admin(
        self,
        *,
        email: str,
        full_name: str | None,
        role: str = "PlatformAdmin",
    ) -> str:
        self._maybe_fail("invite_platform_admin")
        for user in self.users.values():
            if user.email == email:
                user.platform_role = role
                user.realm_roles = tuple(set(user.realm_roles) | {role})
                return user.id
        uid = uuid4().hex
        self.users[uid] = FakeUser(
            id=uid,
            email=email,
            full_name=full_name,
            enabled=True,
            actions_emailed=("UPDATE_PASSWORD",),
            realm_roles=(role,),
            platform_role=role,
        )
        return uid

    async def set_platform_role(
        self, *, keycloak_user_id: str, role: str
    ) -> None:
        self._maybe_fail("set_platform_role")
        user = self.users.get(keycloak_user_id)
        if user is not None:
            user.platform_role = role

    async def clear_platform_role(self, *, keycloak_user_id: str) -> None:
        self._maybe_fail("clear_platform_role")
        user = self.users.get(keycloak_user_id)
        if user is not None:
            user.platform_role = None

    async def aclose(self) -> None:
        self._closed = True

    def _toggle_users_in_group(self, slug: str, *, enabled: bool) -> int:
        for grp in self.groups.values():
            if grp.slug != slug:
                continue
            for uid in grp.member_ids:
                user = self.users.get(uid)
                if user is not None:
                    user.enabled = enabled
            return len(grp.member_ids)
        return 0
