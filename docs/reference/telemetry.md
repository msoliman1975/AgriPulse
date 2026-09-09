# Product telemetry — reference

**Status:** shipped (Phase A) · **Owner:** platform · **Last updated:** 2026-09-08

This is the page you show someone who asks what we collect. It lists every
event, every field, every allowed prop, and how long each is kept. It is not a
design document — that is
[`docs/proposals/product-telemetry-plan.md`](../proposals/product-telemetry-plan.md).

**Keep it current.** Any PR that changes
`backend/app/modules/telemetry/taxonomy.yaml` changes this page too. A taxonomy
reference that has drifted from the code is worse than none, because people
still believe it.

---

## 1. What this is for

Four questions:

1. How is the product used?
2. Where do people spend time?
3. Which capabilities matter?
4. Where do people struggle?

Four decisions that shape everything below:

| Decision | Choice |
|---|---|
| Where the data lives | First-party, our own TimescaleDB. No SaaS, no vendor egress. |
| Who reads it | The platform team only. There is no tenant-facing surface. |
| Identity grain | Full identity — `user_id`, `tenant_id`, role. Not pseudonymous. |
| "Struggle" | Derived from events plus the API error path. No session replay, no rage-click capture. |

---

## 2. What we do NOT collect

Stated first, because it is the part people actually want to know.

- **No IP address and no user-agent string.** `audit_events` already carries
  those for the security trail. Product telemetry has `device_kind`
  (desktop/tablet/mobile, derived from viewport width) and `viewport_w`, which
  answer the only product question here — "is anyone using this on a phone in
  the field?" — without the fingerprint.
- **No free text of any kind.** No farm names, no block notes, no coordinates,
  no search terms, no form values.
- **No error messages.** A thrown message interpolates whatever the code put in
  it. `client_error` carries an error *name* and a stack *fingerprint*, never
  the message.
- **No resolved URLs.** `route` is always a template — `/insights/:farmId`, never
  `/insights/8f3a…`. Ids live in typed columns.
- **No DOM capture, no keystrokes, no screen recording.**
- **Nothing the client asserts about identity.** `user_id`, `tenant_id`,
  `actor_role` and `is_platform_staff` are stamped server-side from the
  validated JWT. The client's request model cannot even express them, and any
  such key in a payload is discarded.

---

## 3. Retention

Enforced by TimescaleDB policies in migrations `0082` and `0083`, not by intent.

| Store | Kept | Compressed |
|---|---|---|
| `public.usage_events` (raw) | **180 days** | after 14 days |
| `public.usage_daily` (rollup) | **730 days** (24 months) | — |
| `public.usage_flow_daily` (rollup) | **730 days** (24 months) | — |

The rollups outlive the raw events on purpose: that is what makes
year-over-year adoption answerable at a fraction of the storage.

**Telemetry does not survive a tenant purge.** Both `tenant_id` and `farm_id`
are registered in `backend/app/shared/purge/registry.py`, and the purge also
refreshes both continuous aggregates so a purged tenant's materialised buckets
go with the rows. There is no archive and no summary row — this was decided,
not deferred. The accepted cost: a churn post-mortem has to be taken from the
dashboard **while the tenant is still live**.

---

## 4. Kill switches

Either one off means nothing is collected, and the app is unaffected.

| Switch | Where | Effect |
|---|---|---|
| `VITE_TELEMETRY_ENABLED=false` | frontend build env | `track()` returns on its first line. The queue is never allocated and no listener is registered. |
| `TELEMETRY_INGEST_ENABLED=false` | backend settings | The endpoint still answers `202` (so a client running ahead of a rollback logs no errors) and stores nothing. |

---

## 5. Events

Ten names, closed. The server rejects anything not listed here and drops just
that event, never the batch.

| `event_name` | Fires when | Carries | Answers |
|---|---|---|---|
| `session_start` | SDK init, once per session | `locale`, `device_kind`, `app_version` | sessions, DAU/WAU/MAU |
| `session_end` | 30 min idle or tab close | `duration_ms` | session length |
| `page_view` | Route committed | `route`, `farm_id` | where people go |
| `page_leave` | Route change, tab hidden, unload | `route`, `duration_ms` | **where time goes** |
| `feature_used` | Explicit `track()` on a meaningful action | `feature`, `props` | **which capabilities matter** |
| `flow_start` | Entering a tracked funnel | `flow` | funnel entry |
| `flow_step` | Advancing a funnel | `flow`, `step` | drop-off point |
| `flow_complete` | Funnel succeeded | `flow`, `duration_ms` | conversion |
| `api_error` | The axios interceptor rejected a call | `route`, `status_code`, `error_code`, `correlation_id` | **struggle** |
| `client_error` | ErrorBoundary, `window.onerror`, unhandled rejection | `route`, `error_code` | **struggle** |

There is no `flow_abandon`. Abandonment is derived server-side — a `flow_start`
with no `flow_complete` for that session inside the flow's timeout. Emitting it
from the client would be unreliable in exactly the case we care about most: the
person who closed the laptop sends nothing.

### 5.1 Allowed props, per event

Any key not listed is **dropped on ingest**, not stored. This allow-list is the
single control that keeps agronomic and customer content out of the store.

| Event | Allowed `props` keys |
|---|---|
| `session_start`, `session_end`, `page_view`, `flow_*` (except below) | — |
| `page_leave` | `hidden_ms` |
| `feature_used` | `action`, `index_code`, `count`, `source` |
| `flow_start` | `entry_point` |
| `flow_step` | `attempt` |
| `flow_complete` | `steps_taken` |
| `api_error` | `method`, `problem_type`, `retry_count`, `api_route` |
| `client_error` | `component`, `digest` |

Values must stay low-cardinality and non-identifying: enum-ish strings, counts,
booleans. Never free text, never a name, never a geometry.

---

## 6. Columns

`public.usage_events`. "Server" means the client cannot set it.

| Column | Source | Notes |
|---|---|---|
| `time` | client, clamped | Outside `now ± 5 min` it is replaced with server time floored to the minute, so a resent beacon still collapses on `(time, id)`. |
| `id` | client (uuid7) | The idempotency key for a resent beacon. |
| `schema_version` | server | The taxonomy version that validated the event. |
| `session_id` | client | A browser-tab visit, not a login. Ends after 30 min idle. |
| `user_id`, `tenant_id`, `actor_role`, `is_platform_staff` | **server** | From the validated JWT. `tenant_id` is NULL for platform staff. |
| `event_name`, `feature`, `flow`, `step` | client, validated | Rejected if not in the vocabulary. |
| `route` | client | Template only. |
| `farm_id` | client | From the matched route params. |
| `outcome` | client | `ok` \| `error` \| `abandoned` \| `cancelled` (CHECK constraint). |
| `duration_ms` | client | Visible dwell for `page_leave`; perceived latency for an action. |
| `status_code`, `error_code` | client | |
| `correlation_id` | client | The `x-correlation-id` off the failed response. Joins to the server log line and the trace. Requires the API to name it in `Access-Control-Expose-Headers` — the SPA and the API are different origins, and a browser hides every response header from cross-origin JS otherwise. Without that it is silently NULL, which is how the first 20 rows landed. |
| `locale` | **server** | From `RequestContext.preferred_language`. |
| `app_version` | client | The **7-character git SHA**, which is exactly the GHCR image tag the cluster runs — so a row joins to a deployed image by equality. Passed to the frontend image as the `APP_VERSION` build arg; a container build inherits no workflow env and the context has no `.git`, so nothing inside the image can derive it. Reads `dev` only for a local build. |
| `device_kind`, `viewport_w` | client | Derived from viewport width, not the UA string. |
| `props` | client, allow-listed | See §5.1. |

---

## 7. Capabilities and flows

**Features** — the closed enum in `taxonomy.yaml`. Coarse on purpose: one entry
per capability we would make a roadmap decision about.

```
farm_console · farm_create · block_create · bulk_aoi_upload · block_defaults
grid_config · imagery_config · weather_config · backfill_console
insights · index_chart · weather_chart · board · plan_template
alerts · recommendations · decision_tree_authoring · decision_tree_dryrun
signals · reports · report_export · settings · users_admin · platform_admin
```

A feature in the enum with no `track()` call yet reads as **cold** on the
dashboard, not as missing. Check instrumentation before concluding a capability
is unused.

**Flows**

| Flow | Steps | Timeout |
|---|---|---|
| `farm_onboarding` | `draw_or_upload` → `details` → `blocks` → `subscriptions` | 60 min |
| `backfill_run` | `select_farm` → `select_range` → `preview` → `submit` | 30 min |
| `block_bulk_upload` | `pick_files` → `map_columns` → `reconcile` → `commit` | 30 min |
| `decision_tree_authoring` | `open` → `edit` → `dry_run` → `publish` | 120 min |

---

## 8. How to add an event, feature, or flow

1. Edit `backend/app/modules/telemetry/taxonomy.yaml`. That file is the single
   source of truth.
2. Run `python backend/scripts/gen_telemetry_taxonomy.py` to regenerate
   `frontend/src/telemetry/taxonomy.generated.ts`. Do not hand-edit it — CI
   fails if it does not match the YAML.
3. Add the `track()` / `trackFeature()` call site.
4. **Update this page in the same PR.**

If you add a new `props` key, justify it in review: the allow-list is the whole
privacy control, and every key added widens what can land.

---

## 9. Reading the data

**`/platform/usage`** — the curated dashboard. Needs `platform.read_usage`
(PlatformAdmin, PlatformSupport). Excludes platform staff by default; the
toggle is visible, so nobody reads a number without knowing which population it
describes.

**Ad-hoc SQL** — for questions the page does not answer. Read
`public.usage_daily` when the aggregate can answer it (24 months, far smaller);
read `public.usage_events` for distinct sessions, funnel pairing, and
percentiles, which the aggregate structurally cannot hold.

Grafana as a third surface is **not set up**. The `observability-*` ArgoCD apps
still carry AWS-era values (`storageClassName: gp3`, an
`*.agripulse.local` ingress host), so their health on the Hetzner node has to be
verified before anyone plans on it.

---

## 10. Answering a product question — a runbook

**"Nobody uses Reports, should we drop it?"**
Open `/platform/usage`, 90 days. Check the cold-capability list. If `reports` is
there, check `git grep 'trackFeature("reports"'` before concluding — a
capability with no call site is invisible, not unused.

**"Which surface should we invest in?"**
"Where time goes", sorted by total dwell. Read the *median visit* beside it: a
big total with a small median is a page people pass through, not one they work
in.

**"A customer says the app is broken."**
Struggle board → error-dense routes to find the surface. Then "recent failures"
for that route, take the `correlation_id`, and search the server logs and traces
with it. That id is the join, and it is the reason this store is worth having.

**"Is this tenant churning?"**
Tenant health: last seen, WAU, and capabilities used. Breadth is the signal —
a tenant on two capabilities is a different risk from one on twelve at the same
event count. Take the reading **while they are still live**; a purge takes their
telemetry with it.

**"Why do people give up on onboarding?"**
Funnels. The `died_at` step names where. "Bounced at entry" means they left
before the first step, which points at a different fix from a mid-flow stall.
Getting from *where* to *why* is Phase B.
