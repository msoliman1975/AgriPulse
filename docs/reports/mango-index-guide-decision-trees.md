# Mango index guide → decision trees

Source: `tatoo Docs/AgriPulse_Mango_Indices_Full_EN.xlsx`
Region: Egypt. All numbers below are the **10 m (Sentinel-2)** column.

## 1. What the workbook actually contains

38,880 data rows across 30 weekly sheets. The stated shape is
9 varieties × 2 establishment methods × 3 sizes × 2 productivity states ×
12 indices × 30 weeks.

Measured against the file itself, most of that shape carries no information:

| Axis | Does the value change? | Evidence |
|---|---|---|
| Variety (9) | **No.** 0 of 4,320 keys differ across the 9 varieties | The file's own note: "No published spectral studies numerically differentiate between these nine specific varieties — values are general for the mango crop." |
| Establishment (grafted/seedling) | Only by a flat +5–8 % | Methodology §3: "a qualitative expert estimate not directly measured" |
| Week (30) | Only for CWSI and SMI, and only on productive trees | NDVI, EVI, SAVI, MSAVI, GNDVI, NDRE, NDMI, MSI, BSI are constant across all 30 weeks |
| Tree size (3) | **Yes, for every index.** Largest effect in the file | e.g. NDVI 0.10–0.22 small vs 0.65–0.81 big |
| Productivity (2) | **Yes, for CWSI and SMI in the harvest phase** | e.g. big+productive CWSI 0.10–0.25 → 0.25–0.45 from week 15 |

So the workbook reduces to a table keyed on **index × tree size × bearing ×
phenological phase**. That is what the trees below are built from.

### The 10 m table used

| Index | Small | Medium | Big | Direction |
|---|---|---|---|---|
| NDVI | 0.10–0.22 | 0.25–0.40 | 0.65–0.81 | low = bad |
| EVI | 0.05–0.14 | 0.14–0.24 | 0.43–0.59 | low = bad |
| SAVI | 0.12–0.24 | 0.28–0.42 | 0.54–0.70 | low = bad |
| MSAVI | 0.15–0.28 | 0.30–0.44 | 0.56–0.71 | low = bad |
| GNDVI | 0.12–0.24 | 0.30–0.45 | 0.59–0.73 | low = bad |
| NDRE | 0.08–0.18 | 0.18–0.30 | 0.38–0.52 | low = bad |
| NDMI | −0.15–0.00 | 0.00–0.12 | 0.11–0.27 | low = bad |
| MSI | 0.90–1.30 | 0.60–0.90 | 0.25–0.45 | **high = bad** |
| BSI | 0.35–0.55 | 0.15–0.30 | 0.04–0.14 | **high = bad** |
| CWSI | 0.15–0.35 | 0.10–0.30 | 0.10–0.25 | **high = bad** |
| CWSI, bearing + harvest phase | 0.38–0.63 | 0.25–0.54 | 0.25–0.45 | **high = bad** |
| SMI | 0.35–0.55 | 0.40–0.60 | 0.45–0.70 | low = bad |
| SMI, bearing + harvest phase | 0.27–0.47 | 0.31–0.51 | 0.35–0.60 | low = bad |

## 2. Fields the workbook needs that the platform did not have

| Workbook axis | Platform today | Action |
|---|---|---|
| Tree size (Small/Medium/Big) | `block_crops.canopy_size_class` exists but **no screen writes it** and it was removed from the decision-tree field list | New crop attribute `tree_size_class` on `mango` |
| Productivity (Productive / Non-productive) | Nothing | New crop attribute `bearing_status` on `mango` |
| Phenological phase (A/B/C) | `block.growth_stage` had 6 mango stages and no maturity | Added a `maturation` stage (migration 0073) |
| Establishment (Grafted/Seedling) | Crop attribute `establishment_method` | Reuse. Not branched on — see §5 |
| Imaging resolution (10 m / 3 m) | Sentinel-2 10 m only | Use the 10 m column. See §5 |
| Variety | Crop taxonomy | Not branched on — the workbook says the values do not differ |

A crop attribute was chosen over `canopy_size_class` because a crop attribute
renders its own form field, validates its own options, and is already a
decision-tree condition source. Reviving `canopy_size_class` would need new
frontend work and would put two size fields in front of the user.

## 3. Custom attribute cleanup

Seven mango attributes had been hand-authored through the admin screens.
Five of them shadow each other and are retired (`is_active = FALSE`, which is
what the screens' own delete does, so the rows and their values survive):

| Code | Label | Values recorded | Why retired |
|---|---|---|---|
| `001` | Tree Size | 0 | Second size field, multi-select |
| `002` | Tree type | 0 | Grafted/seedling — duplicates `004` |
| `testyyy` | testyyy | 0 | Test row |
| `003` | Tree size | 153 | Folds size and bearing into one list, so no rule can ask about size alone |
| `004` | Establish method | 153 | Duplicates the curated `establishment_method` |

Nothing is thrown away. Tenant migration 0084 copies the 306 recorded values
onto the curated definitions:

**Size comes from `tree_age` first**, and from `003` only where no age was
recorded. Age bands follow the size classes mango already carries: under 4
years → small, 4–8 → medium, over 8 → large.

Where `003` is the only signal:

* `01` Young non-productive → `tree_size_class=small`, `bearing_status=not_bearing`
* `02` Young new-productive → `tree_size_class=medium`, `bearing_status=bearing`
* `03` Mature productive → `tree_size_class=large`, `bearing_status=bearing`

`004` `01`…`06` → `seed` / `seedling` / `grafted_tree` / `rootstock` /
`cutting` / `tissue_culture`. Bearing always comes from `003`; only the size
half is superseded by age.

**Why age wins where both exist.** Every prod block carrying `tree_age` reads
2 or 3 years, while 100 of them carry `003 = 02`. Mapping that straight to
medium would call a three-year-old planting a 2–4 m canopy. The imagery
agrees with the age, not the label: those blocks read NDVI 0.17–0.21 and SAVI
0.16–0.19, which are the guide's small-tree bands. Taking the label over the
age would have put 100 of 108 blocks below their expected range on the first
sweep — a size error reported as a crop problem. Measured both ways before
choosing.

Result across both tenants: 125 small, 28 medium, 0 large. The 28 medium are
the blocks with a hand-entered `003 = 02` and no recorded age.

The curated `establishment_method` had been retired on prod while `004`
shadowed it. It is re-activated, because `004` is the copy that goes and
establishment is one of the workbook's own axes.

`tree_age` is kept (117 values, shadows nothing). `implantation_date` is
retired: it duplicates `block_crops.planting_date`, and on prod the two agree
on 71 of the 72 rows, so no data is lost by removing the field.

## 4. Trees built

Three new, one rewritten, one held. Not twelve — several of the workbook's
indices are restatements of each other, and one tree per index would put four
irrigation cards on the same block on the same day.

| Code | Reads | Fires when | State |
|---|---|---|---|
| `mango_canopy_vigour_by_size_v1` | MSAVI (small) / SAVI (medium) / NDVI (large) | Below that size's floor | New |
| `mango_canopy_moisture_by_size_v1` | NDMI | Below that size's floor | New |
| `mango_canopy_cover_gap_v1` | BSI | Above that size's ceiling | New |
| `mango_post_harvest_nitrogen_v1` | NDRE | Below that size's floor during post-harvest flush | Rewritten |
| `mango_irrigation_stress_cwsi_v1` | CWSI | Above that size's ceiling, relaxed for a bearing tree in maturation | **Held** — see §6 |

Each tree gates on `tree_size_class` first. If the field is empty the tree
reaches a `no_action` leaf that says so, so it never opens a card on a guess.

### What the rewrite of the nitrogen tree fixes

That tree compared every mango block against one NDRE floor of 0.30. The
workbook's bands are 0.08–0.18 small, 0.18–0.30 medium, 0.38–0.52 large, so
0.30 was wrong in **both directions at once**:

* it sits above the entire normal band for a small tree, so every young
  orchard was flagged nitrogen-deficient on every post-harvest scene;
* it sits below the entire normal band for a large tree, so a big block could
  fall from 0.45 to 0.31 — a real loss of canopy nitrogen — and never be
  flagged.

### Preview against real prod readings

Compiled trees walked against the latest 45-day index means for the 108 mango
blocks on prod that have recent imagery, using the migrated size and bearing
values and the `maturation` stage those blocks reach under the new curve:

| Tree | Would open |
|---|---|
| `mango_canopy_vigour_by_size_v1` | 54 of 108 |
| `mango_canopy_moisture_by_size_v1` | 28 of 108 |
| `mango_canopy_cover_gap_v1` | 0 of 108 |
| `mango_post_harvest_nitrogen_v1` | 0 of 108 |

82 cards on the first sweep. Two things to read into that number:

* The 28 moisture cards are exactly the 28 blocks sized `medium` from the
  hand-entered `003` label with no age to check it against. If those trees
  are in fact small, all 28 disappear. Worth checking on the ground.
* The nitrogen tree opens nothing because these blocks are now in
  `maturation`, not `post_harvest_flush`. It becomes live again on
  16 September. Under the old 0.30 floor and the old calendar it would have
  opened 89.

Observed ranges on those blocks: MSAVI 0.113–0.210, NDMI −0.116 to −0.034,
BSI 0.129–0.186, NDRE 0.051–0.142.

## 5. Indices deliberately given no tree, and why

* **MSI** — `MSI = SWIR/NIR`, `NDMI = (NIR−SWIR)/(NIR+SWIR)`. These are the
  same two bands and MSI is a monotonic transform of NDMI. A second tree
  would open a second card for one measurement, and an `all_of` across both
  would be a rule ANDed with itself.
* **EVI, GNDVI, SAVI, NDVI, MSAVI as separate trees** — all five answer
  "how much healthy green canopy is there". Folded into one vigour tree that
  picks the index the workbook itself recommends for that tree size.
* **NDWI** — the workbook's NDWI row gives the formula `(NIR−SWIR)/(NIR+SWIR)`,
  which is **NDMI**, not NDWI. The platform's `ndwi` is McFeeters
  `(GREEN−NIR)/(GREEN+NIR)` — open surface water, a different measurement. A
  mango moisture rule on the platform's `ndwi` would be wrong. The workbook
  says as much in its own NDMI row.
* **SMI** — the workbook's own entry: "There is no single globally
  standardized formula under this name (several different methods exist)",
  confidence **Medium-Low**, the lowest in the file. An absolute-threshold
  alert on a number with no agreed definition would be an alert on an
  arbitrary scale. CWSI covers the same decision at High confidence.
* **Variety** — the workbook produces identical numbers for all 9 varieties
  and states there is no study that separates them. A variety branch would
  be nine copies of one rule.
* **Establishment method (grafted vs seedling)** — a flat +5–8 % that the
  workbook calls an unmeasured expert estimate. That is smaller than the
  width of every band it would shift, and smaller than the mixed-pixel error.
  The field stays, and rules do not branch on it.
* **The 3 m column** — we buy Sentinel-2 (10 m). There is no PlanetScope
  download entitlement, so no 3 m pixel ever reaches the index pipeline.

## 6. Why the CWSI tree is held, not published

`seeds/held/mango_irrigation_stress_cwsi_v1.yaml` is written, reviewed and
tested, but is not in the directory startup sync reads, so it is never
published or evaluated.

**`cwsi` is pinned at its ceiling on prod.** 7,225 of 7,320 rows read exactly
1.0000 on one tenant, and 792 of 792 on the other — 98.7 % and 100 %. Walked
against real readings the rule would have opened 72 cards on its first
evaluation, all from a saturated number rather than from real water stress.

The cause is stated in the code that produces the index
(`app/modules/indices/computation.py`, `CWSI_DT_WET_C` / `CWSI_DT_DRY_C`):
the canopy-to-air bounds are literature constants, −2 °C to +6 °C, and are
not calibrated for Egyptian mango. A summer LST near 49 °C over a sparse
canopy on bright sand puts the difference well past +6 °C, so the value
clips to 1.0. That comment already says the output must be read as a relative
signal over time and "must not drive" irrigation volumes.

It now gates its relaxed ceiling on the `maturation` stage added in
migration 0073, so the phase mismatch that was open at review time is closed.

Release condition and the test that keeps it honest are in
`backend/app/modules/recommendations/seeds/held/README.md`.

## 7. Review of the existing trees

| Tree | Verdict |
|---|---|
| `mango_anthracnose_risk_v1` | Keep. Weather-risk score with a warning/critical split. Sound. |
| `mango_fruit_fly_risk_v1` | Keep. Same shape. Sound. |
| `mango_powdery_mildew_risk_v1` | Keep. Same shape. Sound. |
| `mango_stress_induction_v1` | Keep. NDMI AND cool forecast at pre-flowering, study-backed, correctly reads `ndmi` not `ndwi`. |
| `mango_canopy_health_v1` | Keep. Z-score against the block's own history; complements, does not duplicate, the new absolute-threshold vigour tree. |
| `mango_post_harvest_nitrogen_v1` | **Rewritten** — see §4. |
| `date_palm_*` (3), `potato_*` (6) | Reviewed, no change. Different crops, outside this workbook. |
| `ndvi_baseline_alert_v1` | Keep. Emits an *alert*, not a recommendation, so it does not duplicate a scouting card. |
| `scout_for_stress_v1` | **Archived.** Thresholds hardcoded at -0.5 / -1.5 rather than tunable, and on a mango block it asks the same question as `mango_canopy_health_v1`. |
| `demo_cell_low_ndvi_v1` | **Archived.** Fires on a hardcoded NDVI below 0.15, which the workbook calls normal for a small mango tree. |
| `testv01` (tenant-authored, live on prod) | **Removed by hand on prod** — see §9. |

## 8. The maturation stage

Mango had six stages and no maturity: `fruit_development` ran 1 May – 15 July
and `post_harvest_flush` picked up on 16 July. Egyptian mango is harvested
across July, August and September, so that calendar called the whole harvest
"post-harvest" and had no stage for ripe fruit on the tree.

Two things were already written as if the stage existed. Migration 0064 seeds
mango a Kc of 0.85 for `maturation`, and its own docstring lists that stage
among the ones 0033 supposedly created — that row has been unreachable since
it was written, and now resolves. And the workbook keys its CWSI and SMI
bands on a "Maturity/Harvest" phase that had nothing to map onto.

The code is `maturation`, matching the Kc seed and potato's stage of the same
name.

| Stage | Was | Now |
|---|---|---|
| `fruit_development` | 05-01 – 07-15 | 05-01 – 06-30 |
| `maturation` | — | **07-01 – 09-15** |
| `post_harvest_flush` | 07-16 – 10-31 | 09-16 – 11-15 |
| `veg_flush` | 11-01 – 11-30 | 11-16 – 11-30 |

Keitt keeps its own late-cultivar override: it is picked in September and
October, so its `maturation` runs 08-16 – 10-31 and its flush is compressed
into November.

Windows come from the Egyptian harvest calendar rather than the workbook's
own 8 June – 27 September, whose phenology source is a Sentinel-2 study in
Ghana.

Two consequences that would have been silent:

* **Fruit fly and anthracnose.** Both models scored `fruit_development` as a
  susceptible stage. Shortening it without adding `maturation` to their
  susceptible sets would have dropped both scores to the off-stage factor
  exactly when ripening fruit is most at risk. Both sets were widened.
* **The nitrogen tree.** It gates on `post_harvest_flush`, which now starts
  16 September instead of 16 July. Blocks in August go quiet, which is
  correct — they are in harvest, not rebuilding reserves.

Every existing stage code survives, so the two plan templates that anchor
activities to `fruit_development` and `post_harvest_flush` keep working; their
resolved dates move, which is the point. A test walks every day of a leap year
through both curves, new and old, and asserts each day lands in exactly one
stage — the auto-advance task holds a block's stage silently if a day matches
none.

## 9. The sweep that never ran

Found while verifying the deploy. `recommendations.evaluate_sweep` is
scheduled hourly by Beat but was **not registered on any worker**, so it has
never evaluated a decision tree in production.

`workers/celery_factory.py` listed `app.modules.recommendations` — the
package. Celery's `include=` imports the literal module name and does not
recurse, and that package's `__init__.py` is a docstring, so `tasks.py` was
never imported and its three `@shared_task` decorators never ran. The rule
was already written as a comment three lines below the entry that broke it.

Nothing failed loudly. Every hour the light worker answered
`Received unregistered task of type 'recommendations.evaluate_sweep' ...
KeyError` into its log and carried on: queue drained, pod Ready, no alert.
Asked directly, the running worker lists 55 tasks and none of them are
`recommendations.*`, while `phenology.*` and `irrigation.*` are there because
their entries name `.tasks`.

This explains something that looked like good news earlier in this work: none
of the mango seed trees had opened a single recommendation on prod. That was
not because they never matched — they were never run. The 435 cards on the
archived `testv01` came from manual "run tree on farm" calls, which is why
they were the only recommendations that existed anywhere.

Fixed in PR #564, one line plus a test that walks `beat_schedule` and asserts
each task resolves on the queue Beat routes it to. A wrong queue fails the
same silent way as a wrong module name, so both are covered.

Deployed as `c1b811f`. The light worker went from 55 to 58 registered tasks
with all three `recommendations.*` present, and one dispatched sweep opened:

| Source | Opened |
|---|---|
| `mango_canopy_vigour_by_size_v1` | 42 recommendations |
| `mango_canopy_moisture_by_size_v1` | 28 recommendations |
| `mango_fruit_fly_risk_v1` (critical) | 36 recommendations |
| `ndvi_baseline_alert_v1` | 29 alerts |
| Anthracnose, powdery mildew, canopy health, stress induction | 0 |

106 recommendations and 29 alerts, across 8 evaluation runs all recorded
`ok`, with 684 lineage traces on one tenant alone. The fruit-fly score reads
100 on green-valley: August in Egypt with fruit on the tree is the peak of
that risk, and `maturation` entering the susceptible set is what lets the
model say so.

## 10. Left to do by hand on prod

**Done.** `testv01` on tenant `019eafdc…` was a tenant-authored tree named
"My new tree" whose recommendation text was "me testing one more time", live
with 435 open spray cards. It existed only in that tenant's data, so a
migration was the wrong tool; it was archived and its 435 open cards
soft-deleted directly against prod, in one transaction. Applied and dismissed
rows were left alone — those record something a person did.

**One thing left, and it is yours to call.** 34 open alerts remain from
`monitor_mango_in_egypt`, a tenant-authored tree archived before this work
started. The tree cannot open more; these are stale rows of the same kind as
the `testv01` cards. Say the word and they go the same way.
