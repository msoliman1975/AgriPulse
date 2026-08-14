# Org Simulation Harness

An agent-driven simulation of a complete organisation journey on AgriPulse: platform admin
provisions a tenant, an owner builds out two farms, eight people work concurrently in the
browser, decision trees fire, recommendations and alerts land, plans run against blocks.

Purpose: **go-live evidence and continuous exploratory testing.** Not a CI gate.

---

## 1. Locked decisions

| # | Decision | Choice | Consequence |
|---|---|---|---|
| 1 | Environment | **Prod, isolated throwaway tenant** | No clock control; real notifications must be sunk; teardown must be genuinely clean |
| 2 | Time model | **Backdated seed + on-demand task triggers** | Needs a new platform-admin task-trigger endpoint; the beat scheduler itself stays untested |
| 3 | Agent interface | **Browser-driven throughout** | Highest user fidelity; per-persona browser isolation required; slowest and flakiest |
| 4 | Run shape | **Choreographed acts, concurrent within act** | Barriers where dependencies are real, true parallelism inside the "live day" |
| 5 | Verdict | **Declared outcome + adversarial verifier** | ~1.5–2× token cost; kills the self-congratulatory pass |
| 6 | V1 scope | **Full journey, thin** | Whole spine works end to end before any module gets depth |
| 7 | Tenant lifecycle | **Fresh tenant per run, purged after** | Purge orphan gap is a hard blocker |
| 8 | Cadence | **Manual / on-demand only** | No cron, no promotion gate, no CI wiring |
| 9 | Seed data | **Sanitised snapshot of Bashayer** | Needs a cross-tenant clone tool that does not exist |
| 10 | Roster | **6 web personas + Farm-B-scoped FarmManager & Agronomist** | 8 acting agents + verifiers |

### What this harness is not

It is **not** a regression gate. Agent runs are non-deterministic; a green run means "nothing
obvious broke this time", never "this behaves as it did yesterday". Its output is a triaged
defect list a human reads. If it ever starts blocking promotions, it will flake and be ignored.

---

## 2. Prerequisites — engineering that must exist before a single agent runs

These are real deliverables, not scaffolding. Five of the six are useful outside testing.

### P1 — Clean tenant teardown *(hard blocker)* — **BUILT, not yet proven on prod**

`scripts/e2e/provision_demo.py` already carries a workaround comment: purge leaves orphaned
`public.users` rows, forcing an email-suffix hack so re-provisioning doesn't collide. With a
fresh tenant every run, this compounds immediately.

The gap turned out to be precise: `tenant_memberships` **is** in the purge manifest, but
`public.users` cannot be — it carries no ownership column, because a user is not *owned* by a
tenant, it is *reachable from* one, possibly from several.

Done:

- `delete_tenant_public` captures the tenant's members before the manifest empties
  `tenant_memberships`, then deletes those left with no membership anywhere and no platform
  role. Narrow in both directions: a user still in another tenant survives, and so does a
  platform admin with no membership at all.
- The four provenance columns (`invited_by`, `granted_by` ×3) are plain FKs with no
  `ON DELETE`, so a surviving row in another tenant naming a purged user as its inviter would
  have aborted the whole purge. They are blanked first.
- The orphan scanner gained the matching check, which is what makes the **existing**
  `GET /admin/purge/orphans` usable as the post-purge verify-clean assertion. No new endpoint
  was needed.
- Keycloak already deletes the tenant group's members, so the KC side was never the gap.

Outstanding:

- **Prove it on prod** — three consecutive provision/purge cycles with no email suffix. Proven
  in integration tests; needs a deployed build to be proven for real.
- Drop the `SMOKE_EMAIL_SUFFIX` workaround from `provision_demo.py` once that passes.

> **Latent bug found, deliberately not fixed here.** `delete_users_and_group(slug)` deletes
> *every* member of the tenant's Keycloak group. A user belonging to two tenants therefore
> loses their Keycloak identity entirely when either tenant is purged, breaking their login to
> the surviving one. It does not block the harness (which uses its own email domain) and
> fixing it needs a per-user group lookup, so it is filed rather than folded into this change.

### P2 — Task trigger control surface — **BUILT**

```
GET  /api/v1/admin/tasks                -- what may be run, and the params each accepts
POST /api/v1/admin/tasks/{name}:run     -- dispatch for one tenant, returns a Celery task id
GET  /api/v1/admin/tasks/runs/{task_id} -- state, so the harness blocks instead of sleeping
```

Gated on a new `platform.run_tasks`, held only by PlatformAdmin's wildcard — deliberately not
folded into `platform.manage_tenants`, since this reaches into the worker fleet and the tasks
it starts write real rows.

Two safety properties, both tested rather than assumed:

- **No sweeps.** A `*_sweep` task walks every active tenant, so exposing one would let a run
  against a throwaway tenant write into every other tenant on the platform. Only per-tenant
  counterparts are allowlisted.
- **`tenant_schema` is never caller-supplied.** The endpoint fills it in from the resolved
  tenant; passing it in `params` is a 422. Otherwise a request could aim a task at a tenant it
  did not name — and the audit row would record the wrong one.

The allowlist is a literal in `task_registry.py`, not anything derived at runtime: dispatching
Celery by name from an HTTP request is a remote code execution primitive unless that list
holds. Suspended and pending-delete tenants are refused.

### P3 — Sanitising cross-tenant clone

Copies a realistic data distribution out of Bashayer into the fresh test tenant without dragging
customer identity along.

**Copies:** farm/block/sub-block geometry, grid config, crop assignments and phenology, weather
observation history, index observation history, imagery product subscriptions (as rows, not live
subscriptions).

**Never copies:** users, memberships, notes, scouting observations authored by real people, farm
and block *names* (rename to `SIM-A-01` style), tenant branding, billing.

Timestamps are rebased so the newest observation lands on the run date minus one day — that is
what makes the tenant "born mid-season" and gives the decision trees something to fire on.

> **Risk accepted:** this couples the harness to a real customer's dataset. If Bashayer's data
> shape changes, seeds change silently. Mitigate by snapshotting the clone output to R2 once and
> replaying the snapshot, rather than re-reading Bashayer every run.

### P4 — Notification sink — **BUILT**

> Set `NOTIFICATION_SINK_TENANT_PREFIX=sim-` in the Helm values before a run. It is empty by
> default, so an unset value delivers normally — Act 0 must verify the sink is live rather than
> assume it, by dispatching one notification and asserting the row came back `skipped` with
> `error = "outbound suppressed for simulation tenant"`.


The swarm will trigger email and FCM pushes. On prod these reach real endpoints, so this must
land before any persona acts.

**No capture table is needed.** `notification_dispatches` already records every attempt — one
row per (recipient, channel) with status, rendered subject/body, and error. It is already the
oracle this plan asked for. The work is purely to suppress *delivery* for one tenant.

**The switch is a slug prefix in settings, not a column.** `notification_sink_tenant_prefix`
(empty = disabled, set to `sim-` in the Helm values). A per-run tenant is `sim-<run_id>`, so one
setting covers every future run with no per-run configuration, and a real tenant can never match
a reserved prefix. No migration, and no risk of the flag being left on a real tenant.

**It must be per-tenant, never process-wide.** The sim tenant lives on prod beside real
customers, so a global kill switch would silence their alerts too.

Three transports carry outbound traffic — `smtp.send_email`, `push.send_push`,
`webhook.send_webhook`. Suppression is modelled on the precedent already in `send_push`, which
returns `PushResult(sent=False, skipped=True)` when FCM is disabled.

Two findings from reading the dispatch path:

1. **Filtering the tenant's enabled channels is not sufficient.** There are three subscribers —
   `_on_alert_opened`, `_on_recommendation_opened`, `_on_scouting_visit_assigned` — and only the
   first two consult `_load_tenant_channels`. Scouting sends push directly, so a channel-level
   filter would leak exactly the notifications a field-operator persona generates.
2. **The guard has to be at the call sites, not only inside the transports.** Suppressing inside
   `send_email` (which returns `None` on success) would leave the dispatch row saying `sent` for
   something never sent — a lie in the table the harness reads as its oracle. Each of the six
   call sites needs to record a distinct `suppressed` status. Guarding inside the transports as
   well is still worth doing as a backstop, so a future call site cannot leak by omission.

Fail-open on missing context is deliberate: an unset prefix delivers normally. Suppressing by
accident would silence real customers' alerts, which is worse than a sim run that leaks a test
email. Act 0 verifies the sink is live by dispatching one notification and asserting it was
recorded `suppressed`.

FCM is inert in prod (no Helm value sets `fcm_enabled`), so the push path cannot be asserted
until that changes. Record it as a coverage gap; do not fake a pass.

### P5 — Per-persona browser isolation

The Playwright MCP server is a single shared browser. Eight concurrent personas would fight over
one context and produce nonsense. Each acting agent needs:

- Its own browser context with a dedicated `user-data-dir` (separate cookies, sessionStorage,
  OIDC state).
- Its own viewport and locale — at least one persona runs in Arabic/RTL.
- A distinct `X-Sim-Persona` request header injected on every request, so server-side logs and
  the run ledger can attribute any 500 to a specific agent.

### P6 — Run ledger

Concurrency is the point, but it makes failures unrepeatable unless everything is recorded.

- One JSONL per run: `{ts, run_id, persona, act, step, action, url, status, correlation_id, evidence_paths}`.
- Correlation id propagated as a request header and echoed in API logs.
- Screenshots and network HARs written under `runs/<run_id>/<persona>/`.
- Deployed image SHAs for api / workers / frontend captured at Act 0, so every finding is
  attributable to a build.

---

## 3. Run anatomy

```
Act 0  Preflight            harness      serial
Act 1  Platform provision   PlatformAdmin agent   solo
Act 2  Org setup            Owner agent           solo
Act 3  History injection    harness      serial   (clone + triggers)
Act 4  Live day             8 personas   CONCURRENT
Act 5  Reaction loop        4 personas   CONCURRENT
Act 6  Verification         verifiers    concurrent
Act 7  Teardown + report    harness      serial
```

Barriers sit between acts because the dependencies are real: no farms without a tenant, no
recommendations without seeded observations and a triggered sweep. Inside Act 4 and Act 5 there
are no barriers at all — that is where contention, RBAC leakage and cache staleness surface.

### Act 0 — Preflight

Fail fast rather than debugging a half-provisioned tenant later.

- Record api / workers / frontend image SHAs from the cluster.
- Assert no leftover tenant matching the sim slug pattern; if found, purge and re-verify.
- Health-check the API from the node with `curl` (not through the SPA host — `app.agripulse.cloud/api/*`
  serves the SPA, so a 200 there is meaningless).
- Confirm Keycloak direct-grant works for the platform user.
- Allocate `run_id` and the run's email domain suffix.

### Act 1 — Platform provisioning · *PlatformAdmin*

Creates the tenant, then does the platform-side work a real onboarding involves.

- Create tenant `sim-<run_id>`; verify the tenant schema and its migrations landed.
- Inspect the crop catalog and platform defaults as they appear to a new tenant.
- Create the eight users; assign tenant-level roles.
- Visit the Roles & permissions page; confirm capability resolution (the frontend now reads
  capabilities from `/v1/me`, not a bundled mirror — assert they match what the API returns).

### Act 2 — Org setup · *Owner / TenantAdmin*

Two farms, deliberately asymmetric so they don't test the same thing twice.

| | Farm A | Farm B |
|---|---|---|
| Crop | Mango (perennial, phenology-driven) | Potato (seasonal, plan-template-driven) |
| Blocks | ~6 with sub-block grid | ~4, no grid |
| Users | FarmManager, Agronomist, FieldOperator, Viewer (tenant-wide) | Farm-B-scoped FarmManager + Agronomist only |
| Purpose | Depth: grid, indices, pixel map, trees | Isolation: farm-scoped users must not see Farm A |

- Create both farms; import block geometry (clone output from P3).
- Configure grid on Farm A; assign crops and cultivars on both.
- Grant farm memberships — including the two Farm-B-only accounts.
- Subscribe blocks to weather and imagery products.
- Assign a plan template to Farm B's blocks.

### Act 3 — History injection · *harness, not an agent*

Deterministic and scripted, because this is the part that must be identical run to run.

1. Load the sanitised Bashayer snapshot, rebased to `run_date - 1d`.
2. Trigger, in order, blocking on each: weather ingest → index CAGG refresh → index projection →
   `recommendations.evaluate_for_tenant`.
3. Assert non-zero counts at each stage before proceeding. A silent zero here makes every
   downstream persona assertion vacuous — this is the single most important checkpoint in the run.

### Act 4 — The live day · *all 8 personas, concurrent*

Each persona works a shift of two to four tasks. Thin by design: one representative task per
capability area, not exhaustive coverage.

| Persona | Scope | Shift |
|---|---|---|
| PlatformAdmin | platform | Tenant health, integration health, audit log for the run so far |
| Owner / TenantAdmin | tenant | Invite a ninth user, edit a role, review both farms' overview |
| FarmManager | both farms | Farm Console: read the pixel map, open block signals, triage the board |
| Agronomist | both farms | Insights: weather indices chart, index trends, open a recommendation |
| FieldOperator | both farms | Execute a plan task on a block, log completion |
| Viewer | tenant | Read-only sweep — every nav item; **assert every write control is absent or disabled** |
| FarmManager-B | Farm B only | Same as FarmManager, plus **attempt to reach Farm A and be refused** |
| Agronomist-B | Farm B only | Arabic/RTL session throughout; **assert no raw i18n keys render** |

### Act 5 — Reaction loop

Closes the loop that Act 3 opened.

- Agronomist accepts one recommendation and dismisses another.
- FarmManager acknowledges an alert in Action Center.
- FieldOperator completes the dispatched task.
- Harness re-triggers `evaluate_for_tenant`; agents assert state changed correctly — the accepted
  recommendation does not re-fire, the dismissed one behaves per spec, the alert clears.

### Act 6 — Verification

Two independent passes, neither performed by the agent that did the work.

**Refutation pass.** Every step that claimed a pass goes to a verifier prompted to *refute* it,
with the evidence attached. It defaults to "refuted" when the evidence is ambiguous. Only
survivors are reported as passes; refuted claims become findings against the harness, not the product.

**Invariant pass.** Cross-cutting assertions no single persona can make:

- **Farm-scope isolation** — Farm-B accounts saw zero Farm A identifiers in any response body.
- **No 500s** — the run ledger contains no 5xx from any persona.
- **No console errors** — per persona, per page.
- **No raw i18n keys** — no `^[a-z]+\.[a-z_.]+$` string rendered as visible text, EN or AR.
- **Capability parity** — frontend-resolved capabilities match `/v1/me` for every persona.
- **Notification dispatch** — capture table holds the alerts the run should have produced.

### Act 7 — Teardown and report

- Purge tenant, verify clean per P1.
- Emit the findings report; retain the ledger and evidence regardless of outcome.

---

## 4. Oracles — how a step is judged

Every persona step is declared before it is attempted:

```yaml
- step: agronomist.open_recommendation
  intent: "Open the top recommendation on Farm A block SIM-A-03"
  expect:
    ui: "Detail panel shows a rule name, a trigger date, and at least one action"
    api: "GET /v1/recommendations/{id} returns 200 with non-null decision_tree_id"
    data: "evaluation trace exists explaining why the tree fired"
  evidence: [screenshot, network_response, api_readback]
```

Three standing rules, each earned the hard way:

1. **The rendered body can lie.** A Playwright-served response has previously contradicted its own
   `content-length`. Any surprising body must be re-fetched with `curl` from the node before it is
   reported as a defect.
2. **Never assert from the UI alone.** UI plus API readback, or it isn't evidence.
3. **A 401 vs 404 difference proves nothing** about routing — auth middleware rejects pre-routing.
   Route existence is proven by introspecting `app.routes` in the pod.

---

## 5. Findings report

One markdown report per run, plus the raw ledger.

- Header: run id, timestamp, image SHAs per service, tenant slug, personas run, duration.
- **Blockers** — anything that would break a real customer on day one.
- **Defects** — confirmed, with persona, act, step, evidence paths, reproduction.
- **Unverifiable** — steps whose evidence was ambiguous; these are harness debt, and a growing
  count here means the harness is decaying.
- **Coverage gaps** — what this run did not touch (FCM push, the beat scheduler, real imagery
  acquisition, billing).

Findings are advisory. Nothing blocks a promotion automatically.

---

## 6. Build order

Each phase ends in something runnable; nothing is built on an unproven assumption.

**Phase 1 — Unblock (no agents yet).** P1 clean teardown, P2 trigger endpoint. **Code complete
and green in integration tests; the prod proof is outstanding** — three consecutive
provision/purge cycles against a deployed build, with no email suffix. *This phase alone is
worth shipping: both items are prod-ops improvements independent of any testing.*

One thing Phase 1 established that changes later phases: `frontend/e2e/fixtures.ts` is **fully
mocked** — fake JWT in sessionStorage, every `/api/v1/**` call intercepted, unmocked mutations
answering 501. It never reaches a backend and is no use as a base for live simulation. The real
starting point is `scripts/e2e/*.py`, which already does real Keycloak direct-grant against
prod.

**Phase 2 — Deterministic spine (no agents yet).** P3 clone tool, P4 notification sink, Acts 0–3
fully scripted, ending with asserted non-zero recommendations and alerts. Success: a tenant that
provisions, populates, fires trees, and purges — hands off, repeatably.

**Phase 3 — One agent.** P5 browser isolation and P6 ledger, then the Agronomist persona alone
through Act 4. This is where browser-driving cost and flakiness become real numbers instead of
estimates. Re-scope if it disappoints.

**Phase 4 — The swarm.** Remaining seven personas, concurrent Act 4, Act 5 reaction loop.

**Phase 5 — Judgment.** Act 6 refutation and invariant passes, Act 7 report. Only now does a run
produce a verdict worth reading.

**Phase 6 — Depth.** Widen persona shifts module by module against the now-stable spine.

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Purge gap unfixed | Fresh-tenant-per-run impossible; prod accumulates junk tenants | P1 is Phase 1, gating everything |
| Browser flakiness dominates | Findings are mostly harness noise; trust collapses | Phase 3 measures it on one persona before committing to eight |
| Act 3 silently seeds nothing | Every downstream assertion passes vacuously | Hard non-zero assertions between each trigger |
| Clone couples to Bashayer | Customer data change silently alters seeds | Snapshot once to R2, replay the snapshot |
| Agent self-congratulation | Green runs that mean nothing | Refutation pass; ambiguous evidence defaults to refuted |
| Token cost per run | Runs become too expensive to do often | Thin V1; Phase 3 gives a real per-persona cost figure |
| Real notifications escape | Emails or pushes reach real people | P4 sink is Phase 2, before any persona acts |
| Prod blast radius | An agent mutates something outside the sim tenant | Personas hold tenant-scoped tokens only; PlatformAdmin agent's shift is read-only after Act 1 |

---

## 8. Known coverage gaps (stated, not hidden)

- **The beat scheduler** — triggering tasks by hand does not prove they fire on schedule.
- **Real imagery acquisition** — the discovery → download → COG → histogram path is bypassed by
  the clone.
- **FCM push** — inert in prod until a Helm value sets `fcm_enabled`.
- **Billing** — no BillingAdmin persona in the roster.
- **Mobile Scout** — the APK cannot be browser-driven; would need an API-based agent.
- **Long-horizon behaviour** — anything spanning more than the seeded history window.
