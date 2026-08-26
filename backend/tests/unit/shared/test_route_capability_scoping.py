"""Every farm-tier capability check must be able to reach the farm tier.

`CapabilityRegistry.has_capability` resolves PlatformRole -> TenantRole ->
FarmScope, and only consults the farm tier when it is *given* a farm. So a
route written as::

    Depends(requires_capability("signal.read"))

denies every caller whose only grants are farm scopes, because the resolver
stops one tier short. That is correct for a genuinely tenant-scoped capability
and a silent 403 for anything a Scout or a FarmManager is meant to reach — no
error text says which, and the first sign is somebody staring at an empty
screen.

The failure has come back twice. Review does not catch it, because each
individual route looks reasonable. This test walks every route instead and
fails on any farm-tier capability checked with neither `farm_id_param` nor
`any_farm`.

To satisfy it, pick the one that is true of the route:

* the request already names a farm -> `farm_id_param="farm_id"`;
* the row it addresses knows its farm -> read the row first, then
  `has_capability(..., farm_id=row["farm_id"])`, answering 404 on failure so
  the id cannot be probed;
* the data belongs to no farm -> `any_farm=True`;
* the endpoint is personal, so the row filter is already the caller -> no
  capability at all, just `get_current_context`;
* it really is tenant-wide -> add it to `DELIBERATELY_TENANT_SCOPED` with the
  reason.

An imperative `has_capability(...)` that means "is this a tenant-level caller"
is not an exception to any of that: call `has_tenant_wide_capability` instead,
which says so.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
from typing import Any

import pytest
import yaml
from fastapi.routing import APIRoute

from app.shared.rbac.check import get_default_registry

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
MODULES_DIR = BACKEND_DIR / "app" / "modules"
RBAC_YAML = BACKEND_DIR / "app" / "shared" / "rbac" / "role_capabilities.yaml"
FARM_ROLES = ("FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer")

#: Routes that check a farm-tier capability tenant-wide on purpose, mapped to
#: why. Keep the reason: an unexplained entry here is how the bug comes back
#: wearing an allowlist.
DELIBERATELY_TENANT_SCOPED: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/resources"): (
        "The whole roster across every farm. That is a different question from "
        "'who is on my farm' and is not answerable from a single farm's grant "
        "— see the comment on the route."
    ),
}

#: No allowlist for the imperative form. A call that deliberately asks the
#: tenant-wide question says so by calling `has_tenant_wide_capability`, which
#: reads as intent at the call site instead of as an entry in a table nobody
#: looks at. Every bare `has_capability` with no farm is therefore a bug.


def _farm_tier_capabilities() -> set[str]:
    """Capabilities some farm role grants — the ones that need a farm."""
    doc = yaml.safe_load(RBAC_YAML.read_text(encoding="utf-8"))["roles"]
    return {cap for role in FARM_ROLES for cap in (doc.get(role, {}).get("capabilities") or [])}


def _router_module_names() -> list[str]:
    """Every `app.modules.*` module whose filename carries "router".

    Discovered rather than listed. A hand-kept list goes stale the first time
    somebody adds a router, and the router they add is exactly the one this
    should have seen.
    """
    names = []
    for path in sorted(MODULES_DIR.rglob("*router*.py")):
        rel = path.relative_to(BACKEND_DIR).with_suffix("")
        names.append(str(rel).replace("\\", "/").replace("/", "."))
    return names


def _routers() -> list[Any]:
    out = []
    for name in _router_module_names():
        module = importlib.import_module(name)
        router = getattr(module, "router", None)
        if router is not None:
            out.append(router)
    return out


def _iter_dependants(dependant: Any) -> Any:
    yield dependant
    for sub in dependant.dependencies:
        yield from _iter_dependants(sub)


def test_no_farm_tier_capability_is_checked_without_a_farm() -> None:
    farm_caps = _farm_tier_capabilities()
    registry = get_default_registry()
    offenders: list[str] = []
    seen_routes = 0

    for router in _routers():
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            seen_routes += 1
            for dep in _iter_dependants(route.dependant):
                capability = getattr(dep.call, "__ap_capability__", None)
                if capability is None or capability not in farm_caps:
                    continue
                if getattr(dep.call, "__ap_farm_id_param__", None) is not None:
                    continue
                if getattr(dep.call, "__ap_any_farm__", False):
                    continue
                holders = [r for r in FARM_ROLES if registry.role_grants(r, capability)]
                for method in sorted(route.methods or ()):
                    if (method, route.path) in DELIBERATELY_TENANT_SCOPED:
                        continue
                    offenders.append(
                        f"  {method:6s} {route.path}\n"
                        f"         checks {capability!r} with no farm — denies "
                        f"{', '.join(holders)}"
                    )

    assert seen_routes > 100, f"only walked {seen_routes} routes; discovery is broken"
    assert not offenders, (
        "These routes check a farm-tier capability without a farm, so every "
        "farm-scoped caller gets 403:\n\n"
        + "\n".join(sorted(offenders))
        + "\n\nSee this test's module docstring for the ways to fix it."
    )


def test_no_imperative_capability_check_forgets_the_farm() -> None:
    """The same defect in its other shape.

    `requires_capability` is the declarative form, which the route walk sees.
    A route that resolves its own farm calls `has_capability` directly, and a
    call that forgets `farm_id=` fails identically while looking nothing like
    the first form. Both shapes were live in production at the same time.
    """
    farm_caps = _farm_tier_capabilities()
    offenders: list[str] = []

    for path in sorted(MODULES_DIR.rglob("*router*.py")):
        rel = str(path.relative_to(BACKEND_DIR)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "has_capability"):
                continue
            if any(kw.arg == "farm_id" for kw in node.keywords):
                continue
            for arg in node.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    continue
                cap = arg.value
                if cap not in farm_caps:
                    continue
                offenders.append(f"  {rel}:{node.lineno} — has_capability({cap!r}) with no farm_id")

    assert not offenders, (
        "These calls check a farm-tier capability without a farm:\n\n"
        + "\n".join(sorted(offenders))
        + "\n\nPass `farm_id=` from the row being addressed. If the call really "
        'means "is this a tenant-level caller", say so with '
        "`has_tenant_wide_capability`."
    )


@pytest.mark.parametrize("entry", sorted(DELIBERATELY_TENANT_SCOPED))
def test_allowlisted_routes_still_exist(entry: tuple[str, str]) -> None:
    """An allowlist entry for a route that no longer exists is a lie.

    It implies a deliberate decision about a route somebody has since deleted
    or renamed, and it silently covers the next route to take that path.
    """
    method, path = entry
    for router in _routers():
        for route in router.routes:
            if (
                isinstance(route, APIRoute)
                and route.path == path
                and method in (route.methods or ())
            ):
                return
    pytest.fail(f"{method} {path} is allowlisted but no longer exists — drop the entry")


def test_every_allowlist_entry_gives_a_reason() -> None:
    """A placeholder reason is the same as no reason."""
    for key, reason in DELIBERATELY_TENANT_SCOPED.items():
        assert len(re.sub(r"\s+", " ", reason).strip()) > 40, f"{key} needs a real reason"
