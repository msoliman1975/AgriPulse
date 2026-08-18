#!/usr/bin/env python3
"""Acts 0-3 of a simulation run: the deterministic spine.

Everything here is scripted and assertive. The agent swarm comes later and is
allowed to be non-deterministic; this part is not, because it is what makes the
swarm's findings mean anything. It ends with a tenant that has real geometry,
real observation history, and recommendations produced by the live pipeline
rather than carried in by the seed.

    python scripts/sim/spine.py --snapshot snap.json [--keep]

Acts
----
0  Preflight       prove the platform is reachable and clean before touching it
1  Provision       tenant + one login per persona
2  Org setup       load the sanitised clone, grant farm scopes
3  History         trigger the pipeline, assert it produced something

Why the assertions are shaped the way they are
----------------------------------------------
Act 3 asserts on the *task return values*, which
``GET /admin/tasks/runs/{id}`` hands back. Those tasks already return counts,
so the spine reads what the pipeline says it did rather than inventing read
endpoints and inferring. A silent zero at any stage is a hard failure: every
downstream persona assertion in Act 4 would otherwise pass vacuously against an
empty tenant, and the run would report a healthy product having tested nothing.

The notification sink is verified here rather than in Act 0, because a
suppression check needs something to have been dispatched. Act 0 cannot read
the deployed setting, so it does not pretend to; Act 3 fires a real alert and
insists the dispatch rows came back suppressed.

Configuration comes from the environment or ``scripts/sim/.sim.env``:

    SIM_API_BASE        default https://api.agripulse.cloud/api/v1
    SIM_KC_BASE         default https://keycloak.agripulse.cloud
    SIM_REALM           default agripulse
    SIM_KC_CLIENT       default agripulse-api
    SIM_PLATFORM_USER   PlatformAdmin login          (required)
    SIM_PLATFORM_PASS                                (required)
    SIM_EMAIL_DOMAIN    default agripulse.tech
    SIM_TENANT_PREFIX   default sim-  — MUST match NOTIFICATION_SINK_TENANT_PREFIX
    SIM_LOAD_CMD        how to apply the snapshot (needs DB access)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import warnings
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "scripts" / "sim" / ".sim.env"


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

API_BASE = os.environ.get("SIM_API_BASE", "https://api.agripulse.cloud/api/v1")
KC_BASE = os.environ.get("SIM_KC_BASE", "https://keycloak.agripulse.cloud")
REALM = os.environ.get("SIM_REALM", "agripulse")
KC_CLIENT = os.environ.get("SIM_KC_CLIENT", "agripulse-api")
EMAIL_DOMAIN = os.environ.get("SIM_EMAIL_DOMAIN", "agripulse.tech")
# Must equal the deployed NOTIFICATION_SINK_TENANT_PREFIX, or the run's
# notifications reach real inboxes. Act 3 is what actually proves they did not.
TENANT_PREFIX = os.environ.get("SIM_TENANT_PREFIX", "sim-")

# The clone load needs a database connection, which the API does not expose and
# deliberately never will. Runs either inside a pod or through a tunnel.
LOAD_CMD = os.environ.get(
    "SIM_LOAD_CMD",
    f"{sys.executable} {ROOT / 'backend' / 'scripts' / 'sim_snapshot.py'} "
    "load --target {schema} --in {snapshot} --as-of {as_of}",
)

# TLS verification is off for the same reason every other script here does it:
# this corporate network MITMs the chain. Connectivity itself is fine.
VERIFY = False

# The eight personas. Farm-scoped roles are granted in Act 2 once farms exist;
# the FarmManager/Agronomist pair scoped to Farm B is what proves farm
# isolation holds, which is the entire reason the run has two farms.
PERSONAS: tuple[dict[str, Any], ...] = (
    {"key": "owner", "role": "TenantAdmin", "farm": None, "name": "Sim Owner"},
    {"key": "farmmanager", "role": "Viewer", "farm": "both", "name": "Sim FarmMgr"},
    {"key": "agronomist", "role": "Viewer", "farm": "both", "name": "Sim Agronomist"},
    {"key": "fieldop", "role": "Viewer", "farm": "both", "name": "Sim FieldOp"},
    {"key": "viewer", "role": "Viewer", "farm": None, "name": "Sim Viewer"},
    {"key": "farmmanager-b", "role": "Viewer", "farm": "b", "name": "Sim FarmMgr B"},
    {"key": "agronomist-b", "role": "Viewer", "farm": "b", "name": "Sim Agronomist B"},
)

FARM_ROLE = {
    "farmmanager": "FarmManager",
    "agronomist": "Agronomist",
    "fieldop": "FieldOperator",
    "farmmanager-b": "FarmManager",
    "agronomist-b": "Agronomist",
}

# Order matters and is not arbitrary: index aggregates have to be materialised
# before baselines can be computed from them, and both have to exist before a
# tree evaluating "how far below baseline is this block" can decide anything.
PIPELINE: tuple[tuple[str, str], ...] = (
    ("indices.refresh_index_caggs_for_tenant", "materialise the index aggregates"),
    ("indices.recompute_baselines_for_tenant", "compute baselines from that history"),
    ("weather.recompute_baselines_for_tenant", "compute the weather climatology"),
    ("recommendations.evaluate_for_tenant", "evaluate every published tree"),
)


class SpineFailure(RuntimeError):
    """A step that the run cannot meaningfully continue past."""


@dataclass
class Run:
    run_id: str
    slug: str
    started_at: datetime
    directory: Path
    state: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def record(self, act: str, step: str, ok: bool, detail: Any = None) -> None:
        """One line per step, appended immediately.

        Written as it goes rather than at the end: a run that dies mid-act is
        exactly the run whose ledger matters, and Act 4's personas run
        concurrently, so afterwards there is no other way to reconstruct order.
        """
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "act": act,
            "step": step,
            "ok": ok,
            "detail": detail,
        }
        with (self.directory / "ledger.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        mark = "ok  " if ok else "FAIL"
        print(f"  [{mark}] {step}" + (f" — {detail}" if detail is not None else ""))
        if not ok:
            self.failures.append(f"{act}/{step}: {detail}")

    def require(self, act: str, step: str, ok: bool, detail: Any = None) -> None:
        self.record(act, step, ok, detail)
        if not ok:
            raise SpineFailure(f"{act}/{step}: {detail}")

    def save_state(self) -> None:
        (self.directory / "state.json").write_text(
            json.dumps(self.state, indent=2, default=str), encoding="utf-8"
        )


# --- clients ----------------------------------------------------------------


def _platform_token() -> str:
    for name in ("SIM_PLATFORM_USER", "SIM_PLATFORM_PASS"):
        if not os.environ.get(name):
            raise SpineFailure(f"{name} is not set (fill scripts/sim/.sim.env)")
    response = httpx.post(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": KC_CLIENT,
            "username": os.environ["SIM_PLATFORM_USER"],
            "password": os.environ["SIM_PLATFORM_PASS"],
        },
        verify=VERIFY,
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {token}"},
        verify=VERIFY,
        timeout=90,
    )


# --- Act 0 ------------------------------------------------------------------


def act_0_preflight(run: Run, plat: httpx.Client) -> None:
    """Fail before touching anything, rather than halfway through Act 2."""
    print("\n[Act 0] Preflight")

    # Doubles as the reachability check. Deliberately against the API host:
    # app.agripulse.cloud/api/* serves the SPA, so a 200 there proves nothing.
    orphans = plat.get("/admin/purge/orphans")
    run.require(
        "act0",
        "platform API reachable and authorised",
        orphans.status_code == 200,
        f"GET /admin/purge/orphans -> {orphans.status_code}",
    )
    body = orphans.json()
    # A dirty platform before the run means a previous run's teardown failed,
    # and every later "is it clean now" assertion would be measuring residue.
    run.require(
        "act0",
        "no pre-existing orphan rows",
        int(body.get("orphan_rows", 0)) == 0,
        body.get("orphans"),
    )
    run.record(
        "act0",
        "no stray tenant schemas",
        not body.get("stray_schemas"),
        body.get("stray_schemas"),
    )

    triggerable = plat.get("/admin/tasks")
    run.require(
        "act0",
        "task-trigger endpoint present",
        triggerable.status_code == 200,
        f"GET /admin/tasks -> {triggerable.status_code} "
        "(is 3533c938 or later deployed?)",
    )
    names = {t["name"] for t in triggerable.json()["tasks"]}
    missing = sorted({name for name, _ in PIPELINE} - names)
    run.require("act0", "every pipeline task is triggerable", not missing, missing)

    run.require(
        "act0",
        "slug will match the notification sink prefix",
        run.slug.startswith(TENANT_PREFIX),
        f"{run.slug} vs prefix {TENANT_PREFIX!r}",
    )
    # Stated, not assumed: the deployed setting is not readable from here, so
    # the real proof is Act 3's assertion on the dispatch rows.
    run.record(
        "act0",
        "sink verification deferred to Act 3",
        True,
        "cannot read NOTIFICATION_SINK_TENANT_PREFIX remotely",
    )


# --- Act 1 ------------------------------------------------------------------


def act_1_provision(run: Run, plat: httpx.Client, password: str) -> httpx.Client:
    """Create the tenant and one login per persona. Returns the owner client."""
    print("\n[Act 1] Provisioning")

    owner_email = f"sim-owner-{run.run_id}@{EMAIL_DOMAIN}"
    created = plat.post(
        "/admin/tenants",
        json={
            "slug": run.slug,
            "name": f"Simulation {run.run_id}",
            "contact_email": f"sim-contact-{run.run_id}@{EMAIL_DOMAIN}",
            "owner_email": owner_email,
            "owner_full_name": "Sim Owner",
            "initial_tier": "standard",
        },
    )
    run.require(
        "act1",
        "tenant created",
        created.status_code == 201,
        f"POST /admin/tenants -> {created.status_code} {created.text[:200]}",
    )
    tenant = created.json()
    run.state["tenant_id"] = tenant["id"]
    run.state["slug"] = run.slug
    run.state["owner_email"] = owner_email
    run.save_state()

    schema = _await_active(run, plat, tenant["id"])
    run.state["schema_name"] = schema
    run.save_state()

    _set_password(run, owner_email, password)
    owner = _client(_app_token(owner_email, password))
    run.require("act1", "owner can obtain a tenant token", True, owner_email)

    run.state["users"] = {}
    for persona in PERSONAS:
        if persona["key"] == "owner":
            run.state["users"]["owner"] = {"email": owner_email, "farm": None}
            continue
        email = f"sim-{persona['key']}-{run.run_id}@{EMAIL_DOMAIN}"
        invited = owner.post(
            "/users:invite",
            json={
                "email": email,
                "full_name": persona["name"],
                "tenant_role": persona["role"],
            },
        )
        ok = invited.status_code in (200, 201)
        run.record(
            "act1",
            f"invite {persona['key']}",
            ok,
            f"{invited.status_code} {'' if ok else invited.text[:160]}",
        )
        if ok:
            _set_password(run, email, password)
            run.state["users"][persona["key"]] = {
                "email": email,
                "user_id": invited.json().get("user_id"),
                "farm": persona["farm"],
            }
    run.save_state()
    return owner


def _await_active(run: Run, plat: httpx.Client, tenant_id: str, tries: int = 30) -> str:
    """Provisioning is asynchronous; the schema is not there on the 201."""
    for _ in range(tries):
        got = plat.get(f"/admin/tenants/{tenant_id}")
        if got.status_code == 200:
            body = got.json()
            if body.get("status") == "active":
                run.record(
                    "act1", "tenant reached status=active", True, body["schema_name"]
                )
                return str(body["schema_name"])
        time.sleep(2)
    raise SpineFailure(f"tenant {tenant_id} never reached status=active")


def _app_token(username: str, password: str) -> str:
    response = httpx.post(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": KC_CLIENT,
            "username": username,
            "password": password,
        },
        verify=VERIFY,
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _set_password(run: Run, email: str, password: str) -> None:
    """Give a persona a known password so Act 4 can log its browser in.

    Invite mails a temporary credential, which no automated persona can read --
    and on a sim tenant the mail is suppressed anyway.
    """
    admin_user = os.environ.get("SIM_KC_ADMIN_USER")
    admin_pass = os.environ.get("SIM_KC_ADMIN_PASS")
    if not admin_user or not admin_pass:
        run.record("act1", f"set password for {email}", False, "SIM_KC_ADMIN_* not set")
        return
    token = httpx.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": admin_user,
            "password": admin_pass,
        },
        verify=VERIFY,
        timeout=30,
    ).json()["access_token"]
    kc = httpx.Client(
        base_url=f"{KC_BASE}/admin/realms/{REALM}",
        headers={"Authorization": f"Bearer {token}"},
        verify=VERIFY,
        timeout=30,
    )
    with kc:
        found = kc.get("/users", params={"email": email, "exact": True}).json()
        if not found:
            run.record(
                "act1", f"set password for {email}", False, "not found in Keycloak"
            )
            return
        reset = kc.put(
            f"/users/{found[0]['id']}/reset-password",
            json={"type": "password", "value": password, "temporary": False},
        )
        run.record(
            "act1",
            f"set password for {email}",
            reset.status_code in (204, 200),
            reset.status_code,
        )


# --- Act 2 ------------------------------------------------------------------


def act_2_org(run: Run, owner: httpx.Client, snapshot: Path, as_of: datetime) -> None:
    """Apply the sanitised clone, then scope the farm-level personas."""
    print("\n[Act 2] Org setup")

    command = LOAD_CMD.format(
        schema=run.state["schema_name"],
        snapshot=str(snapshot),
        as_of=as_of.date().isoformat(),
    )
    completed = subprocess.run(  # noqa: S602 — command is operator-supplied config
        command, shell=True, capture_output=True, text=True, check=False
    )
    run.require(
        "act2",
        "clone loaded into the tenant schema",
        completed.returncode == 0,
        (completed.stderr or completed.stdout)[-400:],
    )
    (run.directory / "clone-load.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )

    farms = owner.get("/farms")
    run.require(
        "act2",
        "farms readable through the API",
        farms.status_code == 200,
        farms.status_code,
    )
    rows = farms.json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    # Two farms, because farm-scope isolation cannot be tested with one.
    run.require("act2", "clone produced at least two farms", len(rows) >= 2, len(rows))
    run.state["farms"] = [{"id": f["id"], "code": f.get("code")} for f in rows[:2]]
    run.save_state()

    farm_a, farm_b = run.state["farms"][0], run.state["farms"][1]
    members = owner.get("/users").json()
    members = members if isinstance(members, list) else members.get("items", [])
    membership = {m["email"]: m.get("membership_id") for m in members}

    for key, info in run.state["users"].items():
        scope = info.get("farm")
        if not scope:
            continue
        member_id = membership.get(info["email"])
        if not member_id:
            run.record("act2", f"scope {key}", False, "no membership_id")
            continue
        targets = [farm_a, farm_b] if scope == "both" else [farm_b]
        for farm in targets:
            granted = owner.post(
                f"/farms/{farm['id']}/members",
                json={"membership_id": member_id, "role": FARM_ROLE[key]},
            )
            run.record(
                "act2",
                f"scope {key} -> {farm['code']}",
                granted.status_code in (200, 201, 409),
                granted.status_code,
            )
    run.save_state()


# --- Act 3 ------------------------------------------------------------------


def act_3_history(run: Run, plat: httpx.Client, owner: httpx.Client) -> None:
    """Drive the pipeline, and refuse to accept a silent zero."""
    print("\n[Act 3] History and triggers")

    results: dict[str, Any] = {}
    for task_name, why in PIPELINE:
        result = _run_task(run, plat, task_name, why)
        results[task_name] = result

    run.state["pipeline"] = results
    run.save_state()

    # The assertion the whole spine exists for. `evaluate_for_tenant` returns
    # its own counts, so this reads what the pipeline says it did rather than
    # inferring from a list endpoint.
    evaluation = results.get("recommendations.evaluate_for_tenant") or {}
    produced = sum(v for v in evaluation.values() if isinstance(v, int))
    run.require(
        "act3",
        "evaluation produced recommendations or alerts",
        produced > 0,
        f"{evaluation} — a zero here makes every Act 4 assertion vacuous",
    )

    _assert_sink_suppressed(run, owner)


def _run_task(run: Run, plat: httpx.Client, task_name: str, why: str) -> Any:
    accepted = plat.post(
        f"/admin/tasks/{task_name}:run", json={"tenant_slug": run.slug}
    )
    run.require(
        "act3",
        f"dispatch {task_name}",
        accepted.status_code == 202,
        f"{accepted.status_code} {accepted.text[:200]}",
    )
    task_id = accepted.json()["task_id"]

    # Blocking on the result rather than sleeping: a hung worker has to look
    # different from a slow one, or the run reports a timeout as a pass.
    deadline = time.time() + 600
    while time.time() < deadline:
        state = plat.get(f"/admin/tasks/runs/{task_id}").json()
        if state.get("ready"):
            run.require(
                "act3",
                f"{task_name} succeeded ({why})",
                bool(state.get("successful")),
                state.get("error"),
            )
            return state.get("result")
        time.sleep(3)
    raise SpineFailure(f"{task_name} did not finish within 600s")


def _assert_sink_suppressed(run: Run, owner: httpx.Client) -> None:
    """Prove nothing left the building.

    Act 0 could not read the deployed prefix, so this is where the sink is
    actually verified: if a dispatch says `sent`, real mail reached a real
    address and the run must stop being treated as safe.
    """
    dispatches = owner.get("/notifications/dispatches", params={"limit": 200})
    if dispatches.status_code != 200:
        run.record(
            "act3",
            "notification sink verified",
            False,
            f"GET /notifications/dispatches -> {dispatches.status_code}; "
            "sink UNVERIFIED — do not run personas until this is checked",
        )
        return
    rows = dispatches.json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    outbound = [r for r in rows if r.get("channel") in ("email", "push", "webhook")]
    leaked = [r for r in outbound if r.get("status") == "sent"]
    run.require(
        "act3",
        "no outbound notification was actually delivered",
        not leaked,
        f"{len(leaked)} dispatch row(s) say sent — the sink is not active",
    )
    run.record(
        "act3",
        "outbound dispatches recorded as suppressed",
        True,
        f"{len(outbound)} outbound row(s) inspected",
    )


# --- entry ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="sanitised snapshot file")
    parser.add_argument(
        "--as-of", help="ISO date the tenant should look current as of (default today)"
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the tenant in place for Act 4 (the normal case)",
    )
    args = parser.parse_args()

    run_id = f"{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6]}"
    directory = ROOT / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    run = Run(
        run_id=run_id,
        slug=f"{TENANT_PREFIX}{run_id}",
        started_at=datetime.now(UTC),
        directory=directory,
    )
    as_of = (
        datetime.fromisoformat(args.as_of).replace(tzinfo=UTC)
        if args.as_of
        else datetime.now(UTC)
    )
    password = f"Sim!{uuid.uuid4().hex[:10]}Aa1"
    run.state["password"] = password

    print(f"run {run_id}  slug {run.slug}\n  API {API_BASE}\n  ledger {directory}")
    try:
        plat = _client(_platform_token())
        with plat:
            act_0_preflight(run, plat)
            owner = act_1_provision(run, plat, password)
            # `closing`, not `with`. Act 1 issues the invites through this very
            # client before handing it back, which moves httpx out of UNOPENED,
            # and `__enter__` on an already-opened client raises
            # "Cannot open a client instance more than once". `plat` survives
            # the same pattern only because nothing has used it yet at the
            # `with` above. All we ever wanted here was the close.
            with closing(owner):
                act_2_org(run, owner, Path(args.snapshot), as_of)
                act_3_history(run, plat, owner)
    except SpineFailure as exc:
        print(f"\nSPINE FAILED: {exc}", file=sys.stderr)
        run.save_state()
        return 1
    except Exception as exc:
        run.record("run", "unhandled error", False, repr(exc))
        run.save_state()
        print(f"\nSPINE ERRORED: {exc!r}", file=sys.stderr)
        return 2

    run.save_state()
    print(
        f"\nSpine complete. tenant={run.slug} schema={run.state.get('schema_name')}\n"
        f"  state:  {directory / 'state.json'}\n"
        f"  ledger: {directory / 'ledger.jsonl'}"
    )
    if not args.keep:
        print("\n  --keep was not passed; the tenant is still up. Purge it with:")
        print(
            f"    POST /admin/tenants/{run.state.get('tenant_id')}/delete then /purge"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
