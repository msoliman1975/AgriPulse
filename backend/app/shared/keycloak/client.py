"""Async Keycloak admin-API client used by the tenancy module.

Replaces the manual `kcadm.sh` steps in `docs/runbooks/tenant-onboarding.md`
and `tenant-offboarding.md`. Endpoints touched:

  - POST /realms/{realm}/protocol/openid-connect/token  — service-account
                                                           client_credentials
  - GET / POST /admin/realms/{realm}/groups
  - GET / POST / DELETE /admin/realms/{realm}/users
  - PUT  /admin/realms/{realm}/users/{id}/groups/{gid}
  - POST /admin/realms/{realm}/users/{id}/role-mappings/realm
  - PUT  /admin/realms/{realm}/users/{id}/execute-actions-email
  - PUT  /admin/realms/{realm}/users/{id}  (enable=true|false)

Token caching is per-process; on token expiry we refresh once. The TTL
field comes from Keycloak's response — we subtract 30s of slack so we
never present a freshly-expired token.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.shared.keycloak.errors import (
    KeycloakNotConfiguredError,
    KeycloakRequestError,
)

_TOKEN_REFRESH_SLACK_SECONDS: float = 30.0
_GROUP_NAME_PREFIX: str = "tenant-"


def group_name_for(slug: str) -> str:
    """Return the canonical Keycloak group name for a tenant slug."""
    return f"{_GROUP_NAME_PREFIX}{slug}"


class KeycloakAdminClient(Protocol):
    """Surface area used by tenancy + iam provisioning paths."""

    async def ensure_group(self, slug: str) -> str: ...

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str | None,
        group_id: str,
        roles: tuple[str, ...] = ("TenantOwner",),
        tenant_id: UUID | str | None = None,
    ) -> str: ...

    async def add_existing_user_to_group(
        self,
        *,
        keycloak_user_id: str,
        group_id: str,
        roles: tuple[str, ...] = (),
        tenant_id: UUID | str | None = None,
    ) -> None: ...

    async def disable_users_in_group(self, slug: str) -> int: ...

    async def enable_users_in_group(self, slug: str) -> int: ...

    async def delete_users_and_group(self, slug: str) -> int: ...

    async def disable_user(self, *, keycloak_user_id: str) -> None: ...

    async def enable_user(self, *, keycloak_user_id: str) -> None: ...

    async def delete_user(self, *, keycloak_user_id: str) -> None: ...

    async def invite_platform_admin(
        self,
        *,
        email: str,
        full_name: str | None,
        role: str = "PlatformAdmin",
    ) -> str: ...

    async def set_platform_role(self, *, keycloak_user_id: str, role: str) -> None: ...

    async def clear_platform_role(self, *, keycloak_user_id: str) -> None: ...

    async def aclose(self) -> None: ...


# ---- No-op fallback --------------------------------------------------------


class NoopKeycloakClient:
    """Wired when `keycloak_provisioning_enabled=False`.

    Every method logs a warning and returns a benign placeholder so the
    rest of the tenancy flow still completes. Operators following the
    runbook fallback continue to provision via `kcadm.sh` by hand; the
    tenancy service marks the tenant as `pending_provision` so it shows
    up in admin UI banners and can be completed via the retry endpoint
    once Keycloak is reachable.
    """

    def __init__(self) -> None:
        self._log = get_logger(__name__)

    async def ensure_group(self, slug: str) -> str:
        self._log.warning("keycloak_noop_ensure_group", slug=slug)
        raise KeycloakNotConfiguredError(
            "Keycloak provisioning disabled — set keycloak_provisioning_enabled=true"
        )

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str | None,
        group_id: str,
        roles: tuple[str, ...] = ("TenantOwner",),
        tenant_id: UUID | str | None = None,
    ) -> str:
        del email, full_name, group_id, roles, tenant_id
        raise KeycloakNotConfiguredError(
            "Keycloak provisioning disabled — set keycloak_provisioning_enabled=true"
        )

    async def add_existing_user_to_group(
        self,
        *,
        keycloak_user_id: str,
        group_id: str,
        roles: tuple[str, ...] = (),
        tenant_id: UUID | str | None = None,
    ) -> None:
        del roles, tenant_id
        self._log.warning(
            "keycloak_noop_add_user_to_group",
            keycloak_user_id=keycloak_user_id,
            group_id=group_id,
        )
        raise KeycloakNotConfiguredError(
            "Keycloak provisioning disabled — set keycloak_provisioning_enabled=true"
        )

    async def disable_users_in_group(self, slug: str) -> int:
        self._log.warning("keycloak_noop_disable", slug=slug)
        return 0

    async def enable_users_in_group(self, slug: str) -> int:
        self._log.warning("keycloak_noop_enable", slug=slug)
        return 0

    async def delete_users_and_group(self, slug: str) -> int:
        self._log.warning("keycloak_noop_delete", slug=slug)
        return 0

    async def disable_user(self, *, keycloak_user_id: str) -> None:
        self._log.warning("keycloak_noop_disable_user", keycloak_user_id=keycloak_user_id)

    async def enable_user(self, *, keycloak_user_id: str) -> None:
        self._log.warning("keycloak_noop_enable_user", keycloak_user_id=keycloak_user_id)

    async def delete_user(self, *, keycloak_user_id: str) -> None:
        self._log.warning("keycloak_noop_delete_user", keycloak_user_id=keycloak_user_id)

    async def invite_platform_admin(
        self,
        *,
        email: str,
        full_name: str | None,
        role: str = "PlatformAdmin",
    ) -> str:
        del full_name
        self._log.warning("keycloak_noop_invite_platform_admin", email=email, role=role)
        raise KeycloakNotConfiguredError(
            "Keycloak provisioning disabled — set keycloak_provisioning_enabled=true"
        )

    async def set_platform_role(self, *, keycloak_user_id: str, role: str) -> None:
        self._log.warning(
            "keycloak_noop_set_platform_role",
            keycloak_user_id=keycloak_user_id,
            role=role,
        )

    async def clear_platform_role(self, *, keycloak_user_id: str) -> None:
        self._log.warning("keycloak_noop_clear_platform_role", keycloak_user_id=keycloak_user_id)

    async def aclose(self) -> None:
        return None


# ---- httpx implementation --------------------------------------------------


class HttpxKeycloakAdminClient:
    """Real client. Requires service-account creds in Settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.keycloak_admin_client_secret:
            raise KeycloakNotConfiguredError(
                "keycloak_admin_client_secret is empty — provisioning client cannot start"
            )
        self._token_url = (
            f"{self._settings.keycloak_base_url.rstrip('/')}/realms/"
            f"{self._settings.keycloak_realm}/protocol/openid-connect/token"
        )
        self._admin_base = (
            f"{self._settings.keycloak_base_url.rstrip('/')}/admin/realms/"
            f"{self._settings.keycloak_realm}"
        )
        self._http = httpx.AsyncClient(
            timeout=self._settings.keycloak_admin_request_timeout_seconds
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._log = get_logger(__name__)

    # ---- token plumbing ----------------------------------------------------

    async def _bearer(self) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        async with self._token_lock:
            if self._token is not None and time.monotonic() < self._token_expires_at:
                return self._token
            resp = await self._http.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.keycloak_admin_client_id,
                    "client_secret": self._settings.keycloak_admin_client_secret,
                },
            )
            if resp.status_code >= 400:
                raise KeycloakRequestError(resp.status_code, resp.text, operation="token")
            payload = resp.json()
            self._token = payload["access_token"]
            ttl = float(payload.get("expires_in", 60))
            self._token_expires_at = time.monotonic() + max(0.0, ttl - _TOKEN_REFRESH_SLACK_SECONDS)
            return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        json: dict[str, Any] | list[Any] | None = None,
        params: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 201, 204, 404),
    ) -> httpx.Response:
        token = await self._bearer()
        url = f"{self._admin_base}{path}"
        resp = await self._http.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
        if resp.status_code not in expected:
            raise KeycloakRequestError(resp.status_code, resp.text, operation=operation)
        return resp

    # ---- public API --------------------------------------------------------

    async def ensure_group(self, slug: str) -> str:
        name = group_name_for(slug)
        existing = await self._find_group_id(name)
        if existing is not None:
            return existing

        resp = await self._request(
            "POST",
            "/groups",
            operation="create_group",
            json={"name": name, "attributes": {"tenant_slug": [slug]}},
            expected=(201, 409),
        )
        if resp.status_code == 409:
            # Race with a concurrent create — re-read.
            again = await self._find_group_id(name)
            if again is None:
                raise KeycloakRequestError(409, resp.text, operation="create_group")
            return again

        location = resp.headers.get("location") or resp.headers.get("Location")
        if location and "/" in location:
            return location.rsplit("/", 1)[-1]
        # Fallback: search by name.
        again = await self._find_group_id(name)
        if again is None:
            raise KeycloakRequestError(
                201, "no Location header and lookup miss", operation="create_group"
            )
        return again

    async def invite_user(
        self,
        *,
        email: str,
        full_name: str | None,
        group_id: str,
        roles: tuple[str, ...] = ("TenantOwner",),
        tenant_id: UUID | str | None = None,
    ) -> str:
        # We do NOT pass `groups` in the create body — KC requires the
        # group path, not the id, which makes mistakes easy. Add the user
        # via the explicit users/{id}/groups/{gid} call below.
        first, last = _split_full_name(full_name)
        body: dict[str, Any] = {
            "username": email,
            "email": email,
            "firstName": first,
            "lastName": last,
            "enabled": True,
            "emailVerified": False,
        }
        # Inline tenant_id + tenant_role into the create body so the JWT
        # claims work on first sign-in. We can't PUT them afterwards —
        # Keycloak's PUT /users/{id} treats missing fields as empty and
        # would wipe email/firstName/lastName (mirrors what
        # `invite_platform_admin` does for `platform_role`).
        if tenant_id is not None and roles:
            body["attributes"] = {
                "tenant_id": [str(tenant_id)],
                "tenant_role": [roles[0]],
            }

        resp = await self._request(
            "POST", "/users", operation="create_user", json=body, expected=(201, 409)
        )
        if resp.status_code == 409:
            user_id = await self._find_user_id_by_email(email)
            if user_id is None:
                raise KeycloakRequestError(409, resp.text, operation="create_user")
        else:
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location or "/" not in location:
                # Some KC versions return 201 with no Location for service
                # accounts — fall back to a username search.
                user_id_opt = await self._find_user_id_by_email(email)
                if user_id_opt is None:
                    raise KeycloakRequestError(201, "no Location header", operation="create_user")
                user_id = user_id_opt
            else:
                user_id = location.rsplit("/", 1)[-1]

        await self._request(
            "PUT",
            f"/users/{user_id}/groups/{group_id}",
            operation="add_user_to_group",
            expected=(204,),
        )

        for role in roles:
            await self._assign_realm_role(user_id, role)

        # Best-effort: the user object + group membership + role mapping all
        # exist at this point, which is enough for the tenant to be usable.
        # If the realm has no SMTP configured, or SMTP is transiently down,
        # we don't want to fail the whole provisioning flow — operators can
        # set a password manually in KC admin or fix SMTP and re-trigger
        # the reset. Log the failure so it's traceable.
        try:
            await self._send_password_reset(user_id)
        except KeycloakRequestError as exc:
            self._log.warning(
                "keycloak_password_reset_email_failed",
                user_id=user_id,
                email=email,
                error=str(exc),
            )

        self._log.info("keycloak_invite_user", email=email, user_id=user_id, group_id=group_id)
        return user_id

    async def add_existing_user_to_group(
        self,
        *,
        keycloak_user_id: str,
        group_id: str,
        roles: tuple[str, ...] = (),
        tenant_id: UUID | str | None = None,
    ) -> None:
        # PUT is idempotent in Keycloak — re-adding a user already in
        # the group is a no-op 204.
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}/groups/{group_id}",
            operation="add_existing_user_to_group",
            expected=(204,),
        )
        for role in roles:
            await self._assign_realm_role(keycloak_user_id, role)
        # See invite_user above for why we set tenant_id/tenant_role here.
        if tenant_id is not None and roles:
            await self._set_tenant_attributes(
                keycloak_user_id=keycloak_user_id,
                tenant_id=tenant_id,
                tenant_role=roles[0],
            )
        self._log.info(
            "keycloak_add_existing_user_to_group",
            user_id=keycloak_user_id,
            group_id=group_id,
            roles=list(roles),
        )

    async def disable_users_in_group(self, slug: str) -> int:
        return await self._toggle_users_in_group(slug, enabled=False)

    async def enable_users_in_group(self, slug: str) -> int:
        return await self._toggle_users_in_group(slug, enabled=True)

    async def delete_users_and_group(self, slug: str) -> int:
        name = group_name_for(slug)
        group_id = await self._find_group_id(name)
        if group_id is None:
            return 0
        users = await self._members(group_id)
        for user in users:
            await self._request(
                "DELETE",
                f"/users/{user['id']}",
                operation="delete_user",
                expected=(204, 404),
            )
        await self._request(
            "DELETE",
            f"/groups/{group_id}",
            operation="delete_group",
            expected=(204, 404),
        )
        self._log.info(
            "keycloak_delete_users_and_group",
            slug=slug,
            group_id=group_id,
            user_count=len(users),
        )
        return len(users)

    async def disable_user(self, *, keycloak_user_id: str) -> None:
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}",
            operation="disable_user",
            json={"enabled": False},
            expected=(204,),
        )

    async def enable_user(self, *, keycloak_user_id: str) -> None:
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}",
            operation="enable_user",
            json={"enabled": True},
            expected=(204,),
        )

    async def delete_user(self, *, keycloak_user_id: str) -> None:
        await self._request(
            "DELETE",
            f"/users/{keycloak_user_id}",
            operation="delete_user",
            expected=(204, 404),
        )

    async def invite_platform_admin(
        self,
        *,
        email: str,
        full_name: str | None,
        role: str = "PlatformAdmin",
    ) -> str:
        """Create (or find) a Keycloak user with no tenant group + set
        the `platform_role` user attribute. Mirrors what
        `dev_promote_platform_admin.py` does so the JWT carries the
        platform_role claim on next sign-in.

        The user is also assigned the matching realm role + emailed a
        password-reset link, same as the tenant-side invite path.
        Failures during the password-reset email are logged-and-continued
        (matches the existing posture)."""
        first, last = _split_full_name(full_name)
        body = {
            "username": email,
            "email": email,
            "firstName": first,
            "lastName": last,
            "enabled": True,
            "emailVerified": False,
            "attributes": {"platform_role": [role]},
        }
        resp = await self._request(
            "POST", "/users", operation="create_platform_user", json=body, expected=(201, 409)
        )
        if resp.status_code == 409:
            user_id = await self._find_user_id_by_email(email)
            if user_id is None:
                raise KeycloakRequestError(409, resp.text, operation="create_platform_user")
            # User already exists — just set the attribute.
            await self.set_platform_role(keycloak_user_id=user_id, role=role)
        else:
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location or "/" not in location:
                user_id_opt = await self._find_user_id_by_email(email)
                if user_id_opt is None:
                    raise KeycloakRequestError(
                        201, "no Location header", operation="create_platform_user"
                    )
                user_id = user_id_opt
            else:
                user_id = location.rsplit("/", 1)[-1]

        # Realm role mapping — matches the convention from
        # `dev_bootstrap.py` that platform_role JWT claim is sourced
        # from the user attribute, not from the realm role. The realm
        # role is here for parity with TenantOwner and for any code
        # path that gates on the role itself.
        await self._assign_realm_role(user_id, role)

        try:
            await self._send_password_reset(user_id)
        except KeycloakRequestError as exc:
            self._log.warning(
                "keycloak_password_reset_email_failed",
                user_id=user_id,
                email=email,
                error=str(exc),
            )
        return user_id

    async def set_platform_role(self, *, keycloak_user_id: str, role: str) -> None:
        """Set the `platform_role` user attribute. Idempotent — if
        the attribute already has this value, no observable change."""
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}",
            operation="set_platform_role",
            json={"attributes": {"platform_role": [role]}},
            expected=(204,),
        )

    async def _set_tenant_attributes(
        self,
        *,
        keycloak_user_id: str,
        tenant_id: UUID | str,
        tenant_role: str,
    ) -> None:
        """Set tenant_id + tenant_role user attributes on an existing
        Keycloak user.

        These become JWT claims via the per-client protocol mappers in
        `agripulse-api` (`tenant_id-mapper`, `tenant_role-mapper`). The
        backend auth middleware reads `tenant_role` directly for RBAC,
        so a user without these attributes has no tenant context
        regardless of their `public.tenant_role_assignments` row.

        Implementation note: Keycloak's PUT /users/{id} treats missing
        top-level fields (email/firstName/lastName) as "set to empty",
        so a naive `PUT {"attributes": {...}}` would wipe them. We GET
        first, merge the attributes additively, then PUT the full
        representation. `invite_user` avoids this round-trip by
        inlining attributes into the initial POST body — this helper is
        for the `add_existing_user_to_group` path.
        """
        resp = await self._request(
            "GET",
            f"/users/{keycloak_user_id}",
            operation="set_tenant_attributes_get",
            expected=(200,),
        )
        user = resp.json()
        attrs = dict(user.get("attributes") or {})
        attrs["tenant_id"] = [str(tenant_id)]
        attrs["tenant_role"] = [tenant_role]
        user["attributes"] = attrs
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}",
            operation="set_tenant_attributes",
            json=user,
            expected=(204,),
        )

    async def clear_platform_role(self, *, keycloak_user_id: str) -> None:
        """Remove the `platform_role` user attribute. The user account
        stays — they may still be a tenant user."""
        await self._request(
            "PUT",
            f"/users/{keycloak_user_id}",
            operation="clear_platform_role",
            json={"attributes": {"platform_role": []}},
            expected=(204,),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- helpers -----------------------------------------------------------

    async def _find_group_id(self, name: str) -> str | None:
        resp = await self._request(
            "GET",
            "/groups",
            operation="search_groups",
            params={"search": name, "exact": "true"},
            expected=(200,),
        )
        for entry in resp.json():
            if entry.get("name") == name:
                return entry["id"]
        return None

    async def _find_user_id_by_email(self, email: str) -> str | None:
        resp = await self._request(
            "GET",
            "/users",
            operation="search_users",
            params={"email": email, "exact": "true"},
            expected=(200,),
        )
        rows = resp.json()
        if not rows:
            return None
        return rows[0]["id"]

    async def _members(self, group_id: str) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET",
            f"/groups/{group_id}/members",
            operation="list_group_members",
            params={"max": "500"},
            expected=(200,),
        )
        return list(resp.json())

    async def _toggle_users_in_group(self, slug: str, *, enabled: bool) -> int:
        name = group_name_for(slug)
        group_id = await self._find_group_id(name)
        if group_id is None:
            return 0
        users = await self._members(group_id)
        for user in users:
            await self._request(
                "PUT",
                f"/users/{user['id']}",
                operation="set_user_enabled",
                json={"enabled": enabled},
                expected=(204,),
            )
        return len(users)

    async def _assign_realm_role(self, user_id: str, role_name: str) -> None:
        # Look up the role's representation (id required by the mapping API).
        resp = await self._request(
            "GET",
            f"/roles/{role_name}",
            operation="lookup_role",
            expected=(200, 404),
        )
        if resp.status_code == 404:
            # Fresh realm imports don't ship our application roles
            # (TenantOwner, TenantAdmin, FarmManager, ...). Auto-create on
            # first assignment so the invite flow doesn't silently produce
            # users with no realm role. Subsequent invites find the role
            # via the GET above and skip this path.
            self._log.info(
                "keycloak_role_creating_on_demand",
                role=role_name,
                user_id=user_id,
            )
            await self._request(
                "POST",
                "/roles",
                operation="create_realm_role",
                json={"name": role_name},
                expected=(201, 409),
            )
            resp = await self._request(
                "GET",
                f"/roles/{role_name}",
                operation="lookup_role_after_create",
                expected=(200,),
            )
        role = resp.json()
        await self._request(
            "POST",
            f"/users/{user_id}/role-mappings/realm",
            operation="assign_realm_role",
            json=[{"id": role["id"], "name": role["name"]}],
            expected=(204,),
        )

    async def _send_password_reset(self, user_id: str) -> None:
        params: dict[str, str] = {}
        redirect = self._settings.keycloak_invite_redirect_url
        if redirect:
            params["redirect_uri"] = redirect
        await self._request(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            operation="execute_actions_email",
            json=["UPDATE_PASSWORD"],
            params=params or None,
            expected=(204,),
        )


# ---- Module-level singleton + injection point ----------------------------

_default: KeycloakAdminClient | None = None


def get_keycloak_client() -> KeycloakAdminClient:
    """Return the process-wide Keycloak client, creating it on first call.

    When `keycloak_provisioning_enabled=False` (default), returns a
    `NoopKeycloakClient`. Tests typically override via `set_keycloak_client`.
    """
    global _default
    if _default is not None:
        return _default
    settings = get_settings()
    if not settings.keycloak_provisioning_enabled:
        _default = NoopKeycloakClient()
    else:
        _default = HttpxKeycloakAdminClient(settings)
    return _default


def set_keycloak_client(client: KeycloakAdminClient | None) -> None:
    """Test hook — install or clear the singleton client."""
    global _default
    _default = client


def _split_full_name(full_name: str | None) -> tuple[str, str]:
    if not full_name:
        return "", ""
    parts = full_name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]
