# Unified decision tree engine

Design document. Written 2026-09-16. Not implemented.

Answers the question raised against the "Unification model" note: why propose
four layers of trees instead of one tree that does the same work through
branching and conditions.

The short answer is that one tree is right, and the layered proposal was wrong.
The layered proposal cannot be built at all, because no tree can read another
tree's output. This document replaces it.

This document has two halves. Sections 1 to 11 are the design. Section 12 holds
the implementation prompts, written so another session can build each part
without re-reading the discussion.

---

## 1. The problem

There are 23 mango decision trees. Eleven of them are single-index band checks:
NDVI, EVI, SAVI, MSAVI, GNDVI, NDRE, NDMI, BSI, MSI, CWSI, SMI. Each one reads
one index, compares it to a size band, and opens its own card when the value is
out of band.

One real event fires several of them. An irrigation valve failure drops NDVI,
SAVI, EVI and NDMI and raises CWSI. That is five cards for one cause. Seven of
the eleven end their out-of-band branch with the same sentence: water shortage,
root or trunk damage, pest, disease, or nutrient shortage. A single vegetation
index cannot tell those apart, so the sentence is honest and useless.

`t_vigour_cause_split` already reads four indices and names one of four causes.
It proves the fix works. It does not replace the eleven trees. It runs beside
them, so the farmer gets the specific card and the five vague ones together.

### 1.1 Why the layered proposal cannot be built

The earlier note proposed four layers: guards, signal fusion, root-cause
diagnosis, and stage-gated risk. Layer 1 would compute a status and hand it to
layer 2.

The engine has no way to do that. A condition can read nine sources, listed in
`backend/app/shared/conditions/models.py:225-307`:

`indices`, `block`, `weather`, `weather_index`, `weather_risk`, `signals`,
`grid`, `crop_attribute`, `params`.

None of them is another tree. `parse_value_ref` raises on any source it does not
know (`models.py:307`). `ConditionContext` has no field for another tree's
result (`backend/app/shared/conditions/context.py:218-259`). Trees run
independently, in no order, and never see each other.

So the layer that was meant to be the simple part is the part that needs new
engine work. One merged tree needs none of that, because every status the
layered design wanted to pass between trees is arithmetic over sources a single
tree can already read. Anthracnose pressure is the clearest case: it is not the
output of `t_anthracnose_mealybug_watch`, it is `weather_risk` with
`risk_code: anthracnose` and `field: score`, which any tree can read
(`context.py:52-76`).

---

## 2. Why one tree, and what stopped it

Nothing in the engine prevents one tree from producing one correct card. One
evaluation walks one path and returns at the first leaf it reaches
(`backend/app/modules/recommendations/engine.py:218-285`). One tree writes at
most one card per evaluation unit (`service.py:661-863`). That is exactly the
wanted behaviour.

What stops a merged tree is not the walk. It is that the walk cannot remember.

### 2.1 The engine is a graph with no return

The compiled form is a flat node map plus a root
(`engine.py:12-40`). A decision node holds `condition.tree`, `on_match` and
`on_miss`. A leaf holds `outcome`. Two parents may point at the same node id,
and the reachability check does not forbid it (`loader.py:537-605`), so the
shape is a directed graph, not a strict tree.

A subtree can therefore be shared. It cannot be called and returned from. Once
two branches converge, the walk no longer knows which one it came from.

To remember that vigour was low while checking water, the water subtree has to
be repeated once per vigour state. That is multiplication, not addition.

Counted for the merged diagnosis:

- vigour states: 3
- water agreement subtree, about 7 nodes, repeated per vigour state: about 21
- nutrient, cover and pest checks repeated per surviving state: about 90
- index selection by soil and size: about 9 copies of the vigour check
- leaves: about 72

That is 150 to 250 nodes. It compiles and it runs. It is not reviewable by an
agronomist and every one of those 72 leaves needs its own card text.

### 2.2 What removes the multiplication

Two changes, and the second is the one that matters.

**A scratchpad.** A `set` node writes a named value and a `vars` source reads it
later. Write `water_status = dry`, read it four branches on.

**Register and continue.** A node records a finding and the walk carries on. The
tree stops being a cascade of combinations and becomes a sequence of independent
checks. At `stop`, the engine folds the collected findings into one card.

With both, the merged tree is about 40 nodes and roughly 15 checks in order.

Multi-way branching was also proposed. It is worth having, but it adds no
expressive power: a five-way switch is four binary nodes. It is included here
for authoring clarity and because it costs one step against the walk length
instead of four.

---

## 3. Decisions taken

Twenty-six decisions, in the order they were made.

| # | Decision |
| --- | --- |
| 1 | One card per cell. The card names one cause. |
| 2 | A `set` node writes a variable. It holds a literal or a copy of a live reading. A `vars` source reads it. |
| 3 | One merged tree per crop. Crop targeting stays on the tree row. |
| 4 | The merged tree runs at cell scope. The band check is the per-cell signal. The baseline stays a block-level modifier. |
| 5 | A node registers a finding and continues. At `stop` the engine folds the findings into one card. |
| 6 | Card text is composed from per-finding clauses. A named combination rule can override it. |
| 7 | A combination rule fires only on an exact match of the finding set. |
| 8 | A condition can read whether a finding is registered. It cannot read the finding's values. |
| 9 | The matching rule sets the action type. With no rule, the highest severity finding sets it. |
| 10 | When the finding set changes, the engine closes the open card and opens a new one. |
| 11 | A switch node with ordered cases is a real engine node kind. First match wins. |
| 12 | The health class comes from the finding set, through the same table as the text. |
| 13 | Finding codes live in a new platform table. Trees reference them by code. |
| 14 | Build a separate designer and a separate engine as a beta. Opted-in tenants get real cards and their old trees are off. Then migrate the trees and delete the old engine. |
| 15 | Cycle detection uses a visited-node set. The 64-step cap is removed. |
| 16 | A tenant opt-out table lists the platform trees that tenant does not run. |
| 17 | A trace row always stores the fold. Node path and resolved values stay conditional, as today. |
| 18 | A tenant may add finding codes in its own schema. The platform table wins on a conflict. |
| 19 | The designer keeps the node graph and adds the new node kinds to it. |
| 20 | Before a tenant is switched on, run the merged tree over their whole estate as a dry run and review the report. |
| 21 | Notify when the finding set gains a finding, or when severity rises. A shrinking set is silent. |
| 22 | A switch that matches no case stops the walk. The trace status is error. |
| 23 | The compiler rejects a tree where any path can end without reaching `stop`. |
| 24 | The fold is a set. A repeat register of one code is one entry, and the highest severity wins. |
| 25 | Parameter overrides gain a nullable `farm_id`. Resolution is declared default, then tenant, then farm. |
| 26 | Measure sweep cost in the dry run from decision 20. Do not optimise before that number exists. |

---

## 4. The node kinds

The engine discriminates node kind by which key is present, as it does today
(`engine.py:5-11`). Four kinds are added. A tree that mixes old leaves with new
register nodes is rejected at publish.

### 4.1 `register`

Records a finding and continues.

```yaml
n_water:
  label_en: Two of three water signals agree
  register:
    code: dry
    severity: warning        # info | warning | critical
  next: n_nutrient
```

The severity lives on the register node, not on the finding catalogue. The same
finding can be a warning on one route and critical on another.

### 4.2 `set`

Writes a variable. The value is a literal or a copy of a live reading. There is
no arithmetic and no expression language.

```yaml
n_pick:
  set:
    index_used: savi                              # literal
    ndvi_now:                                     # copied reading
      source: indices
      index: ndvi
      field: mean
  next: n_band
```

A `vars` source reads it back, in a condition or in `outcome.parameters`:

```yaml
condition:
  tree:
    op: eq
    left: {source: vars, name: index_used}
    right: savi
```

This also closes a gap that exists today. `outcome.parameters` substitutes only
`{source: params, name: x}` refs (`engine.py:334-336`), so a card can quote a
threshold but never a measurement. A copied reading fixes that.

### 4.3 `switch`

Ordered cases, first match wins. The default is required and the compiler
rejects a switch without one. The editor pre-fills it.

```yaml
n_pest:
  switch:
    on: {source: weather_risk, risk_code: anthracnose, field: score}
    cases:
      - {ge: 70, go: n_reg_pest_high}
      - {ge: 40, go: n_reg_pest_med}
    default: n_cover
```

A switch that matches no case stops the walk and the trace status is error. This
is deliberately stricter than the rest of the engine, which is permissive on
missing data (`evaluator.py:15-18`). Both behaviours now exist in one tree. See
section 10.

### 4.4 `stop`

Ends the walk and triggers the fold.

```yaml
n_end:
  stop: true
```

---

## 5. The fold

At `stop`, the engine holds a set of findings. It produces one card.

### 5.1 Identity

The identity is the sorted list of finding codes. It is used three ways: to pick
a combination rule, to decide whether an open card is stale, and to group cells
in the Action Center. One key, three uses.

An empty set means no card.

### 5.2 Severity

The highest severity among the findings. A repeated register of one code does
not add an entry; it raises the entry's severity if the new one is higher.

### 5.3 Text

Two paths.

A combination rule matching the finding set exactly supplies the text. With no
matching rule, the engine composes the text from each finding's clause, ordered
by severity.

```
findings:
  dry        clause_en: "leaf water is low"
  ndvi_low   clause_en: "canopy vigour dropped"
  pest_high  clause_en: "anthracnose pressure is 78 out of 100"

rule {dry, ndvi_low}:
  "Water shortage is the cause. Irrigate before treating anything else."

{dry, ndvi_low}            -> the rule's text
{dry, ndvi_low, pest_high} -> composed, because no rule matches exactly
```

Exact matching means most real cells compose. A third finding is common. The
composed path is the main path, not a fallback nobody reads. Its join order, its
severity ordering and its Arabic conjunctions have to be right.

### 5.4 Action type

`recommendations.action_type` is one value (`models.py:133`) and the Action
Center turns it into board work through a fixed map
(`action_center/service.py:30-38`). A wrong value creates the wrong work order.

A matching combination rule declares the action type, because that is the case
where the author knows the order of operations. With no matching rule, the
highest severity finding's action type is used.

Every finding contributes its own items to the `actions` horizons
(`models.py:139-142`) either way, so no advice is dropped from the card.

### 5.5 Health class

Each finding carries a default status in the catalogue. A combination rule may
override it. The worst status wins. An empty set is healthy.

This replaces the leaf as the source of the health colour. Under folding almost
every walk ends at the same `stop` node, so the leaf no longer distinguishes
anything.

### 5.6 Supersede

The open-card dedup index is `(block_id, cell_id, tree_id) WHERE state = 'open'`
(`0052_recommendation_alert_cell_id.py:45-59`). Folding to one card per cell
keeps that index correct with no change.

It also means a second insert is skipped without an error
(`service.py:795-800`). So when the finding set changes, the engine closes the
open card and writes a new one.

```
run 1: {dry}             -> card A (warning) open
run 2: {dry, pest_high}  -> card A closed, card B (critical) open, notify
run 3: {dry, pest_high}  -> card B untouched
run 4: {dry}             -> card B closed, card C (warning) open, silent
```

A notification goes out when the set gains a finding or when severity rises. A
set that loses a finding is silent, because a shrinking set never asks for more
work.

The cheapest close reuses the existing `expired` state and needs no constraint
change. The states today are `open`, `applied`, `dismissed`, `deferred`,
`expired` (`0015_recommendations.py:117`). A `superseded` state reads better and
means altering that check constraint.

---

## 6. Data model

### 6.1 `public.decision_tree_findings` (new)

The shared vocabulary. One row per finding code.

| column | type | notes |
| --- | --- | --- |
| `code` | text, primary key | lower snake case |
| `clause_en` | text, not null | one clause for the composed sentence |
| `clause_ar` | text, not null | |
| `name_en`, `name_ar` | text, not null | short label for the group header |
| `default_status` | text, not null | health class, check constrained |
| `description_en`, `description_ar` | text, null | for the admin screen |
| `is_active` | boolean, default true | |

The catalogue owns the code, the clause and the default status. The tree owns
which findings it registers, at what severity, and its own combination rules.

So `dry` means one thing in the mango tree and the potato tree, the clause is
translated once rather than once per crop, and Action Center can group across
trees.

### 6.2 `tenant_*.decision_tree_findings` (new)

Same shape. A tenant authoring its own tree may add codes here without waiting
for the platform.

The fold resolves the platform table first, then the tenant table. If a code
exists in both, the platform row wins, and the admin screen flags the tenant row
as shadowed.

### 6.3 `tenant_*.decision_tree_opt_outs` (new)

| column | type | notes |
| --- | --- | --- |
| `tree_id` | uuid, primary key | logical reference to `public.decision_trees.id` |
| `reason` | text, null | free text, shown in the admin screen |
| `created_at`, `created_by` | | |

`is_active` sits on the shared platform row (`models.py:74`), so clearing it
turns a tree off for every tenant at once. A tenant switching to the merged tree
needs its own way to stop running the eleven index trees.

The sweep loads this list beside the parameter overrides it already loads per
sweep (`service.py:425-427`) and filters the tree list from
`list_active_trees_with_current_version` (`repository.py:51-81`).

Note: this is a logical reference, not a database foreign key. A tenant schema
must never hold a foreign key into `public`.

### 6.4 `tenant_*.tree_parameter_overrides` (changed)

Add `farm_id uuid NULL`. The primary key becomes
`(tree_id, param_name, farm_id)`, with a partial unique index for the
`farm_id IS NULL` row so a tenant default cannot be duplicated.

Resolution layers: declared default, then the tenant row, then the farm row. The
engine already layers declared default and tenant override
(`engine.py:81-104`); this adds one more.

The sweep currently loads overrides once per sweep. It will load them per farm.

### 6.5 Tree version content (changed)

A version stores the tree definition and its compiled form
(`models.py:82-108`). Two blocks are added to the definition:

```yaml
registers:
  - dry
  - ndvi_low
  - pest_high

combinations:
  - codes: [dry, ndvi_low]
    action_type: irrigate
    status: stressed
    text_en: "Water shortage is the cause. Irrigate before treating anything else."
    text_ar: "..."
```

`registers` is the declared list of codes this tree may register. The compiler
checks every `register` node against it, and every entry in it against the
catalogue. A code that does not resolve fails the publish.

### 6.6 `tenant_*.decision_tree_eval_traces` (changed)

Today the payload grain is uneven on purpose: `fired` and `error` rows carry the
full node path and resolved values, a `clear` row keeps the path and drops the
values (`service.py:116-119`, `0062_decision_tree_eval_traces.py:33-46`).

Three columns are added and they are written on every row, whatever the status:

- `finding_set` — the sorted codes, as JSONB
- `matched_rule` — the combination rule id, or null for composed text
- `registered_by` — code to list of node ids, for the duplicate case

Those are short and they answer the first question anyone asks. The long payload
stays conditional.

### 6.7 `recommendations` (changed)

Add `finding_set` JSONB, not null, default `[]`. The Action Center groups on it
and the supersede check compares against it.

There is no `leaf_node_id` column today (`models.py:110-155`) and none is added.
Under folding the leaf is always `stop` and says nothing.

---

## 7. The merged tree, sketched

One tree per crop. This is the mango one, at cell scope.

```
 1  set index_used  by soil texture and size class
 2  index_used below its size band          -> register ndvi_low
 3  NDMI below band                          |
 4  SMI below band                           |  two of three agree
 5  CWSI above band                          |  -> register dry
 6  NDRE below band                          -> register nutrient_low
 7  BSI above band                           -> register cover_open
 8  switch on anthracnose score              -> register pest_high / pest_med
 9  switch on powdery mildew score           -> register mildew_high
10  switch on fruit fly score                -> register fly_high
11  stop
```

Roughly 40 nodes. The cascade that used to decide between causes is gone. The
fold decides, using the combination rules.

Combination rules worth writing first, taken from the cases the old trees
already tried to express:

| set | text |
| --- | --- |
| `{ndvi_low, cover_open}` | Vigour dropped and bare ground increased. Likely missing trees, not a weak canopy. |
| `{ndvi_low, dry}` | Vigour and leaf water both dropped. Water shortage is the fix. Irrigate first. |
| `{ndvi_low, nutrient_low}` | Vigour and leaf nitrogen both dropped. Feed before scouting. |
| `{ndvi_low, dry, nutrient_low}` | Both water and nitrogen are short. Irrigate first, then feed. |
| `{ndvi_low, pest_high}` | Vigour dropped and anthracnose pressure is high. Treat now. |

Everything else composes.

### 7.1 What cell scope gives and what it does not

A cell-scoped tree runs once per cell with the cell's imagery means swapped into
an otherwise block-level context (`service.py:97-113`).

Only `mean` is per cell. `baseline_deviation`, `slope`, `delta` and
`trend_direction` keep the block's values, because `block_grid_aggregates` has
no per-cell equivalent (`service.py:1340-1352`). Weather, weather indices,
weather risk, signals, grid, growth stage, soil texture, salinity class and crop
attributes are all block-level and inherited.

So the band check is the per-cell signal. The baseline drop is a block-level
modifier: it says the block is declining, and the band check says which cells
are weak.

The card must not claim that a cell dropped against its own history. It did not
measure that.

---

## 8. The designer

The beta designer keeps the node graph and adds the new node kinds to the same
canvas. It is a separate screen from the current editor and writes to separate
tree rows.

What it has to add:

- Four node kinds: register, set, switch, stop.
- A finding picker that reads the platform catalogue and the tenant one, and
  shows which table a code came from.
- A combinations tab: a table of finding sets with text, action type and status.
- A publish check that lists every path that does not reach `stop`, naming the
  node.
- A dry run that shows the fold for a chosen block, per cell.

---

## 9. Rollout

Four stages. Nothing is deleted until the last one.

**Stage A — build the beta.** New engine, new compiler, new designer, new
tables. It writes nothing to `recommendations` and is not on the schedule. The
only way to run it is the dry run.

**Stage B — validate.** For each candidate tenant, run the merged tree over
every block and cell they have, using the dry-run path, which writes nothing
(`service.py:2202`). Produce a report and have an agronomist read it before
anything is switched on.

```
Dry run — tenant Bashayer, mango_unified

  cells evaluated        4,312
  no findings            3,780  (87.7%)
  {dry}                    204
  {dry, ndvi_low}          118  rule r3
  {ndvi_low}                96
  {ndvi_low, pest_high}     71  composed
  8 other sets              43

  rules fired        2 of 6
  composed fallback  71.4% of carded cells

  total walk time    18.4 s      per cell  4.3 ms
```

The same report answers the sweep-cost question. That is the measurement
decision 26 asks for.

**Stage C — wire it up.** Opt a tenant in. Their merged tree runs on the normal
sweep and writes real cards. Their eleven index trees go into the opt-out table
on the same day. Action Center grouping and the notification digest move to the
finding set.

**Stage D — migrate and delete.** When every tenant is on the new engine,
convert the remaining old trees, remove the old walk path, remove the old
editor, and drop the eleven index trees from the catalogue.

---

## 10. Traps

**Two behaviours for missing data.** A plain condition on a missing value is
false and takes `on_miss` (`evaluator.py:15-18`). A switch on a missing value
stops the walk with an error (decision 22). Both now exist in one tree. With
cell scope, a missing index means every cell in the block errors and the block
gets no cards at all. Cloud cover makes missing indices common. Watch this in
the stage B report before stage C.

**The composed path is the main path.** Exact matching (decision 7) means a
third finding sends the fold to composition. Do not treat composed text as a
fallback. Measure how often it runs, in the stage B report.

**`weather_risk` is block-level.** In a cell-scoped run, the pest score is the
same in every cell. A pest finding alone does not differentiate cells. Combined
with a per-cell vigour finding it does.

**Migration numbers.** Run `git ls-tree --name-only origin/main
backend/migrations/public/versions/` and the same for `tenant`, and take the
next numbers from that. A local worktree listing has been wrong before.

**New tenant tables must join the purge manifest.** Add
`decision_tree_opt_outs` and `decision_tree_findings` to
`backend/app/shared/purge/registry.py` or continuous integration fails.

**Never write a foreign key from a tenant schema into `public`.** Use a logical
UUID column.

**`op.drop_constraint` doubles the name** the same way `create_check_constraint`
does. Check the real constraint name in the database before writing the
migration for `tree_parameter_overrides`.

**`execute` returns a `Result`, which has no `rowcount`.** There is a
`_rowcount` helper in `backend/app/modules/recommendations/repository.py`
already.

**A 204 response needs `response_model=None`** or every test that assembles the
application fails at import.

**Pass real date and UUID objects to binds,** not strings, when the query casts
them.

**A test's own `commit()` unscopes the next read.** The symptom is an empty list
with no error. Check the search path.

**Run `pytest tests/unit` as well as the integration suite.** Unit failures on a
Windows machine are usually environment, not the change. Confirm against `main`
in a worktree before believing them.

**Docker does not run on the Windows development machine,** so integration tests
never run locally and continuous integration is the only backend signal.
`backend-integration` is `continue-on-error` and has timed out at its 35 minute
cap more than once, so read the per-job list rather than the run badge.

**This repository formats with `black`, not `ruff format`.**

**Frontend and backend constants drift without an error.** If a finding status
or an action type is listed in both, add a test that reads one from the other.

---

## 11. Not in this release

These were considered and deliberately left out.

- **Per-branch targeting.** Targeting stays on the tree row: `crop_paths`,
  `country_codes`, `soil_textures` (`service.py:1389-1441`). Crop cannot move
  into conditions, because `crop_path` was removed as a condition source on
  purpose (`conditions/models.py:44-52`). One merged tree per crop is the answer
  instead.
- **Per-node scope.** Scope stays a whole-tree property, `block` or `cell`
  (`0045_decision_tree_scope.py:44-49`).
- **Per-tree cadence.** There is still one global sweep interval
  (`backend/workers/beat/main.py:131-133`). Revisit only if the stage B timing
  says to.
- **A tree reading another tree.** Not needed. Every status the layered proposal
  wanted to pass between trees is readable from an existing source.
- **An expression language in `set`.** Literals and copied readings only.
  Counting, minimum and maximum stay as branch structure.
- **Per-cell temporal baselines.** `block_grid_aggregates` has no per-cell
  history. Adding it is a data project, not a tree change.

---

## 12. Implementation prompts

Nine prompts. Each is written for a session with no memory of this discussion.

Order: prompt 1 first. Prompts 2 and 3 can run in parallel after it merges.
Prompt 4 needs 2 and 3. Prompt 5 needs 1 and 3. Prompts 6 and 7 need 4.
Prompt 8 needs 7. Prompt 9 is last and needs every tenant migrated.

---

### Prompt 1 — Finding catalogues

> Read `docs/proposals/unified-decision-tree-engine.md` sections 6.1, 6.2 and 10
> first.
>
> Build the finding catalogue. No engine change and no user interface in this
> prompt.
>
> 1. Before writing any migration, run
>    `git ls-tree --name-only origin/main backend/migrations/public/versions/`
>    and the same for `tenant`, and pick the next numbers from what you see. Do
>    not trust the local worktree listing.
> 2. Add `public.decision_tree_findings` exactly as section 6.1 specifies,
>    including the check constraint on `default_status`.
> 3. Add `tenant_*.decision_tree_findings` with the same columns, in the tenant
>    migration chain.
> 4. Add ORM models next to the existing catalogues in
>    `backend/app/modules/recommendations/models.py`. `DecisionTree` at line 41
>    is the pattern for a public catalogue row.
> 5. Register the tenant table in `backend/app/shared/purge/registry.py`.
>    Continuous integration fails if a tenant table is missing from the manifest.
> 6. Write one resolver function: given a code and a tenant, return the row,
>    platform first then tenant. Put it in a pure module with no database
>    session so it can be unit tested. It takes both dictionaries as arguments.
> 7. Add platform admin endpoints to list, create, update and deactivate a
>    platform finding, and tenant endpoints for the tenant table. Follow the
>    shape of the existing decision tree authoring endpoints in
>    `backend/app/modules/recommendations/router.py`.
> 8. Seed the platform table with the codes in section 7: `ndvi_low`, `dry`,
>    `nutrient_low`, `cover_open`, `pest_high`, `pest_med`, `mildew_high`,
>    `fly_high`. Write real clauses in English and Arabic. Read the existing
>    mango tree card text for the wording to match.
>
> Tests: unit tests for the resolver covering a platform-only code, a
> tenant-only code, and a code in both where the platform row must win.
> Integration tests for the endpoints including a tenant trying to write a
> platform row.
>
> A 204 response needs `response_model=None` or every test that assembles the
> application fails at import. Format with `black`, not `ruff format`. Run
> `pytest tests/unit` as well as the integration suite.

---

### Prompt 2 — Beta engine: node kinds and the fold

> Read `docs/proposals/unified-decision-tree-engine.md` sections 4 and 5 first.
> Prompt 1 must be merged.
>
> Build the new walk and the fold as a separate module. Do not change
> `backend/app/modules/recommendations/engine.py`. Nothing in this prompt writes
> to the database.
>
> 1. Create a new module beside the existing engine. Read `engine.py:12-40` for
>    the compiled shape and `engine.py:218-285` for the current walk before you
>    start.
> 2. Implement four node kinds as section 4 specifies: `register`, `set`,
>    `switch`, `stop`. Discriminate by which key is present, the way the current
>    engine does at `engine.py:5-11`.
> 3. Add two condition sources. `findings` answers presence only, never values.
>    `vars` reads what a `set` node wrote. Extend `parse_value_ref` in
>    `backend/app/shared/conditions/models.py:225-307`. Both must fail the same
>    way an unknown source does today.
> 4. Replace the step cap with a visited-node set. Revisiting a node is a cycle.
>    Report the two node ids that closed the loop. The current cap is
>    `_MAX_STEPS = 64` at `engine.py:67` and the current message is at
>    `engine.py:280-285`. A long honest walk must not be treated as a cycle.
> 5. A switch that matches no case ends the walk with an error, not with the
>    default. This is deliberate and it differs from the permissive contract at
>    `backend/app/shared/conditions/evaluator.py:15-18`. Record the node id in
>    the error.
> 6. Implement the fold exactly as section 5 specifies: identity as the sorted
>    code list, highest severity wins, exact-match combination rule or composed
>    text, action type from the rule or the worst finding, status from the rule
>    or the worst finding.
> 7. A repeat register of one code is one entry. Raise its severity if the
>    repeat is higher. Keep the list of node ids that registered it.
> 8. Composed text joins clauses in severity order. Get the Arabic conjunction
>    right. Read an existing Arabic card text in the mango seeds for the style.
>
> Tests: unit tests only, no database. Cover an empty fold, one finding, three
> findings with an exact rule, three findings with no rule, a repeat register
> where the second is more severe, a switch that matches nothing, a cycle, and a
> walk of 200 honest steps.

---

### Prompt 3 — Beta compiler and publish checks

> Read `docs/proposals/unified-decision-tree-engine.md` sections 4, 6.5 and 10
> first. Prompt 1 must be merged.
>
> Build the compiler for the new tree shape as a separate module. Do not change
> `backend/app/modules/recommendations/loader.py`.
>
> 1. Read `loader.py:537-605` for the current reachability check before you
>    start. It validates that every `on_match` and `on_miss` names a known node
>    and every leaf has an outcome.
> 2. Compile the new definition shape: nodes, `registers`, `combinations`. The
>    `parameters` block keeps its current rules at `loader.py:226-284`.
> 3. Reject a tree that mixes an `outcome` leaf with a `register` or `stop`
>    node. The two shapes must never coexist in one tree.
> 4. Reject a tree where any reachable path can end without reaching `stop`.
>    Name every offending node in the error, not just the first. This is a
>    full-path walk, not a reachability check.
> 5. Reject a switch without a `default`.
> 6. Reject a `register` whose code is not in the tree's `registers` list, and a
>    `registers` entry that resolves against neither catalogue. Use the resolver
>    from prompt 1.
> 7. Reject a `vars` read of a name that no `set` node on any path to that node
>    writes. This is a path check, not a whole-tree check.
> 8. Reject a combination whose codes are not all in `registers`.
>
> Tests: unit tests only. One test per rejection, each asserting the message
> names the right node. Plus one valid 40-node tree that compiles, modelled on
> section 7.

---

### Prompt 4 — Persistence, supersede and trace

> Read `docs/proposals/unified-decision-tree-engine.md` sections 5.6, 6.4, 6.6
> and 6.7 first. Prompts 2 and 3 must be merged.
>
> Make the new engine write cards and traces. It is still not on the schedule
> after this prompt.
>
> 1. Add `finding_set` JSONB to `recommendations`, not null, default `[]`. Get
>    the migration numbers from `origin/main` as prompt 1 describes.
> 2. Add `finding_set`, `matched_rule` and `registered_by` to
>    `decision_tree_eval_traces`. Write all three on every row whatever the
>    status. Read `service.py:116-119` and
>    `backend/migrations/tenant/versions/0062_decision_tree_eval_traces.py:33-46`
>    for why the existing payload grain is uneven, and keep that grain for the
>    node path and resolved values.
> 3. Implement supersede. When the stored `finding_set` differs from the new
>    one, close the open card and insert a new one. The dedup index at
>    `backend/migrations/tenant/versions/0052_recommendation_alert_cell_id.py:45-59`
>    is correct as it stands and must not change. Note that a second insert is
>    skipped without an error today at `service.py:795-800`.
> 4. Use the existing `expired` state for the close. The states are check
>    constrained at
>    `backend/migrations/tenant/versions/0015_recommendations.py:117`. If you
>    add a `superseded` state instead, be aware that `op.drop_constraint` doubles
>    the name the same way `create_check_constraint` does; read the real
>    constraint name from the database first.
> 5. Add `farm_id uuid NULL` to `tree_parameter_overrides`. The primary key
>    becomes `(tree_id, param_name, farm_id)`. Add a partial unique index for
>    the `farm_id IS NULL` row. The current table is at
>    `backend/migrations/tenant/versions/0032_tree_parameter_overrides.py:56-75`.
> 6. Layer resolution: declared default, then the tenant row, then the farm row.
>    The engine layers the first two at `engine.py:81-104`.
> 7. `execute` returns a `Result`, which has no `rowcount`. There is a
>    `_rowcount` helper in
>    `backend/app/modules/recommendations/repository.py` already.
>
> Tests: integration tests for supersede across four runs as section 5.6 shows,
> for the three-layer parameter resolution, and for a trace row of each status
> carrying the fold columns. A test's own `commit()` unscopes the next read in
> this codebase; the symptom is an empty list with no error.

---

### Prompt 5 — Beta designer

> Read `docs/proposals/unified-decision-tree-engine.md` sections 4, 6.5 and 8
> first. Prompts 1 and 3 must be merged.
>
> Build the beta designer as a new screen. Do not change the existing decision
> tree editor.
>
> 1. Read the existing editor under
>    `frontend/src/modules/decisionTrees/` first and copy its layout and its
>    node graph interaction.
> 2. Add the four node kinds to the canvas: register, set, switch, stop. A
>    switch node shows its ordered cases and its default in the node body.
> 3. A register node picks its code from the catalogue and sets its severity.
>    Show which table the code came from, platform or tenant.
> 4. A new node that is a switch gets its default pre-filled with the next node
>    in the canvas. The author can change it. It is always stored.
> 5. Add a combinations tab: a table of finding sets with English text, Arabic
>    text, action type and status. Sets are picked from the tree's `registers`
>    list, not typed.
> 6. The publish button shows every compiler rejection with the node named, from
>    prompt 3. Do not let a publish proceed with any rejection outstanding.
> 7. Add a dry run panel: pick a block, see the fold per cell, with the finding
>    set, the matched rule and the resulting text.
> 8. Translate every new string into English and Arabic. Arabic entity names and
>    right-to-left layout already have established patterns in this codebase;
>    follow them rather than inventing new ones.
>
> Frontend and backend constants drift without an error. The finding status
> values and the action types appear on both sides. Add a test that reads one
> list from the other rather than writing the values twice.
>
> Continuous integration runs `tsc -b`, which passes on a stale cache. Delete
> the build info before trusting a local pass. Never run `prettier --write` on a
> broad glob.

---

### Prompt 6 — Dry run report

> Read `docs/proposals/unified-decision-tree-engine.md` sections 9 and 10 first.
> Prompt 4 must be merged.
>
> Build the estate-wide dry run and its report. Nothing here writes a card.
>
> 1. Add a batch dry run: given a tenant and a tree, run the new engine over
>    every active block and, for a cell-scoped tree, every cell. Use the
>    existing dry-run path at
>    `backend/app/modules/recommendations/service.py:2202` as the model. It
>    writes nothing, deliberately, and this must not change that.
> 2. Produce the report in section 9: cells evaluated, cells with no findings,
>    a count per finding set, which sets matched a rule and which composed, how
>    many rules fired out of how many exist.
> 3. Add timing: total walk time, time per cell, and the slowest check by node.
>    This is the measurement decision 26 asks for, so it must be in the same
>    report, not a separate tool.
> 4. Count error rows separately and name the node that caused each. A switch
>    on a missing index stops the walk, so this number tells you whether cloud
>    cover will blank a block before any tenant is switched on.
> 5. Add a platform admin screen showing the report for a chosen tenant and
>    tree, with the finding-set table sortable by count.
>
> Docker does not run on the Windows development machine, so integration tests
> never run locally. Continuous integration is the only backend signal.
> `backend-integration` is `continue-on-error` and has timed out at its 35
> minute cap before; read the per-job list, not the run badge.

---

### Prompt 7 — Wire to the sweep

> Read `docs/proposals/unified-decision-tree-engine.md` sections 6.3 and 9
> first. Prompt 4 must be merged, and prompt 6's report must have been reviewed
> for the tenant you are switching on.
>
> Put the new engine on the schedule for opted-in tenants.
>
> 1. Add `tenant_*.decision_tree_opt_outs` as section 6.3 specifies. It is a
>    logical reference to `public.decision_trees.id`, never a database foreign
>    key. Register it in `backend/app/shared/purge/registry.py`.
> 2. Filter the tree list by the opt-out table. The list comes from
>    `list_active_trees_with_current_version` at
>    `backend/app/modules/recommendations/repository.py:51-81`. Load the
>    opt-outs beside the parameter overrides already loaded per sweep at
>    `service.py:425-427`.
> 3. Dispatch a tree to the old walk or the new one by its compiled shape. A
>    tree with `register` nodes uses the new engine. A tree with `outcome`
>    leaves uses the old one. Prompt 3 already guarantees no tree has both.
> 4. Add a platform admin screen to manage a tenant's opt-outs, showing which
>    merged tree replaces each one.
> 5. Do not add a second Beat entry and do not change the sweep interval. There
>    is one global interval at `backend/workers/beat/main.py:131-133` and it
>    stays.
>
> Before switching a tenant on, add their eleven index trees to the opt-out
> table in the same change. Running both engines for one tenant produces the
> duplicate cards this whole design removes.

---

### Prompt 8 — Action Center and notifications

> Read `docs/proposals/unified-decision-tree-engine.md` sections 5.6 and 6.7
> first. Prompt 7 must be merged.
>
> Group by the finding set and notify on the right changes.
>
> 1. Add a `finding` grouping key to the Action Center queue. The existing keys
>    are `none`, `action_type`, `block`, `due` at
>    `backend/app/modules/action_center/router.py:95` and the builder is at
>    `backend/app/modules/action_center/service.py:224-262`. Group cell rows
>    with the same `finding_set` within one block.
> 2. The group header names the finding set using the `name_en` and `name_ar`
>    from the catalogue, plus the cell count and the worst severity.
> 3. Change the digest. Today it sends one message per tree and block reading
>    "N zones flagged in this block" (`service.py:532-565`), which names no
>    cause. Send one per tree, block and finding set, and name the cause.
> 4. Implement the notify rule from decision 21: send when the set gains a
>    finding, or when severity rises. Stay silent when the set only loses a
>    finding, and when nothing changed.
> 5. Scheduled sweeps have never called `register_subscribers`. Check whether
>    that is still true before claiming any of this reaches a mailbox. Render a
>    real email and read it; a card that printed a raw UUID passed every test
>    once.
>
> Tests: integration tests for each of the five transitions in section 5.6, and
> a grouping test with two finding sets in one block across 30 cells.

---

### Prompt 9 — Migrate and delete

> Read `docs/proposals/unified-decision-tree-engine.md` section 9, stage D,
> first. Every tenant must be on the new engine, with the report from prompt 6
> reviewed for each.
>
> Remove the old engine. Do this as several pull requests, not one.
>
> 1. Confirm no tenant runs an `outcome`-leaf tree. Query the catalogue and put
>    the count in the pull request body. If any tenant still does, stop and say
>    so.
> 2. Convert the remaining platform seed trees to the new shape, one per pull
>    request, each with a dry-run report comparing old and new output on a real
>    tenant. A conversion that changes card text is a change of advice and needs
>    an agronomist to approve it.
> 3. Remove the eleven mango index trees from the catalogue and the opt-out rows
>    that referenced them.
> 4. Remove the old walk from `backend/app/modules/recommendations/engine.py`
>    and the dispatch added in prompt 7.
> 5. Remove the old decision tree editor from the frontend and point its route
>    at the new designer.
> 6. Eighteen platform trees still sync from files on disk at every start
>    (`backend/app/core/app_factory.py:48-54`,
>    `backend/app/modules/recommendations/loader.py:1-22`). Decide whether that
>    loader stays or the trees become database rows only, and say which in the
>    pull request body.
>
> Verify against production, not against a local run. Read the live image tag
> before claiming a deploy landed.
