# The walk explainer: show why a cell got the result it got

Status: built. This document was the spec and is now the record of what
was built, with the three places the build departed from the draft marked
**changed in the build**.

## 1. The goal

An author reads a dry run row and cannot tell why the tree said what it said.
The row gives the finding set and the card text. It does not give the route the
walk took, the values it read on the way, or the combination rule that wrote the
text.

This document specifies one read-only view that answers "why this result". It
opens from a dry run row. It also opens from a real run's trace row, because the
question is the same question and the data has the same shape.

The view is called the **walk explainer** throughout this document. One React
component, two sources.

## 2. What already exists

Read off `origin/main` on 2026-09-21.

### 2.1 The engine records everything the view needs

`folding_engine.FoldingWalkResult.path` is a list of `FoldingPathStep`
(`folding_engine.py:183`):

| Field | What it holds |
| --- | --- |
| `node_id` | The node visited. |
| `kind` | `condition`, `register`, `set`, `switch` or `stop`. |
| `matched` | Yes or no for a condition. `None` for every other kind. |
| `label_en`, `label_ar` | The node's own label. |
| `condition_snapshot` | The values the condition read, by reference name. |
| `detail` | What the node did: the code a register wrote, the values a set wrote, the case a switch chose. |

That is the whole answer to "why". Nothing new has to be computed.

### 2.2 A real run stores the path already

- `_folding_path_steps` (`service.py:247`) turns `walk.path` into `TreePathStep`.
  It packs `kind` and `detail` into the step's values map, because that map is
  free-form JSONB.
- `_folding_evaluation` (`service.py:274`) puts the steps on
  `EvaluationResult.path`.
- `_TraceBuffer.add` (`service.py:496`) writes
  `node_path = _serialize_path(result.path)` on every trace row, with no status
  condition.
- `GET /v1/decision-tree-traces/{trace_id}` returns it as
  `node_path: TreePathStepDTO[]` (`frontend/src/api/decisionTrees.ts:269`).

So a real folding run's path is stored today and is already reachable from the
browser. No backend change is needed for that source.

### 2.3 The canvas already has the prop

`BetaCanvas` accepts `pathNodeIds?: ReadonlySet<string>`, commented "Cells the
dry run walked through, for the path overlay"
(`beta/components/BetaCanvas.tsx:79`). Nothing passes it. It also accepts
`rejectedNodeIds` and `rejectedEdgeKeys`, which is the halo styling to copy, and
leaving out `onAddNode`, `onMoveNode` and `onResetLayout` is what turns editing
off.

### 2.4 The old engine has a working version of this

`lib/dryRunHighlight.ts`, `components/TreeCanvas.tsx` and
`DecisionTreeViewerPage.tsx:746` draw a path for a non-folding tree. The model
there is one route to one leaf, and the leaf holds the answer. It cannot be
reused as is. See section 4.

### 2.5 The report already names this gap

`folding_report.py:313` writes `node_timing: {available: false, reason: ...}`,
and the reason it gives is the dropped path.

## 3. The three defects

### 3.1 The dry run throws the path away

`_fold_one_cell` (`folding_authoring.py:797`) calls `walk_tree`, reads
`walk.findings`, `walk.stopped_at` and `walk.error`, and never reads
`walk.path`. The dry run response has no path field.

This is the only thing standing between the goal and the code.

### 3.2 A combination rule loses its code at compile

`_check_combinations` (`folding_compiler.py:745`) builds each normalized rule
from `codes`, `action_type`, `status`, `text_en` and `text_ar`. It does not copy
`code`.

`parse_combination_rules` (`folding_engine.py:637`) already reads `code`, so
nothing else needs changing. But the compiler dropped it, so
`CombinationRule.code` is always `None`, `FoldedCard.rule_code` is always
`None`, and:

- the dry run table shows the fallback label "matched" instead of a rule name;
- `decision_tree_eval_traces.matched_rule` is `None` on every real run row,
  because `_fold_trace_columns` reads `card.rule_code` (`service.py:355`);
- the estate report works around it. `_rule_for` (`folding_report.py:322`)
  re-matches the identity against the rule list instead of reading the cell's
  own `rule_code`.

The goal says "the rule executed and manifested into the result", so this has to
be fixed.

### 3.3 The stored compiled bodies carry the old shape

A beta tree version stores `tree_compiled`. Fixing the compiler does not change
a body already written. Every version saved before the fix keeps a
`combinations` list with no `code`, and its runs keep showing no rule name.

A recompile pass is needed. See section 8.

## 4. The trace model, one shape for both sources

A folding walk is not shaped like an old-engine walk.

- An old walk ends at a leaf, and the leaf is the answer.
- A folding walk always ends at `stop`. The answer is built from `register`
  nodes spread along the route, then folded. The stop node says nothing.

So the explainer needs three visual roles, not one: nodes on the route, nodes
that registered a finding, and the end. And `pathHighlight` in
`lib/dryRunHighlight.ts` stays where it is; the beta module gets its own.

The two sources deliver the same information in two packings:

| | Dry run (new) | Real run (stored) |
| --- | --- | --- |
| `node_id` | own field | own field |
| `matched` | own field | own field |
| `label_en` / `label_ar` | own fields | own fields |
| `kind` | own field | inside `values.kind` |
| condition values | own field `values` | the rest of `values` |
| `detail` | own field | inside `values.detail` |

One pure function normalises both into a `WalkStep`:

```ts
export interface WalkStep {
  nodeId: string;
  kind: "condition" | "register" | "set" | "switch" | "stop";
  matched: boolean | null;
  labelEn: string | null;
  labelAr: string | null;
  values: Record<string, unknown>;
  detail: Record<string, unknown> | null;
}

export function walkStepsFromDryRun(path: BetaDryRunPathStep[]): WalkStep[];
export function walkStepsFromTrace(path: TreePathStepDTO[]): WalkStep[];
```

New file: `frontend/src/modules/decisionTrees/beta/lib/walkTrace.ts`, with unit
tests. The explainer component takes `WalkStep[]` and never sees either wire
shape.

From `WalkStep[]` a second pure function derives what the canvas needs:

```ts
export interface WalkHighlight {
  nodes: Set<string>;            // every node on the route
  edges: Set<string>;            // edge keys, in BetaCanvas's own key format
  registerNodes: Set<string>;    // nodes that wrote a finding
  stopNodeId: string | null;     // where the walk ended, or null on an error
  errorNodeId: string | null;    // the last node reached when the walk failed
}
```

The edge key format has to match the one `BetaCanvas` already builds for
`rejectedEdgeKeys`. It is read from the canvas, not invented here.

## 5. The API

### 5.1 The dry run: full path per cell, fetched only when asked

The main dry run response is unchanged. It stays lean, because a 300-cell block
would otherwise repeat a 20-step path 300 times for rows nobody opens.

A new route folds one cell and returns its path:

```
POST /v1/platform/decision-trees/beta/{tree_id}/dry-run/cell
{
  "block_id": "...",
  "cell_id": "...",
  "definition": {...} | null,
  "version_id": "..." | null
}
->
{
  "cell": { ...the same row shape the dry run returns... },
  "path": [
    {"node_id": "n1", "kind": "condition", "matched": true,
     "label_en": "NDVI below threshold?",
     "values": {"indices.ndvi.mean": 0.31, "params.ndvi_low": 0.40},
     "detail": null},
    {"node_id": "n7", "kind": "register", "matched": null,
     "label_en": "Low vigour",
     "values": {},
     "detail": {"code": "NDVI_LOW", "severity": "warning",
                "repeat": false, "raised": false}},
    {"node_id": "end", "kind": "stop", "matched": null,
     "values": {}, "detail": null}
  ],
  "rule": {
    "code": "mango_low_vigour_dry",
    "codes": ["NDVI_LOW", "SOIL_DRY"],
    "text_en": "...", "text_ar": "...",
    "status": "issue", "action_type": "irrigate"
  } | null,
  "composed_from": [
    {"code": "NDVI_LOW", "clause_en": "...", "clause_ar": "..."}
  ] | null
}
```

`rule` is set when a combination rule matched. `composed_from` is set when the
text was joined from clauses. Exactly one of the two is non-null on a carded
cell, and both are null when the cell produced no card.

Implementation: `_fold_one_cell` gains `include_path: bool = False` and a second
return path. The existing dry run keeps calling it with the default, so its
response does not change and no existing test moves.

**One risk to state plainly.** The dry run writes nothing and stores nothing, so
this second call re-walks the cell from a freshly built block context. If an
imagery or weather read landed between the two calls, the re-walk can answer
differently from the row on screen. The response therefore echoes `identity`,
`severity`, `status` and `rule_code` on `cell`, and the panel compares them with
the row it was opened from. When they differ it says so in one line and offers to
re-run. It must never draw a path that does not explain the row the author
clicked.

Alternative considered and not chosen: add `include_paths: bool` to the existing
dry run route and re-run the whole block when the first row is opened. One
context build instead of one per click, but it moves the whole block's paths
over the wire to answer one question. The per-cell route with React Query caching
on `(tree, version or definition hash, block_id, cell_id)` makes a re-open free,
which covers the repeat-click case the alternative was protecting.

### 5.2 The real run: one field, already in the query

`GET /v1/decision-tree-traces/{trace_id}` already answers with `node_path`.

**Changed in the build.** One thing was missing after all. The repository reads
`SELECT t.*`, so the three fold columns tenant 0095 added are already fetched,
but `EvalTraceDetailResponse` did not declare them and Pydantic dropped them.
The explainer could see every step of a real run and not the card the steps
added up to. `finding_set`, `matched_rule` and `registered_by` are now on that
model. No SQL changed.

The explainer also needs the tree to draw. The trace row carries `tree_code` and
`tree_version`; `getBetaTree(code)` returns every version with its `definition`,
so the definition is resolved client-side with no new endpoint. Versions are
append-only, so the version a trace names always still exists.

### 5.3 The rule code

- `folding_compiler._check_combinations` copies `code` into the normalized rule.
  It is optional. When present it must be a non-empty string and unique across
  the tree's rules; a duplicate is a new compile error,
  `combination-duplicate-code`, in both languages like every other rule there.
- No change to `parse_combination_rules`, which already reads it.
- `folding_report._rule_for` can then read the cell's own `rule_code` instead of
  re-matching the identity. That is a follow-up, not part of this change.

## 6. The screen

### 6.1 Opening it

The dry run table gains one column on the right, "Show details", one button per
row. It is enabled on every row, including a healthy cell with no findings and an
errored cell — "why did this cell find nothing" and "where did this walk fall
over" are the same question.

The traces page gains the same button on its detail view, opening the same panel.

### 6.2 The panel

A right panel, up to 50 percent of the screen width, over the page. Two rows.

**Top row, left column — the tree.** The read-only `BetaCanvas`. Nodes on the
route are drawn normally and the edges it traversed are drawn thicker. Every
other node and edge is dimmed to 20 percent. On an errored walk, the last node
reached carries the error mark. The canvas gets no `onAddNode`, no `onMoveNode`
and no `onResetLayout`, which is what turns editing off; panning and zoom stay
on, because a 74-node tree does not fit.

**Changed in the build.** The draft also marked each register node on the canvas
with the code it wrote. That was dropped. The step list already names the code
beside the node, and a second copy on a node box that is 140 pixels wide costs
more than it says. `walkHighlight` still returns `registerNodes`, so a later
change can add it without touching the engine or the wire.

**Top row, right column — the steps.** One box per step, in walk order, numbered.
The box header holds the node name and its result:

| Kind | Header result |
| --- | --- |
| `condition` | Yes or No |
| `register` | The finding code and its severity |
| `set` | The names it wrote |
| `switch` | The case it chose |
| `stop` | End of walk |

A box expands to show its detail. A condition shows each value it read, its
reference name, and the comparison. A register shows the code, the severity, and
whether this was a repeat that raised the severity. A set shows each name and the
value written. Clicking a box selects its node on the canvas, and clicking a node
on the canvas scrolls to its box. The two halves are one selection.

**Bottom row — the rule.** What turned the finding set into the card:

- when a rule matched: its code, its finding set, its text in both languages, and
  its status and action type;
- when the text was composed: the words "composed from clauses", then each
  finding's clause in walk order, and the joined result;
- when the cell produced no card: one line saying the walk registered no
  findings, which is a healthy cell and not a missing answer;
- when the walk errored: the error, and the node it happened on.

### 6.3 Arabic

The whole panel mirrors. The canvas does not mirror; a tree laid out right to
left would not match the designer the author just came from. Node labels inside
it use `label_ar` when present. Reference names and node ids stay left to right
and monospaced, the way the dry run table already draws the finding codes.

## 7. The estate report by node

Once `walk.path` survives, the estate run can count it. `folding_report.py`
gains:

```
"coverage_by_node": [
  {"node_id": "n7", "kind": "register", "label_en": "Low vigour",
   "cells": 412, "share_pct": 33.1}
],
"never_reached": [
  {"node_id": "n22", "kind": "condition", "label_en": "Salinity high?"}
]
```

`never_reached` is the useful half. It names the branches of the tree that no
cell in the estate exercised, which is the question an author asks after their
first estate run.

`node_timing` stays `available: false`. Timing needs a clock inside `walk_tree`,
which puts a `perf_counter()` call on every step of every production walk. That
is a separate decision with a cost, and it is not needed for this goal. The
`reason` string is updated, because half of it is no longer true.

**Changed in the build.** The estate run does not carry paths. `dry_run` takes
`collect_coverage`, counts node ids into a `Counter` per block, and answers with
`node_counts`. Carrying a path per cell to reach the same totals would move a
20-step list for every cell of every block, for a report that only ever prints
counts. A block the tree does not target is left out of the totals, the same
rule every other number in that report follows.

## 8. Recompiling the stored versions

Fixing the compiler does not fix a version already saved. A one-off pass reads
each beta tree version's `definition`, recompiles it, and writes `tree_compiled`.

Two things to settle before writing it:

1. **The content hash moves.** `hash_compiled` hashes the whole compiled body, so
   adding `code` to a rule changes the hash of any version that has one. Append
   is a no-op on an unchanged hash, so the stored hash must be rewritten in the
   same pass or the next save behaves oddly.
2. **A published version is history.** Rewriting the compiled body of a published
   version changes what a re-run of that version does — it starts naming its
   rule. That is the intent, and it is still a rewrite of a published row. The
   alternative is to leave old versions alone and accept that only trees
   republished after the fix name their rules.

My reading: recompile everything, published included. The compiled body is a
derived artifact of `definition`, and `definition` is the version. Nothing about
the result changes except that a rule gains a name it always should have had.
Worth one explicit yes before it runs against production.

## 9. Phases

| Phase | What | Where |
| --- | --- | --- |
| 1 | Carry `code` through `_check_combinations`, with the duplicate check. | backend |
| 2 | `_fold_one_cell` gains `include_path`; add the per-cell dry run route and its schema. | backend |
| 3 | `walkTrace.ts`: the two normalisers and the highlight builder, with unit tests. | frontend |
| 4 | The explainer component: canvas, step list, rule row. Its own tests. | frontend |
| 5 | Wire it into the dry run table's new column. | frontend |
| 6 | Wire it into the traces page, off `node_path`. | frontend |
| 7 | The recompile pass. | backend, one-off |
| 8 | `coverage_by_node` and `never_reached` in the estate report. | backend |

Phases 1 to 6 are the goal. Phase 7 decides how far back the rule names go.
Phase 8 is the report half.

## 10. Open questions

1. Recompile published versions, or only new ones? Section 8.
2. Does the explainer belong on the block health screen too? A grower looking at
   a red cell asks the same question an author asks. Out of scope here, but the
   component is built so that it could.
3. ~~Should the step list hide `set` steps by default?~~ Settled: hidden, with
   a "show N variable steps" toggle that says how many are hidden.
