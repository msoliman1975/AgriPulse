# Farm Health View — specification for implementation

Status: pull requests 1, 2 and 3 are written on branches and not pushed.
Pull requests 4 to 8 are not started. This document is the single input for
the session that continues it.

Written on 2026-09-07, each off `origin/main`, in the worktree
`C:/Users/mosoliman/projects/ma-fhvspec`:

| Branch | Commit | What |
| --- | --- | --- |
| `feat/verdict-last-run-id` | `dced9af2` | PR 1 |
| `feat/verdict-history-read` | `a31251ef` | PR 2 |
| `feat/farm-health-view-shell` | `935a1414` | PR 3 |

Prototype: https://claude.ai/code/artifact/2d6cac8c-6c5c-4dd6-997c-3ec00b46c9e6

The prototype is a single HTML page with invented data. It is the reference for
layout and behaviour. Every rule in this document was decided with Mohamed on
2026-09-07, one question at a time. Where the prototype and this document
disagree, this document wins.

## 1. What the screen is

One sentence: a farm map where each grid cell is coloured by what one decision
tree said about it, on a date the user chooses, with a replay over a date range.

The screen answers three questions:

1. What does this tree say about this farm right now?
2. Which parts of a block does it say it about?
3. Why does it say it, with the numbers it read?

The screen is read-only. It writes nothing.

Name: `Farm Health View`. Route: `/farm-health/:farmId`. Navigation label:
`Farm Health View`.

Note: this is a new map. It is not the Farm Console map and not the Farm
Management map. See section 9.

## 2. What already exists

I checked these against `origin/main` on 2026-09-07. The primary checkout is
404 commits behind `origin/main`, so read them with `git show origin/main:<path>`
rather than opening the working copy.

### 2.1 The verdict store

Tenant table `decision_tree_block_verdicts`, tenant migration
`backend/migrations/tenant/versions/0091_decision_tree_block_verdicts.py`.
Model: `DecisionTreeBlockVerdict` in
`backend/app/modules/recommendations/models.py`.

Rows are intervals. Reading a past date is one predicate:

```sql
valid_from <= :at AND (valid_to IS NULL OR valid_to > :at)
```

Columns the screen uses: `farm_id`, `block_id`, `cell_id`, `scope`, `tree_id`,
`tree_code`, `tree_version`, `leaf_node_id`, `kind`, `status_code`, `severity`,
`text_en`, `text_ar`, `valid_from`, `valid_to`, `last_evaluated_at`.

`cell_id` is NULL for a block verdict and set for one grid cell.

A missing row means the tree did not run there. That is not the same as the
status code `na`. Section 5.6 says how the map draws the difference.

### 2.2 The status list

`backend/app/modules/recommendations/status_codes.py`. Five codes, a closed
list, with rank and colour:

| Code | Rank | Colour | Label |
| --- | --- | --- | --- |
| `na` | 0 | `#9AA0A6` | Not assessed |
| `very_good` | 1 | `#1B873F` | Very good |
| `good` | 2 | `#6FBF4B` | Good |
| `issue` | 3 | `#E8A33D` | Issue |
| `alert` | 4 | `#D64545` | Alert |

Do not hardcode this list in the frontend. Read it from the endpoint in
section 2.3.

### 2.3 The read endpoints

All three are on `origin/main` in
`backend/app/modules/recommendations/router.py`.

| Method and path | What it returns |
| --- | --- |
| `GET /verdict-statuses` | The five codes with colour and both labels. |
| `GET /blocks/{block_id}/verdicts?farm_id=&at=` | One block's verdicts and its worst status. |
| `GET /farms/{farm_id}/verdicts?at=` | Every block of one farm with its verdicts. |

`at` is the replay parameter. Omit it for the current answers.

`GET /farms/{farm_id}/verdicts` is what the map reads. Its response is
`FarmVerdictsResponse` in `backend/app/modules/recommendations/schemas.py`.
Each `VerdictResponse` carries `cell_id`, `cell_row` and `cell_col`, so a cell
verdict arrives with its zone label already resolved.

Capability: `recommendation.read`, with `farm_id_param="farm_id"` on the two
farm-scoped routes. `/verdict-statuses` uses `any_farm=True`. Keep both. A
`requires_capability` with no `farm_id_param` denies every farm-scoped user.

### 2.4 The evaluation trace

`GET /decision-tree-traces/{trace_id}` returns one trace with `node_path` and
`resolved_values`. That is the data behind the reasoning panel in section 5.5.

`GET /decision-tree-traces` lists traces and accepts `run_id`, `block_id`,
`farm_id`, `tree_code` and a status filter. The list deliberately omits
`node_path` and `resolved_values`, because 200 full walks is several megabytes
of JSONB.

Warning: both trace endpoints are gated on `decision_tree.read`. I checked
`role_capabilities.yaml` on 2026-09-07: five roles hold `recommendation.read`
and not that one — FarmManager, Agronomist, FieldOperator, Scout and Viewer.
Those are the readers this screen is for, so pointing the reasoning panel at
these endpoints returns 403 for all of them. PR 1 adds a second door instead.

### 2.5 The feature flag

`health_definition_enabled` in `backend/app/core/settings.py`, default `False`.

Caution: the flag controls the block health rule, not the verdict table. Do not
turn it on to build this screen, and do not make this screen depend on it.
Check with the team what the flag reads as in production before you assume
either state.

## 3. The gaps to build

These are the parts that do not exist yet. Each one is verified absent, not
assumed.

### 3.1 A verdict row cannot reach its trace — closed by PR 1

`VerdictResponse` ended at `alert_id` and `recommendation_id`. It carried no
`run_id`, no `last_run_id` and no trace id, although the table has had both
columns since migration 0091. The column was simply missing from the SELECT.

PR 1 adds `last_run_id` to the read and to the response. `confirm()` re-points
it on every sweep that reaches the same leaf, so it names the newest walk
rather than the one that opened the interval.

PR 1 also adds the second door the capability gap in section 2.4 forces:

    GET /blocks/{block_id}/verdicts/{verdict_id}/reasoning?farm_id=

Gated on `recommendation.read` with `farm_id_param`, the way the verdict reads
are. It returns the verdict plus `node_path`, `resolved_values` and
`param_overrides` from the trace of `last_run_id`.

The join to the trace is a LEFT JOIN. Retention prunes eval runs and their
traces, so a verdict that is still the current answer can outlive its walk.
That case returns `reasoning_available: false` with the verdict intact, not a
404, because "the reasoning is no longer kept" and "no such verdict" are
different sentences.

### 3.2 There is no cell geometry in the verdict read

The response gives `cell_row` and `cell_col` but no polygon. The map needs the
cell outlines to paint them.

Two options. Pick one before writing code:

1. Read cells from the existing grid endpoint the Farm Console uses, and join
   on `cell_id` in the frontend. Adds one request. No backend change.
2. Add a `geometry` field to the cell verdicts. Larger payload on every replay
   frame, and the geometry does not change between frames.

Recommendation: option 1. The geometry is stable across the whole replay, so
fetching it once per block beats sending it 30 to 365 times.

### 3.3 There is no range read — closed by PR 2

Every endpoint took a single `at`. A 365-day replay would have been 365
requests.

PR 2 adds `GET /farms/{farm_id}/verdict-history?from=&to=&tree_code=`,
returning the interval rows that overlap the window, once. The frontend then
builds each frame in memory with the same predicate as section 2.1.

`from` and `to` are query aliases because `from` is a Python keyword. A window
whose end is not after its start returns 422 rather than an empty list,
because an empty list reads the same as a farm with no history. The row guard
is 50,000 and the response reports `truncated` rather than returning a short
list the caller cannot tell from a complete one.

Size: one row per block or cell per tree per change, not per day. A block that
holds one verdict for a month is one row.

Caution: measure this before shipping the year range. A farm with 72 blocks,
121 cells each and 13 trees could produce a large result. If it does, cap the
response and return the block-level rollup for ranges over 90 days.

### 3.4 There is no route, page or navigation entry

New frontend module `frontend/src/modules/farmHealth/`. Follow
`frontend/src/modules/timeline/` for structure. See section 9.1 for the trap
that module holds.

## 4. Screen layout

Three regions inside a viewport-height page. The page never scrolls; each
region scrolls inside itself.

```
+--------------------------------------------------------------+
| Header: title, tree picker, range picker, dates, current date |
+--------------------------------------------------------------+
| Transport: back, play, forward, Latest, scrubber, speed       |
+---------------+----------------------------------------------+
|               | Map                                          |
| Block list    |   zoomed to the selected block               |
| (left, 308px) |   other blocks greyed                        |
|               +----------------------------------------------+
|               | Block summary                                |
|               | Area chips                                   |
|               | One area: reason, action, reasoning panel    |
+---------------+----------------------------------------------+
```

Use the app's own components where they exist: `PageHeader`, `Pill`, `Card`,
`Button`. Use the `ap.*` colour tokens from `frontend/tailwind.config.ts`. Do
not add a second colour scale.

## 5. Behaviour

### 5.1 One tree at a time

A tree picker holds the trees that apply to this farm. The map shows that one
tree's verdicts. There is no all-tree rollup on this screen.

A block-scoped tree paints the whole block polygon in one colour. A cell-scoped
tree paints the block's cells. Read `scope` from the verdict row, not from the
tree definition, so a tree that changed scope still draws its old rows
correctly.

### 5.2 The left list

One row per block, sorted worst verdict first. Each row shows the block code,
the crop, a bar of cell counts by status, and the block's worst status as a
`Pill`.

A block whose tree did not run shows a hatched bar and the text
`Tree did not run`. It sorts last.

Clicking a row selects the block and frames it on the map.

### 5.3 Areas, not cells

A block of 121 cells must not produce 121 rows of detail.

Group the block's cells into areas. An area is a set of cells that touch on an
edge and hold the same verdict. Use a four-neighbour flood fill.

Name each area by where its centre sits in the block grid: `North-west`,
`North`, `North-east`, `West`, `Centre`, `East`, `South-west`, `South`,
`South-east`. An area holding 45 percent or more of the block is named
`Most of the block, toward the <direction>`. An area holding every cell is
named `The whole block`.

Merge areas of one or two cells, per leaf, into one entry named
`Scattered · N spots`. Without this rule a scattered verdict makes 40 entries.

Sort areas by status rank, then by cell count, both descending.

One area is selected at a time. Its chip is pressed and its cells are outlined
on the map. On load, and whenever the block or tree changes, select the first
area in that sort order, which is the worst and largest.

When the date moves, keep the selected area if an area with the same leaf and
name still exists. Otherwise select the first one again.

### 5.4 The reason, as text

Above the reasoning panel, write two short paragraphs.

1. Why this area has this colour, with the numbers. Build the sentence from the
   trace, not from a hardcoded string. Give the index value as a range over the
   area's cells, for example `CWSI reads 0.47 to 0.85 across this area, above
   the medium-tree bound of 0.30.`
2. What to do, which is the leaf's `text_en` or `text_ar`.

Both paragraphs run the full width of the panel. Do not constrain them to a
narrow measure. Mohamed asked for this on 2026-09-07: the narrow column used
height that the reasoning panel needs.

### 5.5 The reasoning, expandable in place

A link reads `Show how this was decided`. It expands a section inside the same
card. It is not a modal. Mohamed asked for this on 2026-09-07.

The section lists the steps the tree took, root to leaf. One step shows:

- the step number,
- the question, which is the node's `label_en`,
- what was read: the input path and its value, as a range across the area,
- what it was tested against: the operator and the threshold, with the
  parameter name,
- the result: `yes` or `no`.

The leaf closes the list, with its `leaf_node_id`, `kind` and `status_code`.

Source: `node_path` and `resolved_values` from
`GET /blocks/{block_id}/verdicts/{verdict_id}/reasoning?farm_id=`, added in
PR 1. Do not call `/decision-tree-traces/{trace_id}` from this screen: it is
gated on `decision_tree.read`, which five of the eight roles do not hold.

When `reasoning_available` is false the run has been pruned by retention. Say
that the reasoning is no longer kept. Do not render an empty step list, which
reads as "the tree did nothing".

### 5.6 More than one route to the same verdict

A leaf can be reached by more than one path. The cells of one area can
therefore hold the same verdict for different reasons.

When that happens:

- Put a badge next to the reason that reads `N routes reached this verdict`.
- Say in the reason sentence how many cells came by each route.
- In the reasoning panel, show the steps every route agrees on once, under the
  heading `Shared steps`. Then show one block per route, each with its own cell
  count and its own name, starting at the step where the routes split.

Compare routes step by step from the root. A step is shared when the node id
and the result are the same on every route.

Group an area's cells by the leaf path recorded in their trace, not by the leaf
alone.

### 5.7 The two kinds of nothing

Two states look similar and mean different things. Draw them differently.

| State | Meaning | How to draw |
| --- | --- | --- |
| No verdict row | The tree did not run here. | Diagonal hatch, grey. |
| `status_code = na` | The tree ran and could not assess. | Flat grey, `#9AA0A6`. |

Count both in the legend, on separate lines. The detail panel names which one
it is and why, for example `Tree size is not set on this block's crop
assignment, so there is no band to compare against.`

### 5.8 Dates and replay

The date axis is every calendar day in the range. A day with no evaluation
carries the previous verdict forward. Do not skip days.

Mohamed decided on 2026-09-07 that the screen shows the current state and does
not label it as carried forward. Do not add a line under the date saying when
the verdict was created.

Mark the evaluation days on the scrubber track with a taller tick, so the user
can see where new readings arrive.

Range control. Default is the last 30 days. The other options are the last 90
days, the last year, and custom dates.

- Custom dates use two date inputs, from and to.
- Show the window's dates at all times, not only in custom mode. Editing either
  date switches the range to custom.
- Clamp the end date to today. If the two dates are reversed, swap them.
- Cap a custom range at 1830 days.

Changing the range jumps to the newest day in the new window.

A `Latest` button returns to the newest day. Disable it when already there.

Replay. Play steps one calendar day per frame. Everything follows the date: the
map, the left list, the areas, and the open reasoning panel.

Set the frame interval so one pass takes about 24 seconds at 1x, whatever the
range: `interval = max(55, 24000 / (days - 1) / speed)`. At 30 days that is
828 ms. At 365 days it is 66 ms. A fixed interval makes a year unwatchable at
about 5.5 minutes.

Keyboard: left and right arrows step one day, space plays and pauses.

### 5.9 The map

Colour the cells from the status colour of their verdict.

Smoothing. Draw cells with no gap and no stroke, then put the cell layer behind
an SVG filter: a Gaussian blur of about 0.4 of a cell width, then a
`feColorMatrix` that sharpens the alpha. Colours then meet in curves instead of
a staircase. Mohamed asked for this on 2026-09-07, for looks only. It changes
no value and no click target.

Caution: the selection outline must sit in its own layer, outside the filter,
or it blurs as well. Draw the outline as the edges of the area that have no
neighbour in the area, so it traces the shape and shows no internal grid lines.

Zoom and focus:

- The mouse wheel zooms about the pointer.
- Plus and minus buttons zoom about the centre.
- Dragging pans. A drag of more than 4 pixels must not also count as a click on
  a cell.
- `Fit block` frames the selected block.
- `Fit selected area` frames the selected area.
- `Whole farm` frames every block and stops greying the unselected ones.
- Show the current zoom level.
- Keyboard: plus and minus zoom, `0` fits the block, `F` fits the farm.

Scale limits in the prototype are 0.7x to 14x.

Selecting a block frames it. Clicking a cell in another block moves to that
block, frames it, and selects the area that cell belongs to.

## 6. What the screen does not do

- It does not write. No dispatch, no acknowledge, no assign.
- It does not show more than one tree at a time.
- It does not draw a selection shape. An area is a group the tree produced.
- It does not replace the Farm Console or the Timeline.

## 7. Decisions already made

Each line is a decision Mohamed made on 2026-09-07. Do not re-open them without
asking him.

1. One tree at a time, picked from a list. No rollup mode.
2. A block-scoped tree fills the block polygon.
3. Layout: block list on the left, map upper right, details lower right.
4. The map zooms to the selected block and greys the others.
5. Cells are grouped by geographic area, not by leaf.
6. The full path is shown, with value ranges across the area.
7. The date axis is every calendar day, carrying values forward.
8. Everything follows the date during replay.
9. The two kinds of nothing get two marks, both counted.
10. No cell names in the detail list. Map hover only.
11. No carried-forward text under the date.
12. The block summary sits above, and everything below it is one selected area.
13. The reasoning expands in place. No modal.
14. Default range is 30 days, with 90 days, a year, and custom dates.

## 8. Open questions

1. ~~Which trees appear in the picker?~~ Answered in PR 3: only trees with a
   verdict on this farm. It costs no extra query — the farm read already
   carries `tree_code` on every verdict. A tree with no verdict here would
   paint an entirely blank screen, and a reader cannot tell that from a
   broken one.
2. Should the screen be farm-scoped only, or should there be a tenant-level
   entry that asks for a farm first?
3. Does a Scout see this screen? A Scout holds `recommendation.read` on their
   farms, so the endpoints allow it today.
4. Arabic. Every string has an Arabic side in the data. The area names in
   section 5.3 are generated, so they need Arabic templates.
5. What does `health_definition_enabled` read as in production right now? It
   is `False` by default in `settings.py`; I did not read the running value.

## 8b. What production holds today

Measured on 2026-09-07 and 2026-09-08 against the production database, over
SSH.

**The verdict table is empty, and that is correct.** The image carrying the
verdict code, `0af9a38`, rolled out at 2026-09-07T22:24Z. The last
recommendations sweep ran at 14:21Z the same day, eight hours earlier, on the
previous image `a60b9e8`. So no sweep has yet run with the write in it.
`pg_stat_user_tables` agrees: `n_tup_ins` is 0, meaning not one row has ever
been attempted, rather than rows written and removed.

The first sweep to produce verdicts is the one at about 14:21Z on 2026-09-08.
Check it before concluding anything from an empty screen:

```sql
SET search_path TO "tenant_019eafdc242c7320948e13490efc67dd", public;
SELECT count(*) FROM decision_tree_block_verdicts;
```

For scale, that tenant's sweep walks 72 blocks and 1728 trees and writes
about 4,750 traces per run, of which roughly 1,730 reach a leaf. Expect a
verdict row per leaf reached, so on the order of 1,700 rows on the first
sweep and far fewer on later ones, because a verdict that has not changed is
confirmed rather than re-inserted.

The write itself is proven against the live schema. I ran the exact
`insert_new` statement from `VERDICT_SQL` on the production database inside a
transaction that rolled back: `INSERT 0 1`.

**The archived tenant has no verdict table, and that is also correct.**
`tenant_019ecf24bb59752f8b24762ceb5af639` is `agrosina-demo`, status
`archived`. Archived schemas do not take new migrations, so 0091 was never
applied there. The two active tenants, `agrosina` and `valley-farms`, both
have the table.

Note: I first read both of these as production defects and said so. Neither
is. What was true is that nothing in the sweep log could tell an empty write
from a sweep that had not run, which is why
`fix/sweep-log-verdicts-written` adds the counter.

## 9. Traps in this codebase

These have each cost a day before.

### 9.1 A full-bleed map route must be pinned

`frontend/src/shell/AppShell.tsx` line 19 pins the viewport only for paths
starting `/labs/map`. A new full-bleed map route that is not in that list grows
without limit. The Timeline map reached 15983 pixels tall inside a 950 pixel
viewport.

Add the new route to `viewportPinned`. `viewportPinned.test.ts` fails when a
full-bleed route is missing.

### 9.2 MapLibre checks that `bounds` exists, not that it is a number

Passing `bounds: undefined` to `addSource` throws, and takes `addLayer` with
it. Both errors go to the console only, so the page looks like a farm with no
imagery. Build the source with `rasterSourceSpec` in
`frontend/src/modules/timeline/lib/rasterSource.ts`, which spreads the key
instead of setting it.

### 9.3 A Card with a title does not make its child a flex container

A `<Card>` with a title wraps its children in a plain `div`. A child using
`flex-1 min-h-0 overflow-y-auto` has nothing to resolve against, so the panel
does not scroll and the page grows instead.

### 9.4 Tests that assert the layer below the bug pass anyway

The Timeline shipped four defects and all 46 tests passed. Each test asserted
props handed to a stubbed map, or a payload, instead of the rendered result.

Assert the rendered string. For this screen that means: the area name that
appears, the number in the legend, the colour class on the cell, the text of
the step rows.

Also run `pytest tests/unit`, not only the integration suite.

### 9.5 The i18n namespace must be registered in tests

`setupTestI18n` needs the new namespace. A missing namespace is why the
Integration Health page had no tests for a long time.

### 9.6 Reuse the cell label helper

`frontend/src/lib/cellLabel.ts` formats a cell as `R{row}·C{col}`. Use it. Do
not write a second format.

## 10. Implementation plan

Eight pull requests. Each one is small enough to review on its own, and each
one leaves `main` working. Nothing here is behind a feature flag: the screen
is a new route, so an unfinished route is reached by nobody.

### Before you start

1. Branch from `origin/main`, not from the working copy. The primary checkout
   was 404 commits behind on 2026-09-07.
2. Read existing code with `git show origin/main:<path>` for the same reason.
3. Run `pytest tests/unit` as well as the integration suite. A new field in
   the middle of a dataclass shifts every positional argument, and only the
   unit suite builds them that way. Put new dataclass fields last, with a
   default.
4. `backend-integration` in CI is `continue-on-error`. A green tick means the
   job ran. Read the summary line.

### PR 1 — Backend: let a verdict reach its walk — WRITTEN

Branch `feat/verdict-last-run-id`, commit `dced9af2`. Not pushed.

Problem: sections 2.4 and 3.1.

What it changed:

- `schemas.py` — `last_run_id` on `VerdictResponse`; new
  `VerdictReasoningResponse`.
- `repository.py` — `last_run_id` in the read; new `VERDICT_SQL.REASONING`
  and `get_verdict_reasoning`.
- `service.py` — `verdict_reasoning`, which sets `reasoning_available`.
- `router.py` — `GET /blocks/{block_id}/verdicts/{verdict_id}/reasoning`.
- `tests/integration/recommendations/test_verdict_reasoning.py` — four tests:
  the run id round trips through both verdict reads, the walk comes back in
  order with its values, a pruned run leaves the verdict readable, and a
  verdict id from another block returns 404.

Checked: `pytest tests/unit` passed 1735. ruff, black and mypy clean. The
reasoning SQL was run against the production schema inside a transaction that
rolled back, and planned as three index scans. The integration tests did not
run: Docker does not start on the development machine, so CI is the first
place they execute.

### PR 2 — Backend: one read for a date range — WRITTEN

Branch `feat/verdict-history-read`, commit `a31251ef`. Not pushed.

Checked: `pytest tests/unit` passed 1735. ruff, black and mypy clean. The
history SQL was run against the production schema inside a transaction that
rolled back, and planned as an index scan on `ix_dt_verdicts_tree_time`. Five
integration tests written, not run, for the same reason as PR 1.

Not measured on production data, because there is none. See section 8b.

Problem: section 3.3. A 365-day replay must not be 365 requests.

Changes:

- `backend/app/modules/recommendations/router.py` — add
  `GET /farms/{farm_id}/verdict-history?from=&to=&tree_code=`.
- `backend/app/modules/recommendations/repository.py` — add
  `list_verdict_history`, selecting rows where the interval overlaps the
  window: `valid_from < :to AND (valid_to IS NULL OR valid_to > :from)`.
- `backend/app/modules/recommendations/schemas.py` — add
  `FarmVerdictHistoryResponse`.

Capability: `recommendation.read` with `farm_id_param="farm_id"`. Copy the
existing farm verdict route exactly. A `requires_capability` with no
`farm_id_param` denies every farm-scoped user, and the denial is a silent 403
on a request that looks correct.

`tree_code` is a filter, not optional in practice: the screen shows one tree
at a time, and filtering server-side is what keeps the year range small.

Tests:

- Integration: a verdict that opened before the window and is still open
  appears once.
- Integration: a verdict that closed before the window does not appear.
- Integration: three changes inside the window return three rows, not one row
  per day.
- Integration: a farm-scoped user with the farm in scope gets 200. Without it,
  403.

Acceptance: measure the row count on a real farm before merging. Write the
number in the pull request body. If a 365-day window on the largest farm
returns more than about 50,000 rows, add the cap from section 3.3 in this same
pull request rather than later.

Risk: medium, because of size. Measure first.

### PR 3 — Frontend: route, shell and block list — WRITTEN

Branch `feat/farm-health-view-shell`, commit `935a1414`. Not pushed.

Checked: `tsc -b --force` clean, eslint clean, and the full frontend suite
passed 1522 tests in 174 files, 16 of them new. I removed the AppShell pin
and confirmed `viewportPinned.test.ts` fails, then restored it, so the guard
is proven rather than assumed.

Changes:

- New module `frontend/src/modules/farmHealth/`.
- `frontend/src/api/farmHealth.ts` — typed clients for the three read
  endpoints and the new history endpoint.
- `frontend/src/modules/farmHealth/pages/FarmHealthViewPage.tsx` — the page,
  current date only, no map yet.
- `frontend/src/modules/farmHealth/components/BlockList.tsx`.
- Route registration and the navigation entry.
- `frontend/src/shell/AppShell.tsx` — add `/farm-health` to `viewportPinned`.
- `frontend/src/i18n/locales/en/farmHealth.json` and the Arabic file.

Read the status list from `GET /verdict-statuses`. Do not hardcode the five
codes or their colours.

Tests:

- `viewportPinned.test.ts` already fails when a full-bleed route is missing.
  Confirm it fails before you add the route, then passes.
- Render the block list with two blocks and assert the rendered text: the
  block code, the status label, and the cell count. Assert strings, not props.
- Register the namespace in `setupTestI18n`, or every string renders as its
  key.

Acceptance: the route loads, the left list shows the farm's blocks sorted
worst first, and a block with no verdict row reads `Tree did not run`.

Risk: section 9.1. A full-bleed map route that is not pinned grows without
limit. The Timeline map reached 15983 pixels tall inside a 950 pixel viewport.

### PR 4 — Frontend: the map

Changes:

- `frontend/src/modules/farmHealth/components/HealthMap.tsx`.
- Cell geometry joined from the grid endpoint, per section 3.2 option 1.
- The smoothing filter from section 5.9.

Draw order: block polygons, then the cell layer behind the filter, then the
unfiltered selection layer, then the labels.

Tests:

- Given a block with 4 cells of known status, assert the fill colour on each
  cell element.
- Assert the selection outline path has no internal edges: an area of 4 cells
  in a square draws 8 edges, not 16.
- Assert a block with no verdict row uses the hatch pattern.

Acceptance: cells carry the status colour, colours meet in curves rather than
steps, and the selection outline stays sharp.

Risk: section 9.2. MapLibre checks that `bounds` exists, not that it holds a
number. Build any raster source with `rasterSourceSpec`.

### PR 5 — Frontend: areas and the block summary

Changes:

- `frontend/src/modules/farmHealth/lib/areas.ts` — the flood fill, the naming
  rules, the scattered merge, and the sort from section 5.3.
- `frontend/src/modules/farmHealth/components/BlockSummary.tsx`.
- `frontend/src/modules/farmHealth/components/AreaChips.tsx`.

`areas.ts` is pure. Test it directly with small grids.

Tests:

- A 3 by 3 grid with one status returns one area named `The whole block`.
- Two separate groups of the same status return two areas, not one.
- A group of two cells merges into the scattered entry. A group of three does
  not.
- An area covering 50 percent of the block is named `Most of the block, toward
  the <direction>`.
- Areas sort by status rank first, then by cell count.
- Render the summary and assert the counts as text.

Acceptance: a block of 121 cells produces a readable number of areas, and the
worst area is selected on load.

### PR 6 — Frontend: the reason and the reasoning panel

Depends on PR 1.

Changes:

- `frontend/src/modules/farmHealth/lib/reason.ts` — build the sentence from
  the trace values.
- `frontend/src/modules/farmHealth/components/AreaDetail.tsx`.
- `frontend/src/modules/farmHealth/components/Reasoning.tsx` — the expandable
  panel, the shared prefix, and the per-route blocks from section 5.6.

Group the area's cells by their leaf path, not by the leaf.

Tests:

- One route: the panel lists the steps in order and each step shows the input,
  the threshold and the result. Assert the rendered text of each row.
- Two routes: the shared steps appear once, each route block names its own
  cell count, and the badge reads `2 routes reached this verdict`.
- The reason sentence names the value range and the threshold.
- The panel is closed by default and opens in place. There is no dialog role
  in the tree.

Acceptance: from a colour on the map you can read why in one sentence, and see
the full walk in one click.

Risk: section 9.3. A `Card` with a title wraps its children in a plain `div`,
so `flex-1 min-h-0 overflow-y-auto` inside it does not scroll.

### PR 7 — Frontend: dates, range control and replay

Depends on PR 2.

Changes:

- `frontend/src/modules/farmHealth/lib/window.ts` — the window, the day list,
  and the frame lookup using the interval predicate from section 2.1.
- `frontend/src/modules/farmHealth/components/RangePicker.tsx`.
- `frontend/src/modules/farmHealth/components/Transport.tsx` — back, play,
  forward, `Latest`, the scrubber, the speed buttons.

Fetch the history once per range change, then build every frame in memory.
Do not request per day.

Tests:

- The default window is 30 days and ends today.
- A day with no evaluation shows the previous verdict.
- Changing the range jumps to the newest day.
- An end date after today clamps to today. Reversed dates swap.
- A custom range longer than 1830 days is capped.
- `frameMs` returns 828 at 30 days and 66 at 365 days.
- `Latest` is disabled on the newest day.

Acceptance: the three fixed ranges and a custom range all replay, and one pass
takes about 24 seconds at 1x in every range.

### PR 8 — Frontend: zoom and focus

Changes:

- `frontend/src/modules/farmHealth/lib/view.ts` — the view state, `fitBox`,
  `zoomAbout`, and the pointer handling from section 5.9.
- The map control cluster.

Tests:

- `fitBox` centres a box and clamps the scale to the 0.7 to 14 range.
- `zoomAbout` keeps the named point still.
- A pointer movement of more than 4 pixels sets the flag that suppresses the
  following click.

Acceptance: the wheel zooms about the pointer, dragging pans without changing
the selection, and each of the three fit buttons frames what it names.

### Order and parallel work

PR 1 and PR 2 are backend and independent of each other. PR 3 depends on
neither and can start at the same time. PR 4 and PR 5 follow PR 3. PR 6 needs
PR 1 and PR 5. PR 7 needs PR 2 and PR 3. PR 8 needs PR 4.

One reasonable split for two people: one takes PR 1, PR 2 and PR 7; the other
takes PR 3 through PR 6 and PR 8.

### Before the first deploy

1. Confirm what `health_definition_enabled` reads as in production. The screen
   must not depend on it either way.
2. Check the row count from PR 2 on the largest production farm.
3. Answer the open questions in section 8. Question 1 changes the tree picker,
   and question 4 changes every generated area name.

### How to verify it on the server

Do not judge the deploy from the browser alone. `app.agripulse.cloud/api/*`
returns the single page app, so a 200 there proves nothing. Read the running
image with `.spec.template...image` on the pod, not the ArgoCD revision, and
introspect `app.routes` inside the pod to confirm the new endpoints exist.

## 11. Related documents


- `docs/proposals/decision-tree-status-verdicts.md` — the four leaf kinds and
  the five status codes, and why a leaf that finds nothing wrong still writes
  a row.
- `frontend/src/modules/timeline/` — the closest precedent. A read-only,
  day-by-day replay of a farm on a map.
- `frontend/src/modules/labs/console/indexClasses.ts` — the Farm Console's
  colour classes and legend wording. This screen uses status colours instead,
  but the legend layout is worth copying.
