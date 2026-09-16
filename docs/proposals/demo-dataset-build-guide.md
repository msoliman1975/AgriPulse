# How to build the demo dataset

Status: guide. Written 2026-09-16 for branch `feat/demo-farm-history`
(pull request #695). It describes the whole job, including the parts that
are not built yet. Each step says whether the code exists today.

The goal is one farm whose screens read as if a real team had used the
product for two years: imagery, weather, index history, decision tree
runs, recommendations, alerts, scouting visits, observations, plans,
irrigation, notifications and audit.

## The rule that shapes everything

The past is produced once, on an internal build tenant, by running the
real engine under a moved clock. A customer tenant never runs the clock.
It loads a snapshot file and shifts the dates.

That split is why the guide has two halves. Steps 1 to 12 build the
snapshot. Steps 13 to 15 deliver it.

## What counts as an activity

Nothing in the product writes all of these. Each row has an author, and
the author decides which step produces it.

| What the demo must show | Table | Who writes it |
| --- | --- | --- |
| Satellite passes and index history | `imagery_ingestion_jobs`, `block_index_aggregates` | Backfill, step 5 |
| Weather history and daily derivations | `weather_observations`, `weather_derived_daily`, `weather_index_daily` | Backfill, step 5 |
| Index baselines and z-scores | `block_index_baselines`, `weather_index_baselines` | Replay, step 10 |
| Growth stage changes | `growth_stage_logs` | Replay, step 10 |
| Disease and pest risk, SPI | `weather_risk_daily`, `weather_index_daily` | Replay, step 10 |
| Water balance and irrigation proposals | `block_water_balance_daily`, `irrigation_schedules` | Replay, step 10 |
| Sub-block anomalies | `alerts`, from the grid anomaly sweep | Replay, step 10 |
| Decision tree runs and their traces | `decision_tree_block_verdicts`, evaluation runs and traces | Replay, step 10 |
| Recommendations and alerts | `recommendations`, `alerts` | Replay, step 10 |
| Acknowledging, dispatching, closing an item | `recommendations`, `recommendations_history`, `alerts` | Actors, step 11 |
| Scouting visits, their acceptance and completion | `scouting_visits` | Actors, step 11 |
| Field observations, photos, notes | `signal_observations`, `block_attachments` | Actors, step 11 |
| Plans and their activities | `vegetation_plans`, `plan_activities` | Actors, step 11 |
| Irrigation logged as carried out | `irrigation_schedules` | Actors, step 11 |
| Crop attribute changes over time | `block_crop_attribute_values`, `block_crop_attribute_value_log` | Actors, step 11 |
| Responsibility changes | `block_responsible_log` | Actors, step 11 |
| Emails, push and in-app messages | `notification_dispatches`, `in_app_inbox` | Replay and actors, step 12 |
| Audit trail | `audit_events`, `audit_data_changes` | Every write that goes through a service |
| Product telemetry | `usage_events` | Optional, step 12 |

The last two rows are the reason the actor layer must call the service
layer rather than write SQL. Audit rows, history rows and notifications
are side effects of the services. A direct INSERT produces a farm whose
screens look full and whose audit trail is empty.

---

## Part one: build the snapshot

### Step 1 - Fix the inputs

Decide these before any code runs. Each one is hard to change later.

1. The span. Two years, ending about one month before today. The last day
   must be in the past; the runner refuses today.
2. The area. A real place we do not sell to, large enough for 8 to 15
   blocks. Imagery is dense from 2018 onward, so any recent two years
   work.
3. The crops. Pick crops whose decision trees are already authored, so
   the engine has something to say. Mango has 41 trees today.
4. The team. Five or six people: a tenant owner, a farm manager, two
   agronomists, two scouts. Every human action needs an author, and the
   screens show names.
5. The incidents. About 20 over two years. Each one names a block, a date
   and a condition, for example water stress in block 4 in week 6.

Status: your decisions. Nothing to build.

### Step 2 - Stand up a build environment

The replay writes past timestamps into real tables. Keep it away from
production data.

- A separate database, or at least a separate tenant on a cluster that is
  not production.
- `DEMO_HISTORY_BUILD_SCHEMA_PREFIX` set to the prefix of that tenant's
  schema. It is empty everywhere else, and the runner refuses to start
  without it.
- `NOTIFICATION_SINK_TENANT_PREFIX` set to the same tenant, so no mail can
  leave. The dispatch rows then read as suppressed; step 13 rewrites the
  status when it exports them.
- Provider credentials for imagery and weather, because step 5 makes real
  provider calls.

Status: the setting and the guard exist. The environment is yours to
create.

### Step 3 - Create the tenant and the people

Create the tenant, then create one user per person from step 1 and give
each one their role and farm scope. Use the platform admin API, the same
path a real tenant takes.

Status: exists.

### Step 4 - Draw the farm

Create the farm, its blocks, the crop on each block, the grid
configuration, and the imagery and weather subscriptions.

Two traps. A farm that fetches its whole boundary needs `fetch_farm_aoi`
set, or the farm-level sweep enqueues nothing. A block with no crop is
skipped by most trees.

Status: exists.

### Step 5 - Backfill imagery and weather for the whole span

    python -m scripts.backfill_history \
        --tenant-schema tenant_demobuild_ab12 \
        --from 2024-09-01 --to 2026-08-31

This lands raw scenes and raw hourly weather. Then compute the indices
per scene and the weather indices per farm. Weather reaches back to 1940;
imagery is dense from 2018.

This is the slowest step and it spends provider quota. Run it once and
keep the database.

Status: exists.

### Step 6 - Check the backfill before going further

Count scenes per month, and index rows per block per month. A gap here
becomes a flat line in every later screen, and the replay will not tell
you: a tree with no index simply does not fire.

Status: manual today. Worth a small script.

### Step 7 - Author the catalogue

The engine answers with whatever is authored:

- Decision trees for the chosen crops, published, and not excluded by the
  farm's tree selection.
- Signal definitions, and the templates a scout fills in.
- Plan templates for the crop's season.
- Resources: the workers and equipment an activity is assigned to.
- Scouting routing rules, so a visit is auto-assigned rather than left in
  triage.

Status: exists. The content is a decision.

### Step 8 - Write the incident script

Each entry names a block, a date and a condition to force. The replay
steers the inputs so the real trees fire on those dates. Without this the
history is whatever the weather happened to do, and a demo needs a water
stress case, a disease risk case and a pest case on known days.

Status: not built. The runner takes a step list, so an incident step fits
in front of the engine step.

### Step 9 - Measure one day

Run the replay for a single day and read the counts.

    python -m scripts.replay_demo_history \
        --tenant-schema tenant_demobuild_ab12 \
        --from 2026-08-01 --to 2026-08-01

Read every step. A step that returns zeros on a day with imagery is a
fault, not quiet weather. Multiply the time by the number of days before
starting the full span.

Status: exists.

### Step 10 - Run the replay across the span

    python -m scripts.replay_demo_history \
        --tenant-schema tenant_demobuild_ab12 \
        --from 2024-09-01 --to 2026-08-31

Ten steps run per day, in the order the scheduler uses: growth stage,
index aggregates, weekly baselines, weather risk, SPI, water balance,
irrigation proposals, grid anomalies, then the decision tree sweep. A
failing step stops the run; `--keep-going` turns that off.

Read the totals at the end before believing any screen.

Status: exists.

### Step 11 - Add the human work

After step 10 the farm has a full engine history and no people in it.
Every recommendation the engine opened is still open, no visit was ever
made, and no plan was applied.

This is the largest unbuilt piece. The shape that fits the runner:

- An actor step runs each simulated day, after the engine step.
- It reads what is open, then performs a share of it through the service
  layer as a named user: acknowledge, dispatch to a scout, complete the
  visit with observations and a photo, close the item.
- It applies a plan at the start of a season, and marks activities done
  on their dates.
- It logs irrigation as carried out on some of the proposals.
- It leaves some items open and some overdue, because a demo with a clean
  inbox looks unused.

The rule: call the services, not the tables. Audit rows, history rows and
notifications only exist if a service wrote them.

Status: not built.

### Step 12 - Notifications, audit and telemetry

The notification sink is on for this tenant, so dispatch rows are written
and suppressed. Check that each digest has rows on the days the engine
found something. Scheduled sweeps have never registered subscribers, so
confirm the replay path produces the emails you expect rather than
assuming it does.

Status: partly exists. Verify rather than assume.

---

## Part two: deliver it

### Step 13 - Export the snapshot

One file: the farm, its blocks, the imagery and weather history, the
engine output and the human work. Two rewrites happen here: the dispatch
status becomes `sent`, and every date becomes an offset from the last day
so the loader can rebase it.

Status: not built. The existing snapshot loader inserts one row per
statement, about 110,000 round trips, so it needs batch inserts before
trial provisioning uses it.

### Step 14 - Load it into a tenant

Tenant creation gets a `Deploy demo farm` choice, and a trial signup gets
the farm by default. The loader creates one farm with `is_demo` true and
shifts every date to the tenant's own start day.

The demo farm is fully editable inside the customer tenant, and it never
counts towards the meter, the caps or billing.

Status: the column and the meter exclusion exist. Nothing sets the flag,
and the loader is not built.

### Step 15 - Freeze it

At trial end, or when the tenant moves to a paid plan, `demo_frozen_at` is
stamped. The farm becomes read-only and its scheduled work stops: no
imagery import, no tree runs, no index recomputation.

Status: the column exists. The freeze is not built.

---

## How to check the result

Open the product as each persona and read the screens, in this order.
Each one fails differently, so a green step above proves little.

1. Farm map and the date bar. Are there passes every few days across the
   whole span, or a gap?
2. Index charts. Do they move with the season, and is there a baseline
   band?
3. Farm Health. Are blocks classified, and does each verdict name a tree
   and show its reasoning?
4. Action Center. Is there a mix of open, dispatched, done and dismissed,
   with names and dates on them?
5. Scouting. Are there completed visits with observations and photos?
6. Timeline. Does the replay show change across the whole span?
7. Reports. Does a report over the span return rows?
8. Audit. Does each human action have an entry with the right author and
   date?

A screen that is empty is usually one missing input, not a broken
feature. Trace it back to the step that should have written the row.

## The order that matters

Steps 3, 4, 5 and 7 must all be finished before step 10. The engine reads
imagery, weather, crops and trees; any one of them missing produces a
silent zero rather than an error. Step 11 must run after step 10 for each
day, because a person cannot close an item that has not been opened.
