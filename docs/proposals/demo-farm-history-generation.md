# Demo farm with generated history

Status: design only. No code written. Decisions taken 2026-09-03.

## Problem

A new tenant is empty. A sales prospect and a trial visitor both open a product
with no activities, no decision tree runs, no recommendations and no alerts. The
screens that carry the most value are the ones that need months of past use.

We want one farm whose data reads as if a team had used it for months. The rows
must carry past creation and update dates, not one seeding burst dated today.

## Where this was not written down

The roadmap (`prompts/roadmap.md`) has no item for this. `docs/proposals/` has
no file for it. The nearest existing work is
`docs/testing/org-simulation-harness.md`, which clones and date-shifts imagery
and weather only. It marks engine output as `DELIBERATELY_NOT_CLONED`.

## Decisions

| # | Decision |
| --- | --- |
| D1 | The users are sales demos on production and self-serve trial signups. |
| D2 | The past is produced by replaying the real engine under a fake clock, one simulated day at a time. |
| D3 | The base imagery and weather come from a purpose-built farm on a real area we do not sell to, filled once by the historical backfill from PR #303. |
| D4 | The history covers engine output, human work, signals and observations, notifications and audit events. |
| D5 | The operator sets the start and end dates. The span is not fixed. |
| D6 | A central clock helper is added. All 46 files that call `datetime.now` or `utcnow` are routed through it. |
| D7 | The unit is one farm inside an ordinary tenant, not a demo tenant. |
| D8 | A platform admin creating a tenant sees a `Deploy demo farm` choice. A trial signup gets the demo farm by default. No other tenant can generate history. |
| D9 | Inside a customer tenant the demo farm is fully editable. |
| D10 | The demo farm never counts towards the meter, the trial caps or billing. |
| D11 | When the trial ends, or the tenant moves to a paid plan, the demo farm becomes read-only. Daily imagery import, recommendation runs and every other compute for that farm stop. |
| D12 | The history is steered. We choose the incidents and the dates they happen on. |

## Shape that follows from the decisions

### Two phases, not one

Phase A, build. The replay runs once on an internal build tenant. This is the
only place the fake clock is ever active. It produces a snapshot file.

Phase B, load. Tenant creation and trial provisioning load that file as one farm
and rebase the dates to the tenant's own start day. This takes minutes and runs
no engine code.

D7 makes this split necessary and also makes it safe. Because a customer tenant
only loads rows, the fake clock never runs inside a customer tenant. That is a
stronger guard than the tenant flag first considered.

### The clock

Built, 2026-09-04. The clock has two halves that must report the same instant.

`app/shared/clock.py` exposes `now()`. In every normal run it returns the real
time. During a replay a context variable holds the simulated day. All 124 direct
`datetime.now(...)` calls in 45 files now go through it.

`public.app_now()` is the SQL half. It returns `now()` unless the Postgres
setting `agripulse.now` is present. All 234 bare `now()` calls in SQL strings go
through it, as do `public.set_updated_at()` and every column default that was
`now()`. `app/shared/db/session.py` writes the setting on transaction begin
while a simulated clock is active.

Both halves were needed. A Python-only clock cannot reach the 234 SQL call
sites, the `BEFORE UPDATE` trigger, or a stored column default.

Why not shadow `now()` through `search_path`. Measured on the production
database: a function in a schema placed ahead of `pg_catalog` does redirect raw
SQL and plpgsql bodies, including the existing trigger, but a stored column
default keeps calling `pg_catalog.now()` because the default is resolved when
the column is created. On top of that, 46 places in the application set their
own `search_path`, so any of them would drop the shim and the timestamps would
quietly become real again.

One rule follows from the design. The setting is written when a transaction
begins, so a replay must enter `clock.simulate(...)` before any statement opens
one. Entering it half way through a transaction moves the Python side and not
the SQL side. An integration test records this.

Celery is still open. A task runs in a worker process, so the context variable
does not cross the queue. The replay must run the task functions in its own
process, inside the simulate block.

### The flag

Built, 2026-09-04, in tenant migration 0091. `farms.is_demo` says the farm is
the seeded demo. `farms.demo_frozen_at` records when it was made read-only; NULL
means still live. A CHECK stops the two drifting: only a demo farm can be
frozen.

The flag drives four behaviours: exclusion from the meter and caps (D10), the
read-only switch (D11), stopping the imagery and recommendation schedules (D11),
and a label in the interface. The first is done. Nothing sets the flag yet; the
writer comes with tenant creation and trial provisioning.

### Scripted incidents

D12 means the replay reads an incident file. Each entry names a block, a date
and a condition to force, for example water stress in one block in week 6. The
replay steers the inputs so the real trees fire on those dates. Every workflow
screen then has a case to show.

## Traps already known

- The notification sink writes `notification_dispatches` rows with status
  `skipped`, not `sent`. The demo history needs realistic dispatch rows, so the
  sink must not be active on the build tenant, or the replay must write the
  status it wants.
- `_insert_rows` in `backend/app/modules/simulation/snapshot.py` runs one
  `execute` per row. The current snapshot load makes about 110,000 round trips.
  Adding engine output and human work makes this worse. The loader needs batch
  inserts before this is used in trial provisioning.
- Date-shifting must leave the `0001-01-01` valid-time sentinel alone.
  `_rebase()` in the same file already handles this.
- `weather_forecasts` runs ahead of the observation date. It is marked
  `forward_looking`. Any new forward-looking table needs the same mark.
- A new tenant table must join the purge manifest or the continuous integration
  run fails.

## Open questions

1. ~~How the database `now()` defaults are handled during replay.~~ Answered:
   migrations 0081 and 0090 rewrite every one of them to `public.app_now()`.
2. How the simulated day reaches a Celery worker.
3. Whether the customer can delete the demo farm, and what a complete delete
   removes.
4. Whether the demo farm keeps importing real daily imagery during the trial.
   D11 says this stops at trial end, which implies it runs during the trial and
   consumes provider quota.
5. Which area we use for the purpose-built farm.
6. How often the snapshot is rebuilt, and who rebuilds it.

## Phase 3, built 2026-09-15 — the replay runner

`app/modules/demo_history/` holds the day loop.

`steps.py` lists the work of one simulated day. Each step names a
per-tenant task function that the scheduler also calls in production, so
there is no second copy of the engine. The order and the cadence come from
`workers/beat/main.py`:

| Hour | Step | Cadence |
| --- | --- | --- |
| 05 | `phenology.advance_for_tenant` | daily |
| 06 | `indices.refresh_index_caggs_for_tenant` | daily |
| 06 | `indices.recompute_baselines_for_tenant` | Mondays |
| 06 | `weather.recompute_weather_baselines_for_tenant` | Mondays |
| 07 | `weather.compute_weather_risk_for_tenant` | daily |
| 07 | `weather.compute_spi_for_tenant` | daily |
| 08 | `irrigation.water_balance_for_tenant` | daily |
| 08 | `irrigation.generate_for_tenant` | daily |
| 09 | `grid.detect_anomalies_for_tenant` | daily |
| 10 | `recommendations.evaluate_for_tenant` | daily |

The hours are part of the data. Rows from one day carry different times of
day, and the order inside a day stays visible: a recommendation is stamped
after the index refresh that produced its input.

Imagery acquisition and weather fetching are not steps. Those rows come
from the historical backfill, which ran once against the real providers for
real dates. Asking a provider again for a date it has already served spends
quota and returns the same data.

`runner.py` moves the clock with `clock.simulate` around each step, not
around the whole day. The Postgres setting is written when a transaction
begins, so a clock moved after that point moves the Python side alone and
nothing reports an error.

Three guards run before any row is written:

1. The tenant schema must start with `DEMO_HISTORY_BUILD_SCHEMA_PREFIX`.
   The setting is empty by default, which means no tenant qualifies. That
   is the value production runs on.
2. The last day must be in the past.
3. A failing step stops the run. `--keep-going` turns that off.

The run returns a report. `totals()` sums each step's counts across the
span, so a step that produced nothing for months shows as a row of zeros
rather than passing unread.

`scripts/replay_demo_history.py` is the operator entry point. It runs the
steps in its own process, because a Celery worker is a different process
and the moved clock does not travel with a queued message.

`clock.real_now()` was added for the guard. A guard that called `now()`
would read the simulated instant it is meant to be checking.

### Answers to two open questions

Open question 2, how the simulated day reaches a Celery worker: it does
not. The replay calls the task functions in its own process. Each of them
is a synchronous wrapper around `asyncio.run`, and a `ContextVar` is copied
into the task that `asyncio.run` creates, so the clock reaches the async
body.

The notification sink, listed under Traps: leave the sink on for the build
tenant, so no mail can leave. The dispatch rows will read as suppressed.
The snapshot export rewrites their status when it copies them out. Sending
real mail from a replay has no upside and reaches addresses nobody owns.

### Not built yet

- Steered incidents (decision D12). The runner takes a step list, so an
  incident step can be added to it, but nothing forces a condition yet.
- Human work: acknowledging and closing items, scouting observations,
  applied plans. A recommendation opened by the replay stays open, because
  the engine is the only actor so far.
- The writer that sets `farms.is_demo`.
- Snapshot export and load, and the freeze at trial end.
