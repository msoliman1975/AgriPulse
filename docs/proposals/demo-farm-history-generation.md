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

`app/shared/clock.py` exposes `now()`. In every normal run it returns the real
time. During a replay a context variable holds the simulated day.

Two parts still need a decision, listed under Open questions:

- Database columns that default to `now()`. The context variable does not reach
  them. Either the replay passes the value explicitly, or the replay sets the
  Postgres session time.
- Celery tasks. A task runs in a worker process, so the context variable does
  not cross the queue. The replay must either run the task functions in process
  or pass the simulated day as a task argument.

### The flag

`farms.is_demo`, a boolean on the farm row. It drives four behaviours: exclusion
from the meter and caps (D10), the read-only switch (D11), stopping the imagery
and recommendation schedules (D11), and a label in the interface.

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

1. How the database `now()` defaults are handled during replay.
2. How the simulated day reaches a Celery worker.
3. Whether the customer can delete the demo farm, and what a complete delete
   removes.
4. Whether the demo farm keeps importing real daily imagery during the trial.
   D11 says this stops at trial end, which implies it runs during the trial and
   consumes provider quota.
5. Which area we use for the purpose-built farm.
6. How often the snapshot is rebuilt, and who rebuilds it.
