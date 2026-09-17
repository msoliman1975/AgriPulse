# One tree, not four layers

Written 2026-09-17. Answers `Unification model.pdf`, which proposes cutting the
23 mango trees down to 13 by splitting them into four layers.

The problem the PDF describes is real and this document does not argue with it.
The four-layer shape is what that problem looked like through the old engine.
The folding engine removes the constraint the layers were working around, so
the same problem is answered here by **one tree**.

---

## 1. The problem, in the PDF's own terms

Eleven of the 23 mango trees are single-index band checks. Each reads one index,
compares it to a size band, and opens its own card. A single real event — an
irrigation valve failing — moves NDVI, SAVI, EVI, NDMI and CWSI at once, so the
farmer gets five cards, each saying some version of "could be water, pest or
nutrient".

Seven of those eleven end on the same three-word guess, because one vegetation
index cannot tell those causes apart. `t_vigour_cause_split` already proves the
fix: it cross-reads four indices and names one of four causes. It just is not
the tree that fires.

## 2. Why the PDF reached for layers

The old engine gives a tree one outcome per leaf, and a tree cannot read
another tree. To cross-read five indices and still open one card, the PDF had
to invent a place for the cross-reading to happen — Layer 2 — and a way for the
index trees to hand it their answers without opening cards of their own —
Layer 1, publishing a status object.

That is a sound design for an engine where a card is a leaf. It carries three
costs, all of them from the workaround rather than from the agronomy:

- **13 trees to keep in step.** A band change to S1 has to be read against D1's
  cascade, because S1's output is D1's input.
- **No condition source reads another tree.** Layer 1 to Layer 2 needs a new
  mechanism, and Layer 3's "publish your score as a queryable signal" needs a
  second one.
- **The order of the cascade decides the answer.** D1's step 2 beats step 4, so
  a cell that is both dry and opening up can only ever be told one of the two.

## 3. What the folding engine changes

In the folding engine a tree does not open a card at a leaf. It walks once per
cell, **registers findings** as it goes, and **folds** the whole set into one
card at the end. So:

| The PDF needs | The folding engine already has |
| --- | --- |
| Layer 1 statuses that open no card | a `register` node. It records a finding and carries on. |
| Layer 2 reading Layer 1's outputs | the finding set at `stop`. Everything the walk found is in one place. |
| D1's ordered cascade | `combinations`: a rule matches a finding **set**, not a first hit. |
| Layer 3 scores feeding D1 | `{source: weather_risk, risk_code: …, field: score}` in the same walk. |
| One card per real event | the fold. One walk, one card, whatever it found. |

The layers were a way to pass values between trees. Inside one tree there is
nothing to pass.

## 4. What was built

`mango_unified`, the tree in `mango-unified-tree.md`, built into an API body by
`scripts/build_mango_unified.py`:

- **74 nodes**, 11 checks.
- **14 findings** registered instead of 14 cards opened.
- **11 combination rules**, 9 from that document and 2 added here (section 6).
- **45 parameters**, one naming convention, tunable per tenant in one place.
- Compiles clean against `folding_compiler.check_folding_tree`: 0 errors.

### What it absorbs

| PDF layer | Old trees | Where they are now |
| --- | --- | --- |
| Layer 1, S1 | `t_ndvi_canopy_vigour`, `t_evi_…`, `t_savi_…`, `t_msavi_…`, `t_gndvi_chlorophyll`, `mango_canopy_health_v1` | the index-selection and vigour nodes, registering `vigour_low`, `chlorophyll_low`, `block_declining` |
| Layer 1, S2 | `t_ndre_nitrogen` | the red-edge nodes, registering `nutrient_low` |
| Layer 1, S3 | `t_ndmi_leaf_water`, `t_msi_moisture_stress`, `t_cwsi_irrigation_stress`, `t_smi_soil_moisture`, `t_water_stress_confirm` | the 21 water nodes, registering `dry` on a two-of-three agreement and `dry_unconfirmed` otherwise |
| Layer 1, S4 | `t_bsi_ground_cover` | the ground-cover nodes, registering `cover_open` |
| Layer 2, D1 | `t_vigour_cause_split` | the combination rules. No cascade — each rule names a set. |
| Layer 0, Q1 | `t_size_record_check` | the size nodes, registering `size_missing` |
| Layer 3, P1–P3 | `t_anthracnose_mealybug_watch`, `t_bloom_protection`, `t_fruit_fly_harvest_readiness` | three `switch` nodes reading the live risk scores, registering `pest_high/med`, `mildew_high/med`, `fly_high/med` |

Seventeen trees become one. The four plan trees the PDF also leaves alone —
`t_deficit_irrigation_verify`, `t_flower_induction_readiness`,
`t_fruit_development_program`, `t_post_harvest_care` — stay as they are. They
schedule work; they do not diagnose. `t_young_orchard_establishment` is left out
on purpose, for the reason in section 7 of `mango-unified-tree.md`.

**23 → 5 trees**, not 23 → 13.

### Where the PDF's cascade went

D1's seven steps are not an ordered list here. Each one is a rule over a set,
so two of them can both be true and the card says both:

| PDF step | Here |
| --- | --- |
| 1. vigour normal → no action | no `vigour_low` finding, so nothing is registered and no card opens |
| 2. cover opened up | rule `{vigour_low, cover_open}` |
| 3. water and nutrient both | rule `{vigour_low, dry, nutrient_low}` |
| 4. water alone | rule `{vigour_low, dry}` |
| 5. nutrient alone | rule `{vigour_low, nutrient_low}` |
| 6. a pest score elevated | rules `{vigour_low, pest_high}` and `{vigour_low, mildew_high}` |
| 7. nothing above | rule `{vigour_low}`, which says what is known and what is not |

Steps 2 and 4 were mutually exclusive in the cascade. Here a cell that is both
dry and opening up matches `{dry, cover_open}`, which is the blocked-line case
and the more useful answer.

## 5. What this costs the farmer, measured

| Metric | 23 trees today | `mango_unified` |
| --- | --- | --- |
| Cards for one irrigation failure | up to 5, each generic | 1, naming the cause |
| Leaves ending in "water, pest or nutrient" | 11 | 0 |
| Pest pressure considered before giving up | never | every walk, as a score |
| Places to tune vigour sensitivity | 11 scattered | 1 parameter block |
| Distinct finding sets the graph can produce | — | 2,619, each folding to exactly one card |

The last row is the whole point of the fold: 11 rules and 14 clauses cover
2,619 outcomes, because an unmatched set composes its clauses into a sentence
rather than falling off the end.

## 6. The two rules added beyond `mango-unified-tree.md`

Both are in `scripts/build_mango_unified.py` under `ADDED_RULES`, with the
reason beside each.

- **`{vigour_low}` alone.** The PDF's step 7. A lone `vigour_low` otherwise
  composes to its catalogue clause and reads as a measurement with no
  instruction. The rule says what is known, says what is ruled out, and sends
  someone to look at the trunk and ask about salinity.
- **`{vigour_low, mildew_high}`.** The PDF's step 6 names the specific disease.
  This mirrors `{vigour_low, pest_high}`, which that document already carries.
  Its section 6.2 rejects `{fly_high, vigour_low}` because fruit fly and canopy
  vigour share no cause; powdery mildew shares one, because it takes the leaves
  and the panicles.

## 7. What is not settled

1. **The card cannot quote a number yet.** The tree copies `index_used`,
   `vigour_now` and `leaf_water_now` into variables for the card, and the fold
   has no stated way to read a variable back. Open in section 7 of
   `mango-unified-tree.md`.
2. **`register.severity` is a literal.** Twelve of the 74 nodes exist only to
   vary severity by tree size. A value ref there collapses them to four.
3. **Nothing runs on a schedule.** A beta tree carries `stage='beta'` and the
   sweep reads `stage='live'`. This tree produces cards only in a dry run until
   someone promotes it, which is the right place to stop before a season of
   real cards depends on it.
4. **The 17 old trees stay live until it is promoted.** Turning them off is a
   separate decision with its own evidence: an estate dry run of this tree
   beside a week of their real cards.
