# Mango tree merge map

Read of the 23 live mango decision trees, and where each one goes under the
merged `mango_unified` tree.

Written 2026-09-16. Companion to `mango-unified-tree.md` and to
`unified-decision-tree-engine.md`.

## How this was read

Read from production, read-only:

```
ssh root@167.233.98.216
kubectl -n agripulse exec -c postgres agripulse-pg-1 -- psql -U postgres -d agripulse
```

For each row in `public.decision_trees` whose `crop_paths` contains `mango`, the
`tree_yaml` was taken from the row's `current_version_id` in
`public.decision_tree_versions`. The text was moved as base64 and decoded to a
file, never pasted through a shell. Nothing in production was written.

All 23 trees are at version 2 or later and all are `is_active = true`.

---

## 1. The 11 single-index band checks

Every one of the 11 has the same shape: branch on
`crop_attribute.tree_size_class` (small / medium / large), compare
`indices.<code>.mean` against that size's parameter, open one card when the
reading is out of band. A block with no recorded tree size reaches a `na` leaf
and nothing is checked.

### 1.1 Bands, in the exact numbers

`floor` means the card opens when the reading is **below** the number.
`ceiling` means the card opens when the reading is **above** it. The range in
brackets is the full band the mango index guide gives at 10 m, quoted from the
parameter's own description; the parameter is the actionable edge of that band.

| Tree | Index | Direction | Small | Medium | Large |
| --- | --- | --- | --- | --- | --- |
| `t_ndvi_canopy_vigour` | NDVI | floor | 0.1 (band 0.1–0.22) | 0.25 (0.25–0.4) | 0.65 (0.65–0.81) |
| `t_evi_canopy_vigour` | EVI | floor | 0.05 (0.05–0.14) | 0.14 (0.14–0.24) | 0.43 (0.43–0.59) |
| `t_savi_canopy_vigour` | SAVI | floor | 0.12 (0.12–0.24) | 0.28 (0.28–0.42) | 0.54 (0.54–0.7) |
| `t_msavi_canopy_vigour` | MSAVI | floor | 0.15 (0.15–0.28) | 0.3 (0.3–0.44) | 0.56 (0.56–0.71) |
| `t_gndvi_chlorophyll` | GNDVI | floor | 0.12 (0.12–0.24) | 0.3 (0.3–0.45) | 0.59 (0.59–0.73) |
| `t_ndre_nitrogen` | NDRE | floor | 0.08 (0.08–0.18) | 0.18 (0.18–0.3) | 0.38 (0.38–0.52) |
| `t_ndmi_leaf_water` | NDMI | floor | -0.15 (-0.15–0.0) | 0.0 (0.0–0.12) | 0.11 (0.11–0.27) |
| `t_bsi_ground_cover` | BSI | ceiling | 0.55 (0.35–0.55) | 0.3 (0.15–0.3) | 0.14 (0.04–0.14) |
| `t_msi_moisture_stress` | MSI | ceiling | 1.3 (0.9–1.3) | 0.9 (0.6–0.9) | 0.45 (0.25–0.45) |
| `t_cwsi_irrigation_stress` | CWSI | ceiling | 0.35 (0.15–0.35) | 0.3 (0.1–0.3) | 0.25 (0.1–0.25) |
| `t_cwsi_irrigation_stress`, deficit window | CWSI | ceiling | 0.63 (0.38–0.63) | 0.54 (0.25–0.54) | 0.45 (0.25–0.45) |
| `t_smi_soil_moisture` | SMI | floor | 0.35 (0.35–0.55) | 0.4 (0.4–0.6) | 0.45 (0.45–0.7) |
| `t_smi_soil_moisture`, deficit window | SMI | floor | 0.27 (0.27–0.47) | 0.31 (0.31–0.51) | 0.35 (0.35–0.6) |

One more number, from `t_cwsi_irrigation_stress`: `saturation_guard = 0.99`. A
CWSI mean at or above this is treated as clipped at the index ceiling and
carrying no information, not as real stress. `t_water_stress_confirm` carries a
second copy of the same parameter, also `0.99`.

### 1.2 Baseline drop threshold

**None of the 11 index trees reads `baseline_deviation` at all.** Every one of
them reads `mean` only. The baseline drop lives in two other trees:

| Tree | Parameter | Default | What it reads |
| --- | --- | --- | --- |
| `mango_canopy_health_v1` | `drop_sigma` | -1.5 | SAVI on sandy soil, else NDVI, `baseline_deviation` |
| `t_vigour_cause_split` | `vigour_drop_z` | -1.0 | SAVI `baseline_deviation` |

They are the same concept under two names and two defaults. `mango_unified`
keeps one name, `vigour_drop_z`, at default -1.0. The pull request body lists
that as a changed number.

`t_vigour_cause_split` also carries `dry_z = -1.0`, `low_ndre_z = -1.0` and
`bare_soil_z = 1.0`. `t_water_stress_confirm` carries `dry_z = -1.0` and
`cwsi_hot_z = 1.0`.

### 1.3 Extra gates on three of the 11

Three of the 11 are not a plain size branch:

- `t_ndre_nitrogen` skips the check entirely when `block.growth_stage` is in
  `[pre_flowering, flowering]`. That is the deliberate nitrogen-stop window, so
  a low NDRE there is intended.
- `t_smi_soil_moisture` and `t_cwsi_irrigation_stress` swap to the deficit band
  when `crop_attribute.bearing_status = bearing` **and** `block.growth_stage` is
  in `[maturation]`.
- `t_cwsi_irrigation_stress` tests `saturation_guard` before anything else.

### 1.4 Card severity, action type and confidence

Identical across all 11 and set only by size class:

| Size | Severity | Confidence |
| --- | --- | --- |
| small | `info` | 0.4 |
| medium | `warning` | 0.55 |
| large | `warning` | 0.65 |

`t_cwsi_irrigation_stress` is the exception: `critical` at every size.

Action type by tree: `scout` for NDVI, EVI, SAVI, MSAVI, GNDVI and BSI;
`fertilize` for NDRE; `irrigate` for NDMI, MSI, CWSI and SMI.

The in-band leaf is `status: good` on all 11. The missing-size leaf is
`status: na` on all 11.

### 1.5 Card text, medium-tree leaf, both languages

The small and large leaves carry the same sentence with the size's own band
substituted, so one row per tree is enough to read the vocabulary.

**`t_ndvi_canopy_vigour`**

> EN: Canopy greenness is below the band the guide expects for this tree size.
> On a large tree this is the single strongest sign of decline. The guide's
> medium-tree band for NDVI at 10 m is 0.25 to 0.4.

> AR: اخضرار المجموع دون النطاق الذي يتوقعه الدليل لهذا الحجم. على الشجرة الكبيرة هذه أقوى علامة منفردة على التدهور. نطاق الدليل للشجرة متوسطة في NDVI عند 10 م هو من 0.25 إلى 0.4.

**`t_evi_canopy_vigour`**

> EN: EVI is below the band the guide expects for this tree size. The guide says
> EVI performs best exactly here, on dense mango canopy. The guide's medium-tree
> band for EVI at 10 m is 0.14 to 0.24.

> AR: قيمة EVI دون النطاق الذي يتوقعه الدليل لهذا الحجم. يقول الدليل إن EVI يعمل بأفضل صورة هنا تحديدًا، على مجموع المانجو الكثيف. نطاق الدليل للشجرة متوسطة في EVI عند 10 م هو من 0.14 إلى 0.24.

**`t_savi_canopy_vigour`**

> EN: SAVI is below the band the guide expects for this tree size. Because SAVI
> already discounts the soil, this is a canopy signal and not a soil-brightness
> artefact. The guide's medium-tree band for SAVI at 10 m is 0.28 to 0.42.

> AR: قيمة SAVI دون النطاق الذي يتوقعه الدليل لهذا الحجم. ولأن SAVI يخصم أثر التربة أصلًا، فهذه إشارة من المجموع لا أثر لسطوع التربة. نطاق الدليل للشجرة متوسطة في SAVI عند 10 م هو من 0.28 إلى 0.42.

**`t_msavi_canopy_vigour`**

> EN: MSAVI is below the band the guide expects for this tree size. On a young
> block this is the most trustworthy of the four greenness readings. The guide's
> medium-tree band for MSAVI at 10 m is 0.3 to 0.44.

> AR: قيمة MSAVI دون النطاق الذي يتوقعه الدليل لهذا الحجم. على قطعة حديثة هذه أوثق قراءات الاخضرار الأربع. نطاق الدليل للشجرة متوسطة في MSAVI عند 10 م هو من 0.3 إلى 0.44.

**`t_gndvi_chlorophyll`**

> EN: Leaf chlorophyll is below the band the guide expects for this tree size.
> The canopy may still look full while the leaves it carries are old or starved.
> The guide's medium-tree band for GNDVI at 10 m is 0.3 to 0.45.

> AR: الكلوروفيل دون النطاق الذي يتوقعه الدليل لهذا الحجم. قد يبدو المجموع ممتلئًا بينما أوراقه مسنّة أو جائعة. نطاق الدليل للشجرة متوسطة في GNDVI عند 10 م هو من 0.3 إلى 0.45.

**`t_ndre_nitrogen`**

> EN: NDRE is below the band the guide expects for this tree size, which points
> at a nitrogen shortage before it becomes visible. The guide's medium-tree band
> for NDRE at 10 m is 0.18 to 0.3.

> AR: قيمة NDRE دون النطاق الذي يتوقعه الدليل لهذا الحجم، ما يشير إلى نقص نيتروجين قبل أن يصبح مرئيًا. نطاق الدليل للشجرة متوسطة في NDRE عند 10 م هو من 0.18 إلى 0.3.

**`t_ndmi_leaf_water`**

> EN: Leaf water is below the band the guide expects for this tree size. The tree
> is drawing on its own reserves. The guide's medium-tree band for NDMI at 10 m
> is 0.0 to 0.12.

> AR: ماء الأوراق دون النطاق الذي يتوقعه الدليل لهذا الحجم. الشجرة تسحب من مخزونها. نطاق الدليل للشجرة متوسطة في NDMI عند 10 م هو من 0.0 إلى 0.12.

**`t_bsi_ground_cover`**

> EN: More bare ground is showing than the guide expects for this tree size.
> Either trees have been lost, or the canopy has thinned enough to open the
> ground up. The guide's medium-tree band for BSI at 10 m is 0.15 to 0.3.

> AR: التربة العارية الظاهرة أكثر مما يتوقعه الدليل لهذا الحجم. إما أن أشجارًا فُقدت، أو أن المجموع ترقّق حتى انكشفت الأرض. نطاق الدليل للشجرة متوسطة في BSI عند 10 م هو من 0.15 إلى 0.3.

**`t_msi_moisture_stress`**

> EN: MSI is above the band the guide expects for this tree size. On this index
> that means more water stress, not less. The guide's medium-tree band for MSI at
> 10 m is 0.6 to 0.9.

> AR: قيمة MSI فوق النطاق الذي يتوقعه الدليل لهذا الحجم. على هذا المؤشر يعني ذلك إجهاد ماء أكبر لا أقل. نطاق الدليل للشجرة متوسطة في MSI عند 10 م هو من 0.6 إلى 0.9.

**`t_cwsi_irrigation_stress`**

> EN: Canopy temperature says this block is under more water stress than the
> guide expects for its tree size. The guide's medium-tree band for CWSI at 10 m
> is 0.1 to 0.3.

> AR: تقول حرارة المجموع إن هذه القطعة تحت إجهاد ماء أكبر مما يتوقعه الدليل لحجم أشجارها. نطاق الدليل للشجرة متوسطة في CWSI عند 10 م هو من 0.1 إلى 0.3.

**`t_smi_soil_moisture`**

> EN: Soil moisture is below the band the guide expects for this tree size. The
> guide's medium-tree band for SMI at 10 m is 0.4 to 0.6.

> AR: رطوبة التربة دون النطاق الذي يتوقعه الدليل لهذا الحجم. نطاق الدليل للشجرة متوسطة في SMI عند 10 م هو من 0.4 إلى 0.6.

### 1.6 What the card text already asks for

Four of the 11 cards tell the reader to go and read another card. Those four
sentences are combination rules, written as prose because the engine had no way
to write them as rules:

| Tree | The sentence | Becomes |
| --- | --- | --- |
| `t_savi_canopy_vigour` | "Compare against T_BSI: if bare soil is also high, the block may have lost trees rather than weakened them." | rule `{vigour_low, cover_open}` |
| `t_gndvi_chlorophyll` | "Read this beside T_NDRE: both low points at nutrition, GNDVI alone points at leaf age." | rule `{chlorophyll_low, nutrient_low}`, and the `chlorophyll_low` clause |
| `t_msi_moisture_stress` | "Do not count this as a separate finding from T_NDMI — the two carry the same signal." | MSI dropped as a standalone signal |
| `t_smi_soil_moisture` | "Read it beside T_CWSI and T_NDMI rather than on its own." | the two-of-three water vote |

---

## 2. Coverage check — all 23 trees

### 2.1 The 11 index band checks

| # | Tree | Where its behaviour went |
| --- | --- | --- |
| 1 | `t_ndvi_canopy_vigour` | Absorbed into check **vigour**. NDVI is the index chosen when the soil is not sandy and the trees are medium or unrecorded. Registers `vigour_low`. |
| 2 | `t_evi_canopy_vigour` | Absorbed into check **vigour**. EVI is chosen on a large, dense canopy. Registers `vigour_low`. |
| 3 | `t_savi_canopy_vigour` | Absorbed into check **vigour**. SAVI is chosen on sandy soil. Registers `vigour_low`. |
| 4 | `t_msavi_canopy_vigour` | Absorbed into check **vigour**. MSAVI is chosen on a small or young tree. Registers `vigour_low`. |
| 5 | `t_gndvi_chlorophyll` | Absorbed into check **chlorophyll**, its own check with its own finding `chlorophyll_low`. Not folded into vigour, because its card says a different thing: a full canopy of old or starved leaves. |
| 6 | `t_ndre_nitrogen` | Absorbed into check **nutrient**, including the `pre_flowering` and `flowering` suppression window. Registers `nutrient_low`. |
| 7 | `t_ndmi_leaf_water` | Absorbed into check **water**, as the leaf-water vote. Registers nothing on its own. |
| 8 | `t_smi_soil_moisture` | Absorbed into check **water**, as the soil-moisture vote, with its deficit window kept. Registers nothing on its own. |
| 9 | `t_cwsi_irrigation_stress` | Absorbed into check **water**, as the canopy-temperature vote, with its deficit window and its saturation guard kept. Registers nothing on its own. |
| 10 | `t_msi_moisture_stress` | **Dropped as a standalone signal.** MSI is the same measurement as NDMI with the ratio inverted, and its own card says not to count it twice. Kept only as the leaf-water vote when NDMI has no reading. Its three ceilings carry across unchanged and are used in that stand-in path. |
| 11 | `t_bsi_ground_cover` | Absorbed into check **cover**. Registers `cover_open`. |

### 2.2 The 12 that are not index band checks

| # | Tree | Where its behaviour went |
| --- | --- | --- |
| 12 | `mango_canopy_health_v1` | Absorbed twice. Its soil branch becomes the index-selection rule at the top of `mango_unified`. Its baseline drop becomes the block-level modifier, registering `block_declining`. Its parameter name `drop_sigma` is retired in favour of `vigour_drop_z`. |
| 13 | `t_vigour_cause_split` | **Absorbed into the fold, not into a check.** The four causes it separates are what the combination rules now do, so it no longer has to be a cascade. Its `vigour_drop_z`, `dry_z`, `low_ndre_z` and `bare_soil_z` all survive as parameters; `vigour_drop_z` is the name kept for the baseline drop. |
| 14 | `t_water_stress_confirm` | **Absorbed into check water.** Its two-of-three vote, its fall back to two-of-two when CWSI is clipped, and its "one reading only, do not act yet" outcome all carry across. The one change is what each vote reads: the band for the tree size, not `baseline_deviation`. The pull request body lists that as a change. |
| 15 | `t_anthracnose_mealybug_watch` | Absorbed into check **anthracnose**, a `switch` on `weather_risk` with the same `warn_score` 40 and `high_score` 70 and the same susceptible-stage gate. Registers `pest_high` or `pest_med`. |
| 16 | `t_bloom_protection` | Absorbed into check **mildew**, same shape, same 40 and 70, same flowering gate. Registers `mildew_high` or `mildew_med`. |
| 17 | `t_fruit_fly_harvest_readiness` | Absorbed into check **fruit fly**, same 40 and 70, same bearing-and-maturation gate. Registers `fly_high` or `fly_med`. Its `leaf_harvest_routine` info card, which fires at any score once the harvest window is open, is **dropped**: it is a calendar reminder, not a finding, and it belongs with the plan trees. |
| 18 | `t_size_record_check` | **Kept as a separate tree, unchanged.** It is a data-quality rule about the recorded tree size. It has to keep running when `mango_unified` cannot run, which is the exact case it detects. |
| 19 | `t_young_orchard_establishment` | **Kept as a separate tree, unchanged.** Its two readings are the MSAVI and BSI the merged tree already takes, but its subject is the planting, not the season. Folding it in would put "count the saplings that failed to take" on the same card as "anthracnose is rising". Revisit after the merged tree has run a season. |
| 20 | `t_deficit_irrigation_verify` | **Kept as a separate tree, unchanged.** It is the only tree that reports an overshoot, that the pre-harvest water cut went too deep. `mango_unified` reads the deficit number as a floor only, so it cannot say that. |
| 21 | `t_flower_induction_readiness` | **Kept as a separate tree, unchanged.** A stage tree. It says start or hold a 50 to 60 day operation; that is not a per-cell finding. |
| 22 | `t_fruit_development_program` | **Kept as a separate tree, unchanged.** A calendar plan tree. |
| 23 | `t_post_harvest_care` | **Kept as a separate tree, unchanged.** A calendar plan tree. |

Count: 14 trees absorbed into a named check, 1 absorbed into the fold, 1 dropped
as a standalone signal and kept as a stand-in, 6 kept as separate trees, 1 leaf
inside an absorbed tree dropped with a reason. Nothing is unaccounted for.

### 2.3 What is left running after the merge

Six mango trees keep running beside `mango_unified`: `t_size_record_check`,
`t_young_orchard_establishment`, `t_deficit_irrigation_verify`,
`t_flower_induction_readiness`, `t_fruit_development_program`,
`t_post_harvest_care`.

Seventeen go on the tenant opt-out list in section 6.3 of the design document:
the 11 index trees, `mango_canopy_health_v1`, `t_vigour_cause_split`,
`t_water_stress_confirm`, `t_anthracnose_mealybug_watch`, `t_bloom_protection`
and `t_fruit_fly_harvest_readiness`.

### 2.4 Rows outside the 23

Nine `mango_*_v1` rows and one `demo_cell_low_ndvi_v1` row are `is_active =
false` in production today. They are earlier drafts the `t_` trees replaced.
They need no decision here, and they do not belong on the opt-out list, because
a tree that is inactive for every tenant does not need opting out of.

`mango_anthracnose_risk_v1`, `mango_canopy_cover_gap_v1`,
`mango_canopy_moisture_by_size_v1`, `mango_canopy_vigour_by_size_v1`,
`mango_fruit_fly_risk_v1`, `mango_post_harvest_nitrogen_v1`,
`mango_powdery_mildew_risk_v1`, `mango_stress_induction_v1`,
`demo_cell_low_ndvi_v1`.

Separately, production holds 14 further rows targeting mango whose names are
`New tree`, `probe`, `My new tree` and the like. Most have no
`current_version_id`. They are authoring scratch and are outside this merge.
