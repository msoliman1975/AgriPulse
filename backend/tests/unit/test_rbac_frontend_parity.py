"""The frontend RBAC mirror must equal the backend YAML.

`frontend/src/rbac/capabilities.ts` restates the capability list and the
role -> capability mapping so `useCapability` can resolve locally from JWT
claims without a round trip. Nothing generated it and nothing checked it, and
it had drifted in both directions at once:

  * 30 of 94 capabilities were missing from the union;
  * `BillingAdmin` had no entry at all, so every one of its grants resolved
    to `false` and the role saw no controls whatsoever;
  * four grants existed only on the frontend (`Agronomist` -> `plan.manage`
    and `alert_rule.manage`, `FarmManager` -> `alert_rule.manage`,
    `PlatformSupport` -> `irrigation.schedule.read`), rendering controls that
    403 the moment anyone clicked them.

Both directions are silent: a missing grant hides a control the user is
entitled to, and an extra grant shows one the API refuses. Neither produces a
type error or a failing render, which is why this test exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.shared.rbac.check import WILDCARD

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIRROR = _REPO_ROOT / "frontend" / "src" / "rbac" / "capabilities.ts"
_RBAC_DIR = Path(__file__).resolve().parents[2] / "app" / "shared" / "rbac"

pytestmark = pytest.mark.skipif(
    not _MIRROR.exists(),
    reason="frontend/ is absent (backend-only checkout or Docker build context)",
)


def _backend() -> tuple[set[str], dict[str, set[str]]]:
    caps = yaml.safe_load((_RBAC_DIR / "capabilities.yaml").read_text(encoding="utf-8"))
    roles = yaml.safe_load((_RBAC_DIR / "role_capabilities.yaml").read_text(encoding="utf-8"))
    return (
        set(caps["capabilities"]),
        {name: set(body.get("capabilities") or []) for name, body in roles["roles"].items()},
    )


def _mirror() -> tuple[set[str], dict[str, set[str]]]:
    source = _MIRROR.read_text(encoding="utf-8")

    union_block = source.split("export type Capability =", 1)[1].split(";", 1)[0]
    union = set(re.findall(r'"([^"]+)"', union_block))

    roles_block = source.split("ROLE_CAPABILITIES", 1)[1].split("\n};", 1)[0]
    # Only the literal `new Set([...])` form is recognised. That is deliberate:
    # the previous file built TenantOwner/TenantAdmin from a shared
    # `tenantWideCaps()` helper, which made their real grants invisible to any
    # static check. Reintroducing a helper makes the role read as absent and
    # fails loudly rather than silently passing.
    grants: dict[str, set[str]] = {}
    for match in re.finditer(r"^  (\w+): new Set<[^>]*>\(\[(.*?)\]\),", roles_block, re.S | re.M):
        grants[match.group(1)] = set(re.findall(r'"([^"]+)"', match.group(2)))
    return union, grants


def test_capability_union_matches_the_yaml() -> None:
    backend_caps, _ = _backend()
    union, _ = _mirror()
    assert union - backend_caps == set(), "frontend names a capability the backend does not define"
    assert backend_caps - union == set(), "frontend union is missing backend capabilities"


def test_every_backend_role_appears_in_the_mirror() -> None:
    _, backend_roles = _backend()
    _, mirror_roles = _mirror()
    # BillingAdmin was absent here, which silently denied it everything.
    assert set(backend_roles) - set(mirror_roles) == set()
    assert set(mirror_roles) - set(backend_roles) == set()


def test_no_role_grants_more_on_the_frontend_than_the_backend() -> None:
    """The dangerous direction: a control that renders and then 403s."""
    _, backend_roles = _backend()
    _, mirror_roles = _mirror()
    over = {
        role: sorted(caps - backend_roles.get(role, set()))
        for role, caps in mirror_roles.items()
        if caps - backend_roles.get(role, set()) - {WILDCARD}
    }
    assert over == {}, f"frontend grants the backend denies: {over}"


def test_no_role_grants_less_on_the_frontend_than_the_backend() -> None:
    """The quiet direction: an entitled control that never appears."""
    _, backend_roles = _backend()
    _, mirror_roles = _mirror()
    under = {}
    for role, caps in backend_roles.items():
        if WILDCARD in caps:
            # PlatformAdmin is the literal wildcard on both sides.
            assert mirror_roles.get(role) == {WILDCARD}
            continue
        missing = caps - mirror_roles.get(role, set())
        if missing:
            under[role] = sorted(missing)
    assert under == {}, f"frontend is missing backend grants: {under}"
