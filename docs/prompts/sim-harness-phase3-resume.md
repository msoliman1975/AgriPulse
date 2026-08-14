# Resume prompt — org simulation harness, Phase 3

Paste this into a fresh session, or say: *"read `docs/prompts/sim-harness-phase3-resume.md`
and carry on."*

---

You are continuing work on the **org simulation harness**: an agent-per-persona simulation of a
whole organisation's journey through AgriPulse, built for go-live evidence and continuous
exploratory testing. The full plan is `docs/testing/org-simulation-harness.md` — read it first.

Phases 1 and 2 are **built, merged and live in production**. Phase 3 is next.

## STOP — read this before running anything

**`NOTIFICATION_SINK_TENANT_PREFIX` is empty in production.** Verified on 2026-08-14 by
executing into the api pod: the sink module is present, and
`get_settings().notification_sink_tenant_prefix` returns `''`.

The sink ships inert by design — that is what stops it silencing real customers — but it means
**a simulation run today would send real email to whatever addresses the cloned seed carries.**
The spine's Act 3 detects this and fails the run, but only after the mail has gone.

So: **set the value before any spine run.** In
`infra/argocd/overlays/hetzner/values.yaml`, under the env map that merges into api + workers:

```yaml
NOTIFICATION_SINK_TENANT_PREFIX: "sim-"
```

It must equal `SIM_TENANT_PREFIX` in `scripts/sim/.sim.env` (default `sim-`). Nothing else
needs promoting — the code is already live.

## Verified state as of 2026-08-14

| Thing | State |
|---|---|
| Phase 1 (purge fix, task triggers) | live — merged `3533c938`, rode along in `ea8fe1e` |
| Phase 2 (sink, clone tool, spine) | live — merged `f3b978ab`, rode along in `f8708b8` |
| prod api / workers | `f8708b8` |
| prod frontend | `cf5c2d7` (Phase 2 is backend-only; frontend is ahead) |
| sink prefix in prod | **NOT SET** — inert |
| spine end-to-end run | **never done** — failure paths tested, happy path not |

**Neither phase ever needed its own promote.** Both times, checking
`git merge-base --is-ancestor <my-sha> <prod-sha>` showed the work was already contained, and
promoting my own SHA would have rolled prod *backwards*. **Always run that check before
touching `values.yaml`.**

## What to do next

### Option A — get the first real spine run (recommended)

This is the highest-value next step: it converts "built" into "demonstrated".

1. **Set the sink prefix** (above) and promote just that values change.
2. **Verify it took**, by exec-ing into the api pod and re-reading
   `get_settings().notification_sink_tenant_prefix`. Do not assume the rollout landed.
3. **Extract a snapshot** — needs DB access, so run it in a pod or through a tunnel:
   ```
   python backend/scripts/sim_snapshot.py extract \
       --source <bashayer_tenant_schema> --out snap.json --farms 2
   ```
4. **Fill `scripts/sim/.sim.env`** from `scripts/sim/.sim.env.example` (gitignored; it holds a
   PlatformAdmin login and the Keycloak master password).
5. **Run the spine**: `python scripts/sim/spine.py --snapshot snap.json --keep`
6. Expect to find bugs. It has never run against prod. Fix what it finds; the ledger is at
   `runs/<run_id>/ledger.jsonl`.
7. Then do the **outstanding P1 prod proof**: three consecutive provision/purge cycles with no
   `SMOKE_EMAIL_SUFFIX`, asserting `GET /api/v1/admin/purge/orphans` returns zero each time —
   then delete that workaround from `scripts/e2e/provision_demo.py`.

### Option B — Phase 3: one browser persona

Per the plan, Phase 3 deliberately runs **one** persona through Act 4 before committing to
eight, to get real numbers on browser-agent cost and flakiness. Start with the Agronomist
(Insights: weather index chart, index trends, open a recommendation). Re-scope if it disappoints.

Phase 3 needs a working spine run first, so Option A comes before it in practice.

## Decisions the user has locked — do not re-litigate

Prod with a **fresh throwaway tenant per run** (purged after) · **backdated seed + on-demand
task triggers** (prod has no clock to move) · **browser-driven personas**, not API ·
choreographed acts with concurrency *inside* each act · **declared outcome + adversarial
verifier** for the verdict · thin-but-complete V1 · **manual/on-demand only — no cron, no CI
gate, no promotion gate** · seed by **cloning a sanitised Bashayer snapshot** · **8 personas** =
6 web roles + a Farm-B-scoped FarmManager and Agronomist (that pair exists to prove farm-scope
isolation, which is why the run has two farms).

The harness is an **advisory defect list, never a gate**. Agent runs are non-deterministic; a
green run means "nothing obvious broke this time".

## What exists, and where

- `backend/app/shared/purge/{engine,scanner}.py` — orphan-user delete + the matching scan.
- `backend/app/modules/platform_admins/{task_registry,tasks_router}.py` — `/api/v1/admin/tasks`,
  capability `platform.run_tasks`.
- `backend/app/modules/notifications/sink.py` — suppression; guards at six call sites in
  `subscribers.py`, backstops in `smtp.py` / `push.py` / `webhook.py`.
- `backend/app/modules/simulation/snapshot.py` + `backend/scripts/sim_snapshot.py` — the clone.
- `scripts/sim/spine.py` — Acts 0–3.

## Traps — all of these cost real time

**Deploy**
- Run `git merge-base --is-ancestor <sha> <prod-sha>` before every promote. Twice now the work
  was already live and promoting would have rolled prod back.
- Verify the pushed manifest in the **container job log** (`"image.name": …:<7-char-tag>`),
  never the run conclusion. A cancelled run may still have pushed.
- GHCR tags are 7 chars; git prints 8.
- `app.agripulse.cloud/api/*` serves the SPA — a 200 there proves nothing. Use
  `api.agripulse.cloud`, or better, exec into the pod.
- Prove a rollout by **introspecting `app.routes` in the pod**, not by probing HTTP status: auth
  middleware rejects pre-routing, so 401-vs-404 is worthless.
- SSH to prod works: `root@167.233.98.216`, k3s + kubectl.

**This codebase**
- `scripts/e2e/` is **mostly uncommitted** — only `identity_smoke.py` is in git.
  `provision_demo.py`, `mint_oidc.py`, `setup_demo_data.py`, `rbac_sweep.py` exist only in one
  working directory. The spine depends on none of them, but they are one `git clean` from gone.
- `frontend/e2e/fixtures.ts` is **fully mocked** — fake JWT, every `/api/v1/**` intercepted. No
  use as a base for live simulation.
- Adding a capability **requires** editing `frontend/src/rbac/capabilities.ts` too;
  `tests/unit/test_rbac_frontend_parity.py` enforces it.
- CI runs `black`, not `ruff format`; `tsc -b`, not `tsc`. Lint is scoped to `^backend/.*\.py$`,
  so `scripts/` is not linted by CI.
- `backend-integration` has a 20-minute cap against a ~15-minute suite and is
  `continue-on-error: true`. It times out intermittently from runner variance — verify locally
  rather than chasing it.
- Worktrees have no `.venv`. Run tests as:
  `PYTHONPATH=. ../../MissionAgre/backend/.venv/Scripts/python.exe -m pytest ... --no-cov`

**Traps specific to this harness**
- The **orphan scan is platform-wide**, so "assert zero orphans" in a test passes or fails on
  test ordering. Assert baseline-relative and clean up anything deliberately stranded.
- `ruff --fix` **deletes registration-only imports** (`import x.tasks  # noqa: F401`). Use
  `importlib.import_module` in a loop when the import exists for its side effect.
- `notification_dispatches.status` is CHECK-constrained to
  `(pending, sent, failed, skipped)`. Suppression reuses `skipped` plus a reason string; a new
  status value needs a tenant migration.
- The clone's rebase offset **must** come from a named observation column.
  `block_index_aggregates` also carries `inserted_at` (~now); letting it set the offset pegged
  everything to the extract date and left history five months in the past, where no tree finds
  recent data.
- Generated columns cannot be inserted into; arrays and JSONB both arrive as Python lists but
  only JSONB may be re-serialised; dates must be rebuilt for asyncpg.
- Never provision a real tenant in a test that does not need one — `create_tenant` runs all 77
  tenant migrations.

## Known-broken, filed but not fixed

- **`delete_users_and_group(slug)` deletes every member of the tenant's Keycloak group**, so a
  user belonging to two tenants loses their Keycloak identity when either is purged, breaking
  their login to the surviving one. Needs a per-user group lookup.
- **FCM is inert in prod** (no Helm value sets `fcm_enabled`), so the push path cannot be
  asserted at all. A stated coverage gap — do not fake a pass on it.
