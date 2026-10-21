# Season as an entity

Design document. Written 2026-09-09. Not implemented.

Supersedes topic T-1, "Is a season a formal thing?", in `prompts/roadmap.md`.

This document has two halves. Sections 1 to 10 are the design. Section 11 holds
the implementation prompts, written so another session can build each part
without re-reading the discussion.

---

## 1. The problem

There is no season entity. The word "season" appears as free text in two tables
that do not reference each other.

- `block_crops.season_label` — `TEXT`, max 64. The user types it.
  `CropAssignmentPanel.tsx:80` is an empty text box with no list and no format
  rule.
- `vegetation_plans.season_label` plus `season_year` — `TEXT` and `INTEGER`.
  `ApplyTemplateDialog.tsx:47` defaults the label to the current year.

Nothing joins them. `docs/data_model.md:507` gives three formats on one line:
`2026-summer`, `2025-2026`, and `Y3`. The third is tree age, not a season.

### Four parts of the system decide when a season starts, and they disagree

1. `weather/derivations.py:141`, `cumulative_gdd_base10_for_season` sums
   `gdd_base10` from 1 January of the given year. The schema at
   `docs/data_model.md:852` says "reset by event". The event was never built.
2. `farms/phenology.py:14` advances the growth stage from
   `block_crops.planting_date`, per block.
3. `plan_templates/apply.py:49` builds every perennial stage date as
   `date(season_year, month, day)`, so it anchors on the calendar year.
4. `block_crops.effective_from` and `effective_to` are a half-open range, and
   are the only correct start and end dates in the system today.

### Two failures this causes now

An Egyptian winter crop runs October to May. The season-to-date growing degree
day total resets on 1 January, in the middle of that crop. Every report and
every decision tree reading `gdd_cumulative_base10_season` sees a number that
restarted 4 months into a 7 month crop.

A perennial stage window written `12-15` to `01-20` maps both ends onto one
`season_year`. The January end lands 11 months before the December start.

### A third thing, found while writing this

`start_date` is not stored anywhere. In `plan_templates/schemas.py:125` it is a
field on the apply request body. The user types a start date per block on every
apply call, and nothing keeps it. Every activity anchored on `start` or on a
`milestone` is built from that typed number. Re-applying the same template next
month gives different dates.

---

## 2. What the industry actually defines

The starting assumption was that season start, end, and other attributes are
already defined by the industry, driven by crop or variety plus geography. That
is partly right.

### What is right

Public reference data exists and is stable.

- The [FAO Crop Calendar](https://data.apps.fao.org/catalog/dataset/crop-calendar-and-crop-activities)
  publishes sowing and harvesting windows per country, per crop, per
  agro-ecological zone, with sowing rates and main practices.
- The [EU Joint Research Centre](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC112670/development_national_sub-national_crop_calendars_data_set_compatible_with_remote_sensing.pdf)
  publishes national and sub-national crop calendars built for remote sensing
  use, which is the same shape this platform needs.
- [Growing season](https://en.wikipedia.org/wiki/Growing_season) length varies by
  latitude, and season modality varies by country. Some countries are unimodal,
  some bimodal, and some seasons span two calendar years.

### Three corrections to the assumption

**Crop plus geography is not enough.** The planting window itself is a third
driver. In Egypt, potato has three separate plantings in one calendar year:
summer, nili, and winter. Same crop, same region, three different seasons. Wheat
in Egypt is one winter season. So the key is crop, region, and season type.

**Perennials do not fit the annual shape.** Mango, dates, and coffee are not
planted and harvested in one season. The tree lives for decades. Their cycle is
a bearing year anchored on flowering, not on planting.

**The industry defines a window, not an instance.** FAO says potato is planted in
Egypt between two dates. It does not say that block B-14 was planted on
3 October 2026. Those are two different records, and the design keeps them apart.

### The five crops you named

| Crop | Cycle | What the season is anchored on |
| --- | --- | --- |
| Potato | Annual, about 90 to 120 days | Planting date. Egypt has three plantings a year: summer, nili, winter. |
| Wheat | Annual, about 150 to 180 days | Sowing date. Egypt is one winter season, sown November to December. |
| Mango | Perennial, one bearing year | Flowering. Fruit matures 100 to 150 days after flowering. Egyptian harvest runs July to November. Alternate bearing is common, a heavy year then a light year. |
| Dates | Perennial, one bearing year | Pollination in spring, harvest late summer to autumn. |
| Coffee | Perennial, **24 months**, cycles overlap | See the following subsection. |

### Coffee is the shape that breaks a simple model

[Camargo and Camargo (2001)](https://www.scielo.br/j/brag/a/DHJFXMkTxK5wJX5q74xhw3p/?lang=pt),
the standard Brazilian reference, gives arabica a 24-month cycle in six
phenological phases. Two phases fall in year one and four in year two.

- Year one, phase 1: vegetative, September to March, long days, grows the nodes.
- Year one, phase 2: vegetative, April to August, short days, turns the
  vegetative buds on those nodes into flower buds.
- Year two, phases 3 to 6: flowering, fruit fill, ripening, and rest.

The cycles **overlap**. While year two of one cycle is fruiting, year one of the
next cycle is running on the same tree on the same day. This is not an edge
case. It is true from the first reproductive cycle onward.

Brazil also has the on-year and off-year swing. An on-year crop can rise 5 to 10
million bags and fall by a similar amount the following off year, which is most
of the year-to-year variation in world arabica supply.

### Why this rules out putting the season on `block_crops`

`block_crops` is a valid-time occupancy record. Its own comment at
`farms/models.py:505` says a perennial orchard has no `effective_to` until it is
grubbed up, and that harvest is not the end of occupancy. So a mango or coffee
block has one `block_crops` row covering 20 years and 20 seasons. There is also
a partial unique index keeping one current assignment per block, so two
overlapping coffee cycles cannot be two `block_crops` rows.

---

## 3. Decisions taken

Ten questions were asked and answered on 2026-09-08 and 2026-09-09.

| # | Question | Decision |
| --- | --- | --- |
| 1 | How many entities? | Two. A knowledge base window in `public`, and a farm-side instance in the tenant schema. |
| 2 | Grain of the instance? | The crop assignment. |
| 3 | Where does the growing degree day total live? | Per crop cycle, computed on read, not stored. |
| 4 | How do perennials fit decision 2? | One cycle table under `block_crops`. One row for an annual, many for a perennial, overlapping allowed. |
| 5 | Geography key? | Country plus a seeded agro-zone catalog. Most specific match wins. |
| 6 | Who owns the knowledge base? | The platform. Tenants read only. |
| 7 | Who creates a cycle? | The crop assignment opens the first one. A nightly job opens later ones for perennials. |
| 8 | Coffee has two open cycles. Which one? | Derive it. The open cycle whose end date is nearest in the future. Screens can list both. |
| 9 | Existing `season_label` rows? | Open one cycle per assignment, copy the label into the cycle name, leave the window unset. |
| 10 | First release scope? | All four parts: schema and job, seed data, plan template rewiring, and the growing degree day change. |

---

## 4. The model

Three new tables and six changed ones.

```
public.agro_zones                    public.season_definitions
  code         EG-DELTA                crop_path       'potato'
  country_code EG                      country_code    'EG'
  name_en / name_ar                    agro_zone_code  'EG-DELTA' or NULL
        ^                              season_type     'winter'
        |                              start_month_day '10-01'
        |                              typical_duration_days 168
  farms.agro_zone_code                       ^
                                             | logical UUID, no DB FK
                                             |
  block_crops  (occupancy, unchanged)        |
       |                                     |
       +--< block_crop_cycles ---------------+
              start_date / end_date
              season_year, bearing_class
                    ^
                    | cycle_id
                    |
              plan_activities
```

### 4.1 `public.agro_zones` (new)

A small curated catalog of sub-national growing zones, one level below country.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | primary key, uuid v7 default |
| `code` | TEXT | not null, for example `EG-DELTA`. Immutable. |
| `country_code` | TEXT | not null, ISO 3166-1 alpha-2. Logical reference to `public.countries.code`, no database foreign key. |
| `name_en` | TEXT | not null |
| `name_ar` | TEXT | not null |
| `description` | TEXT | null |
| `is_active` | BOOLEAN | not null, default true |

Constraints: unique on `code` where `deleted_at IS NULL`. Index on
`country_code`.

### 4.2 `public.season_definitions` (new)

The knowledge base window. Platform-owned. There is no `tenant_id` column,
because decision 6 made this platform-only.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | primary key |
| `code` | TEXT | not null, unique, for example `potato-eg-delta-winter` |
| `crop_path` | TEXT | not null. Prefix-matched against `block_crops.crop_path`, the same rule `plan_templates.crop_path` already uses. |
| `country_code` | TEXT | null means any country |
| `agro_zone_code` | TEXT | null means any zone inside `country_code` |
| `season_type` | TEXT | not null. Check: `winter`, `summer`, `nili`, `spring`, `autumn`, `annual`, `bearing`, `biennial`. |
| `cycle_kind` | TEXT | not null. Check: `annual`, `perennial_bearing`, `perennial_multi_year`. |
| `name_en` | TEXT | not null |
| `name_ar` | TEXT | not null |
| `start_month_day` | TEXT | not null, format `MM-DD`. When a cycle opens. |
| `typical_duration_days` | INT | not null. Potato 168. Coffee 730. |
| `sow_window_start_month_day` | TEXT | null, `MM-DD` |
| `sow_window_end_month_day` | TEXT | null, `MM-DD` |
| `harvest_window_start_month_day` | TEXT | null, `MM-DD` |
| `harvest_window_end_month_day` | TEXT | null, `MM-DD` |
| `season_year_rule` | TEXT | not null. Check: `start_year`, `end_year`. Says which calendar year names the season. |
| `rollover_month_day` | TEXT | null. When the nightly job opens the next cycle. Falls back to `start_month_day`. |
| `alternate_bearing` | BOOLEAN | not null, default false |
| `source` | TEXT | null. Where the window came from, for example `FAO crop calendar` or `Camargo 2001`. |
| `status` | TEXT | not null, default `draft`. Check: `draft`, `published`, `archived`. |
| `is_active` | BOOLEAN | not null, default true |

Constraints: unique on
`(crop_path, country_code, agro_zone_code, season_type)` where
`deleted_at IS NULL`.

There is no `spans_year_boundary` column. It is computed from
`start_month_day` plus `typical_duration_days`. Storing it would give one fact
two sources.

### 4.3 `tenant_*.block_crop_cycles` (new)

The season instance. One row per growing cycle on one crop assignment.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID | primary key |
| `block_crop_id` | UUID | not null, foreign key to `block_crops.id`, on delete cascade |
| `block_id` | UUID | not null, foreign key to `blocks.id`, on delete cascade. Denormalised so the board and the growing degree day query skip a join, the same reason `plan_activities.farm_id` exists. |
| `farm_id` | UUID | not null, foreign key to `farms.id`, on delete cascade. Same reason. |
| `season_definition_id` | UUID | null. Logical reference to `public.season_definitions.id`. **Never a database foreign key.** Null means no window matched. |
| `season_year` | INT | not null |
| `name` | TEXT | null. Display name. Defaults from the window. |
| `start_date` | DATE | not null |
| `end_date` | DATE | null. Null means still open. |
| `planned_harvest_date` | DATE | null |
| `actual_harvest_date` | DATE | null |
| `bearing_class` | TEXT | null. Check: `on`, `off`, `regular`. |
| `status` | TEXT | not null, default `active`. Check: `planned`, `active`, `harvested`, `closed`, `cancelled`. |
| `source` | TEXT | not null, default `manual`. Check: `manual`, `crop_assignment`, `rollover`. |
| `notes` | TEXT | null |

Constraints and indexes:

- Unique on `(block_crop_id, season_year, season_definition_id)` where
  `deleted_at IS NULL`. This is the guard that stops the rollover job opening
  a second row for a period it already opened.
- Check `end_date IS NULL OR end_date > start_date`.
- Index on `(block_id, start_date DESC)`.
- Index on `(farm_id, status)`.

Overlapping rows on one `block_crop_id` are allowed on purpose. That is coffee.

### 4.4 Changed tables

| Table | Change |
| --- | --- |
| `farms` (tenant) | Add `agro_zone_code TEXT NULL`. Logical reference to `public.agro_zones.code`. |
| `block_crops` (tenant) | Drop `season_label`. |
| `vegetation_plans` (tenant) | Drop `season_label`. Add `season_definition_id UUID NULL`. Keep `season_year`. |
| `plan_activities` (tenant) | Add `cycle_id UUID NULL`, foreign key to `block_crop_cycles.id`, on delete set null. |
| `plan_templates` (public) | Rename `region` to `agro_zone_code`. Add `season_definition_id UUID NULL`, foreign key to `public.season_definitions.id`, on delete set null. |
| `weather_derived_daily` (tenant) | Drop `gdd_cumulative_base10_season`. See section 6. |

`uq_vegetation_plans_farm_season_active` moves from `(farm_id, season_label)` to
`(farm_id, season_definition_id, season_year)`. See the trap in section 9 about
nulls in that index.

### 4.5 Resolving the window for a block

Given a block's `crop_path`, its farm's `country_code` and `agro_zone_code`, and
a `season_type`, take the first match in this order.

1. `crop_path` exact, country matches, zone matches
2. `crop_path` exact, country matches, zone is null
3. `crop_path` exact, country is null, zone is null
4. Repeat 1 to 3 walking `crop_path` up one segment at a time
5. No match. The user types the dates.

Step 4 reuses `app.shared.crop_taxonomy.path_matches`, which
`plan_templates/service.py:201` already uses. Do not write a second matcher.

### 4.6 The current cycle

A consumer that needs exactly one cycle for a block takes the open cycle whose
`end_date` is nearest in the future.

```sql
SELECT * FROM block_crop_cycles
WHERE block_id = :block
  AND status IN ('planned', 'active')
  AND deleted_at IS NULL
  AND (end_date IS NULL OR end_date >= CURRENT_DATE)
ORDER BY end_date NULLS LAST
LIMIT 1
```

For a coffee block this picks the fruiting cycle, which is what a grower means
by "this season". This is derived on every read. There is no stored flag,
because a flag written by both a job and a user drifts.

---

## 5. How this works with Plan Template and Plan

The two seasons have two different jobs. The window talks to the template,
because both are reference data. The cycle talks to the plan and to apply,
because both hold real dates.

### 5.1 Window to Plan Template

| Change | Today | After |
| --- | --- | --- |
| Geography | `plan_templates.region`, free text, 64 characters, no catalog, no validation | `agro_zone_code`, the same catalog and the same match order as the window |
| Which season | nothing | `plan_templates.season_definition_id`, nullable |
| Discovery | matches on `crop_path` only | matches on the block cycle's `season_definition_id` first, then falls back to `crop_path` |

The second row closes a real gap. Egyptian potato has three plantings a year.
Today one template says `crop_path = 'potato'` and cannot say which planting it
is for. With the link, "Potato winter Delta" and "Potato summer Delta" are two
templates, each tied to its own window.

### 5.2 Cycle to Plan

`vegetation_plans` stays farm-level. A template is already crop-specific through
`crop_path`, so a plan is already about one crop. The header changes from
`(farm_id, season_label, season_year)` to
`(farm_id, season_definition_id, season_year)`.

### 5.3 Cycle to Apply

This is where most of the value is.

1. `block_start_date` stops being typed. `plan_templates/service.py:221` reads
   `block_crop_cycles.start_date` instead of `blk.start_date`. Re-applying the
   same template gives the same dates.
2. The perennial line `date(season_year, month, day)` at `apply.py:49` resolves
   against the cycle. A window written `12-15` to `01-20` currently puts the
   January end 11 months early. Anchored on the cycle, both ends land correctly.
3. Block selection changes. `list_current_block_crops` in
   `plan_templates/repository.py:347` picks rows where `is_current = TRUE`, one
   per block. With cycles a coffee block has two open cycles, so apply asks
   which one, defaulting to the current cycle from section 4.6.
4. `plan_activities` gains `cycle_id`. Re-apply then regenerates only that
   cycle's rows, and a report can total one cycle.

### 5.4 Worked examples

```
Potato, block B-14, Bashayer (EG-DELTA)

  window     potato / EG / EG-DELTA / winter   start 10-01, 168 days
  block_crop planted 2026-10-03, effective_to 2027-03-20
  cycle      one row: 2026-10-03 -> 2027-03-20, season_year 2026
  plan       farm Bashayer, potato-eg-delta-winter, 2026   <- one row
  apply      block_start_date = 2026-10-03, read from the cycle

Coffee, block C-07, Brazil (BR-SULMINAS)

  window     coffee / BR / BR-SULMINAS / biennial   start 09-01, 730 days
  block_crop planted 2019, effective_to NULL
  cycles     2024: 2024-09-01 -> 2026-08-31   harvest 2026
             2025: 2025-09-01 -> 2027-08-31   harvest 2027
                   ^ these two overlap for 12 months, on purpose
  plan       two rows, season_year 2024 and 2025
  apply      the user picks a cycle; each gets its own activities
  current    on 2026-03-15 the current cycle is 2024, ending sooner
```

---

## 6. The growing degree day total

Today `weather_derived_daily.gdd_cumulative_base10_season` is one number per
farm per day, and `weather/derivations.py:141` sums `gdd_base10` from 1 January.
A farm running potato, wheat, and mango at once gets one number for three crops
with three different starts.

### The change

Drop the stored column. Compute the total per cycle when it is read.

```sql
SELECT COALESCE(SUM(wdd.gdd_base10), 0)
FROM weather_derived_daily wdd
WHERE wdd.farm_id = :farm
  AND wdd.date >= :cycle_start
  AND wdd.date <  LEAST(CURRENT_DATE + 1, COALESCE(:cycle_end, CURRENT_DATE + 1))
```

`gdd_base10` and `gdd_base15` stay exactly as they are. Only the running sum
moves.

### The condition source keeps its name

`shared/conditions/context.py:206` exposes `derived_today` as a dictionary of
that row's columns, and `gdd_cumulative_base10_season` is one of the keys the
docstring names. The class docstring at `context.py:224` says removing a field
is a breaking change for any persisted rule that references it.

So the key name does not change. The context builder computes the per-cycle
total and puts it into `derived_today` under the same key. Persisted rules keep
working. What changes is the number they see.

### This changes live behaviour

Trees that fire today may stop. Trees that do not fire may start. This is not a
side effect to discover in production. Section 11, prompt 5, makes it a
measured, flagged change.

---

## 7. Migration of existing data

The migration opens one `block_crop_cycles` row per `block_crops` row.

```
before
  block_crops
    season_label   '2026-summer'
    effective_from 2026-04-01
    effective_to   2026-09-30

after
  block_crops                    season_label DROPPED
  block_crop_cycles
    name                 '2026-summer'   copied from season_label
    start_date           2026-04-01      from effective_from
    end_date             2026-09-30      from effective_to
    planting_date        untouched, stays on block_crops
    season_definition_id NULL            no window matched
    season_year          2026            from start_date
    source               'manual'
    status               derived from block_crops.status and end_date
```

No label is parsed. `Y3` is tree age and `2025-2026` names no season type, so
text matching would write wrong start dates into the growing degree day count.
A wrong date is worse than a null.

`vegetation_plans.season_label` is dropped and `season_definition_id` is left
null on every existing row. A screen lets a user attach a window later.

### Before writing the migration

Run this read-only count on production and record the result in the pull request
body.

```sql
SELECT season_label, COUNT(*) FROM block_crops
WHERE deleted_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
```

Three tidy values means the copy is enough. Forty values means a mapping screen
is worth building before the drop.

---

## 8. Seed data

Written as a `public` seed migration. `source` is filled on every row.

| crop_path | country | zone | season_type | cycle_kind | start | days |
| --- | --- | --- | --- | --- | --- | --- |
| potato | EG | EG-DELTA | winter | annual | 10-01 | 120 |
| potato | EG | EG-DELTA | summer | annual | 01-15 | 110 |
| potato | EG | EG-DELTA | nili | annual | 08-01 | 100 |
| wheat | EG | null | winter | annual | 11-15 | 165 |
| mango | EG | null | bearing | perennial_bearing | 01-15 | 320 |
| dates | EG | null | bearing | perennial_bearing | 02-01 | 270 |
| coffee | BR | BR-SULMINAS | biennial | perennial_multi_year | 09-01 | 730 |

The table is a starting shape, not the final numbers. The implementer confirms
each row against the FAO crop calendar for that country and records the source
per row. Mango and coffee get `alternate_bearing = true`.

Agro-zones to seed, at minimum: `EG-DELTA`, `EG-MIDDLE`, `EG-UPPER`,
`EG-NEWLANDS`, `EG-NORTHCOAST`, and `BR-SULMINAS`.

---

## 9. Traps

Each of these has bitten this codebase before.

**Never a foreign key from a tenant schema into `public`.**
`block_crop_cycles.season_definition_id` and `farms.agro_zone_code` are logical
references. `block_crops.crop_id` at `farms/models.py:492` is the pattern to
copy.

**A new tenant table must join the purge manifest or continuous integration
fails.** Register `block_crop_cycles` in `backend/app/shared/purge/registry.py`
next to `OwnedTable("block_crops", owner_column="block_id", order=20)` at line
196. Cycles are children of `block_crops`, so check the order direction in that
file and make sure cycles are removed first.

**Nulls in a unique index do not collide.** In PostgreSQL two rows with
`season_definition_id IS NULL` both pass a plain unique index. The new
`uq_vegetation_plans_farm_season_active` needs `NULLS NOT DISTINCT`, which needs
PostgreSQL 15 or later. Check the server version first. If it is older, use a
sentinel UUID instead of null, and write down which one.

**The decision tree condition list is pinned by a parity test.** Read that test
before touching the condition picker. This has caused rework before.

**Migration heads move, and a stale worktree lies.** As of 2026-09-09 on
`origin/main` the heads are `public/0084_usage_caggs_realtime.py` and
`tenant/0091_decision_tree_block_verdicts.py`. A local branch may show much
older numbers. Run `git ls-tree origin/main` before picking a number.

**Check the base branch before branching.** Roadmap edits go on
`docs/roadmap-prompt-10`, not on a feature branch.

**A test's own `commit()` unscopes the next read.** Integration tests for the
new tenant table will hit this.

**Run `pytest tests/unit` as well as the integration suite.** The apply resolver
is pure and unit-tested, and prompt 4 changes it.

---

## 10. Not in this release

**Growing degree day stages in apply.** Stages with
`mode = gdd_from_planting` are skipped at `apply.py:52` because a degree day
target has no calendar date. A cycle gives the correct starting point for the
count, but scheduling a future activity still needs a weather forecast. This
stays open.

**Yield attribution across coffee cycles.** The nodes formed in year one of a
cycle carry the crop harvested in year two. Nothing in this design links a yield
figure back to the vegetative cycle that produced it.

**Decision trees running once per open cycle.** Decision 8 chose one derived
current cycle. Advice about next year's node formation cannot fire during this
year's fruiting. Revisit if coffee tenants ask for it.

**Tenant-authored windows.** Decision 6 made the knowledge base platform-owned.
The `tenant_id` pattern from `signals/models.py:84` is the way in if this is
reopened.

**A mapping screen for legacy `season_label` values.** Section 7 leaves every
migrated cycle with a null window. Attaching them is manual for now.

---

## 11. Implementation prompts

Six prompts. Each is written for a session with no memory of this discussion.
Run them in order. Prompts 2 and 3 can run in parallel after prompt 1 merges.

---

### Prompt 1 — Schema, catalogs, and migration

> Read `docs/proposals/season-as-an-entity.md` sections 4, 7, and 9 first.
>
> Build the schema for the season entity. No API and no user interface in this
> prompt.
>
> 1. Before writing any migration, run
>    `git ls-tree --name-only origin/main backend/migrations/public/versions/`
>    and the same for `tenant`, and pick the next numbers from what you see.
>    Do not trust the local worktree listing.
> 2. Add `public.agro_zones` and `public.season_definitions` exactly as
>    section 4.1 and 4.2 specify, including every check constraint and the
>    partial unique indexes.
> 3. Add ORM models next to the existing public catalogs. `Crop` at
>    `backend/app/modules/farms/models.py:52` is the pattern for a curated
>    public catalog.
> 4. Add tenant table `block_crop_cycles` exactly as section 4.3 specifies.
>    Overlapping rows on one `block_crop_id` must be allowed.
> 5. Add `farms.agro_zone_code TEXT NULL` in the tenant schema. It is a logical
>    reference to `public.agro_zones.code`, never a database foreign key.
> 6. Register `block_crop_cycles` in `backend/app/shared/purge/registry.py`.
>    `OwnedTable("block_crops", owner_column="block_id", order=20)` at line 196
>    is the neighbour. Cycles are children of `block_crops`. Read how `order`
>    is used in that file and make sure cycles are deleted first. Continuous
>    integration fails if a tenant table is missing from the manifest.
> 7. Write the data migration from section 7. One cycle row per `block_crops`
>    row. Copy `season_label` into `name`. Take `start_date` from
>    `effective_from` and `end_date` from `effective_to`. Leave
>    `season_definition_id` null. Do not parse the label.
> 8. Drop `block_crops.season_label` in the same migration.
> 9. Add a resolver function for section 4.5 and one for section 4.6. Put them
>    in a new pure module so they can be unit-tested without a database. Reuse
>    `app.shared.crop_taxonomy.path_matches` for the crop path walk. Do not
>    write a second path matcher.
>
> Tests: unit tests for both resolvers, covering a coffee block with two
> overlapping open cycles, a block whose window has no zone match, and a block
> with no window at all. Integration tests for the migration on a tenant with
> mixed `season_label` formats, including `Y3`.
>
> Run `pytest tests/unit` as well as the integration suite. A test that calls
> `commit()` unscopes the next read in this codebase, so check the search path
> if a query returns an empty list with no error.
>
> Before you start, run the read-only count in section 7 against production if
> you have access, and put the result in the pull request body. If you do not
> have access, say so in the pull request body.

---

### Prompt 2 — Seed the knowledge base

> Read `docs/proposals/season-as-an-entity.md` sections 2 and 8 first. Prompt 1
> must be merged.
>
> Write a `public` seed migration for `agro_zones` and `season_definitions`.
>
> 1. Seed the agro-zones listed at the end of section 8, with Arabic and English
>    names for each.
> 2. Seed one `season_definitions` row per line of the section 8 table. The
>    numbers in that table are a starting shape, not confirmed values.
> 3. Confirm each row against the FAO crop calendar for that country before you
>    write it. Put the source in the row's `source` column, for example
>    `FAO crop calendar 2024` or `Camargo and Camargo 2001`.
> 4. Set `alternate_bearing = true` for mango and coffee.
> 5. Set `status = 'published'` only on rows you confirmed against a source.
>    Leave the rest `draft`.
> 6. Coffee is `perennial_multi_year` with `typical_duration_days = 730`. Its
>    cycles overlap by 12 months. Do not shorten it to a single year.
>
> Write the migration so it is safe to run more than once, keyed on `code`.
>
> Test: one integration test that loads the seed and asserts the resolver from
> prompt 1 picks the Delta winter potato window for a farm with
> `country_code = 'EG'` and `agro_zone_code = 'EG-DELTA'`.

---

### Prompt 3 — Cycle creation and the rollover job

> Read `docs/proposals/season-as-an-entity.md` sections 4.3 and 4.5. Prompts 1
> and 2 must be merged.
>
> 1. When a crop is assigned to a block, open one `block_crop_cycles` row in the
>    same transaction. Resolve the window with the prompt 1 resolver. Take
>    `start_date` from `block_crops.planting_date` when it is set, otherwise
>    from `effective_from`. Take `end_date` from
>    `start_date + typical_duration_days` when a window matched, otherwise leave
>    it null. Set `source = 'crop_assignment'`.
> 2. Let the user edit the dates in the same dialog before saving.
> 3. Add a nightly Celery task that opens the next cycle for perennial crops. For
>    each active `block_crops` row whose crop is perennial, resolve the window.
>    If today matches `rollover_month_day`, or `start_month_day` when that is
>    null, insert the next cycle with `source = 'rollover'`.
> 4. The unique index on
>    `(block_crop_id, season_year, season_definition_id)` is the duplicate
>    guard. The task must handle the conflict, not assume it cannot happen.
> 5. A coffee block must end up with two open cycles overlapping by 12 months.
>    This is correct, not a bug to prevent.
> 6. Add read and write endpoints for cycles, plus a screen listing every cycle
>    on a block, so a user can open, edit, and close one by hand.
>
> Note on the Celery task: a loop error in this codebase names the block it
> failed on, not the block that caused it. Wrap each tenant in a savepoint so
> one bad row does not roll back the sweep.
>
> Tests: an annual crop gets exactly one cycle at assignment. A mango block gets
> a second cycle after a simulated rollover date. A coffee block gets two
> overlapping open cycles. Running the task twice on the same day inserts
> nothing the second time.

---

### Prompt 4 — Rewire Plan Template and Apply

> Read `docs/proposals/season-as-an-entity.md` section 5. Prompts 1 to 3 must be
> merged.
>
> 1. Rename `plan_templates.region` to `agro_zone_code` and validate it against
>    `public.agro_zones.code`. Update the schemas at
>    `backend/app/modules/plan_templates/schemas.py:59` and `:112`.
> 2. Add `plan_templates.season_definition_id UUID NULL` with a foreign key to
>    `public.season_definitions.id`, on delete set null. Both tables are in
>    `public`, so a real foreign key is correct here.
> 3. In `vegetation_plans`, drop `season_label` and add
>    `season_definition_id UUID NULL`. Move
>    `uq_vegetation_plans_farm_season_active` to
>    `(farm_id, season_definition_id, season_year)`. Read the null trap in
>    section 9 before you write the index. Check the PostgreSQL server version.
> 4. Add `plan_activities.cycle_id UUID NULL`, foreign key to
>    `block_crop_cycles.id`, on delete set null. Set it on every row apply
>    creates.
> 5. In `plan_templates/service.py:221`, stop passing `blk.start_date`. Read the
>    cycle's `start_date` instead. Keep `start_date` on the request schema for
>    one release as an optional override, and log when it is used.
> 6. Fix `plan_templates/apply.py:49`. `date(season_year, month, day)` puts the
>    January end of a `12-15` to `01-20` window 11 months before its start.
>    Resolve the day-of-year against the cycle's `start_date` and `end_date`
>    instead, so a date falling before the cycle start rolls to the next year.
> 7. Change `list_current_block_crops` in
>    `plan_templates/repository.py:347` to select by cycle rather than by
>    `is_current`. When a block has more than one open cycle, default to the
>    current cycle from section 4.6 and let the caller pass a cycle id.
> 8. Template discovery matches the block cycle's `season_definition_id` first,
>    then falls back to `crop_path`.
>
> Do not change `apply.py`'s handling of `gdd_from_planting` stages. They stay
> skipped. That is section 10.
>
> Tests: `apply.py` is pure and already has unit tests, so extend those first.
> Add a regression test for the year-boundary bug in item 6, using a window from
> 15 December to 20 January. Add an integration test that applies the same
> template twice and asserts the dates are identical both times.

---

### Prompt 5 — Growing degree day total per cycle

> Read `docs/proposals/season-as-an-entity.md` section 6 and the parity-test
> trap in section 9. Prompts 1 to 3 must be merged. This prompt changes what
> live decision trees do, so read all of it before writing code.
>
> 1. Find the parity test that pins the decision tree condition source list.
>    Read it before you touch anything.
> 2. Replace `cumulative_gdd_base10_for_season` at
>    `backend/app/modules/weather/derivations.py:141`. It sums from 1 January
>    today. It must sum from the cycle's `start_date` to the earlier of today
>    and the cycle's `end_date`. The query is in section 6.
> 3. Keep the condition key name `gdd_cumulative_base10_season` unchanged. The
>    docstring at `shared/conditions/context.py:224` says removing a field
>    breaks every persisted rule that references it. Compute the per-cycle total
>    in the context builder and put it into `derived_today` under the same key.
> 4. `ConditionContext` already carries `block_id`, so the builder can find the
>    block's current cycle with the section 4.6 query.
> 5. Drop `weather_derived_daily.gdd_cumulative_base10_season` only after items
>    2 and 3 are working. Leave `gdd_base10` and `gdd_base15` alone.
> 6. Put the new behaviour behind a feature flag, default off.
> 7. Before turning the flag on, run every published decision tree against
>    production data with the flag off and then on, and record how many blocks
>    change verdict. Put both counts in the pull request body. Do not turn the
>    flag on in the same pull request.
> 8. Update `docs/data_model.md:852`, which still says "reset by event".
>
> Tests: a block whose cycle runs October to May gets a total that does not
> reset on 1 January. A coffee block with two open cycles gets the total for the
> nearer-ending cycle. A block with no cycle gets null, and a rule reading it
> fails closed rather than treating null as zero.

---

### Prompt 6 — Screens and translations

> Read `docs/proposals/season-as-an-entity.md` sections 4.6 and 5. Prompts 1 to
> 5 must be merged.
>
> 1. Add a platform screen for `season_definitions` and `agro_zones`, in the
>    same place as the other curated catalogs. Read-only to tenants.
> 2. Add a farm setting for `agro_zone_code`, a dropdown filtered by the farm's
>    `country_code`.
> 3. On the block page, show the current cycle's name and dates. When a block
>    has more than one open cycle, list them all and mark which one is current.
> 4. In the crop assignment dialog, show the cycle dates the window supplied and
>    let the user change them before saving.
> 5. Remove the free-text season box at
>    `frontend/src/modules/farms/components/CropAssignmentPanel.tsx:80`.
> 6. In `ApplyTemplateDialog.tsx`, replace the typed season label with a season
>    picker, and replace the typed block start date with the cycle's date shown
>    read-only.
> 7. Add English and Arabic strings for every new label. Every catalog row has
>    `name_en` and `name_ar`, so show the right one for the active language.
>
> Arabic notes for this project: no operating system font stack carries Arabic
> on Android, so do not rely on a Latin-only default. Text inside an inline
> image flips under right-to-left, so set `dir="ltr"` on any container holding
> a date range drawn as an image.
>
> Do not run a formatter across a broad glob. Format only the files you changed.
