# Mango Decision Tree Catalogue

Proposed decision trees derived from `AgriPulse_Mango_Indices_Plan_EN.xlsx`
(English version, folder `tatoo Docs/Mango indices- 28_8`).

This is a **list only**. No tree is built yet. Read it, cut or rename what you
do not want, then I build the ones you approve.

---

## 1. What the sheet contains

| Sheet | Rows | What it gives |
|---|---|---|
| Index Definitions | 12 indices | formula, meaning, general range, confidence, source |
| Values - Flowering-Fruitset | 72 | value range per index x size x productivity |
| Values - Fruit Development | 72 | same grid |
| Values - Maturity-Harvest | 72 | same grid |
| Plan - Early / Mid / Late / General | 4 x 27 activities | weekly agriculture plan per variety group |

**Index grid dimensions:** 12 indices x 3 tree sizes (Small, Medium, Big)
x 2 productivity states (Productive, Non-productive) = **72 combinations**.

**Stages are ignored, as you asked.** I checked whether that loses anything.
Of the 72 combinations, **64 hold the same value range in all three stage
sheets**. Only 8 change:

| Index | Size | Productivity | Flowering | Fruit Dev | Maturity |
|---|---|---|---|---|---|
| NDWI | Small | Productive | -0.07 to 0.00 | -0.15 to 0.00 | -0.07 to 0.00 |
| NDMI | Small | Productive | -0.07 to 0.00 | -0.15 to 0.00 | -0.07 to 0.00 |
| CWSI | Small | Productive | 0.15 - 0.35 | 0.15 - 0.35 | **0.38 - 0.63** |
| CWSI | Medium | Productive | 0.10 - 0.30 | 0.10 - 0.30 | **0.25 - 0.54** |
| CWSI | Big | Productive | 0.10 - 0.25 | 0.10 - 0.25 | **0.25 - 0.45** |
| SMI | Small | Productive | 0.31 - 0.51 | 0.35 - 0.55 | 0.27 - 0.47 |
| SMI | Medium | Productive | 0.36 - 0.56 | 0.40 - 0.60 | 0.31 - 0.51 |
| SMI | Big | Productive | 0.40 - 0.65 | 0.45 - 0.70 | 0.35 - 0.60 |

The CWSI and SMI shift is not noise. The plan sheets say growers cut irrigation
before harvest on purpose (deficit irrigation) to raise fruit sugar. So the tree
is expected to look thirsty at that time.

**Consequence for the trees.** T01 to T08 and T11 need no stage input at all.
T09 (CWSI) and T10 (SMI) need one extra yes/no input: "pre-harvest deficit
irrigation is running". That is a farm practice flag, not a phenology stage.

**Varieties.** The sheet states plainly that all 9 varieties (Crimson, Yasmeena,
Alphonso, Ewais, Osteen, Keitt, Sukkary, Zebdia, Kent) carry **identical** index
values, because no published study separates them. So every index tree is
crop-level: Mango (Mangifera indica), all varieties, no variety branch.
Variety only matters in the plan trees (Section C), where harvest timing differs.

**NDWI and NDMI are the same formula and the same numbers.** The sheet says so.
I fold them into one tree (T07) instead of two. That is why 12 indices produce
11 index trees.

---

## 2. Section A - Index band trees (T01 to T11)

One tree per index. Same shape for all of them:

- **Inputs:** the index value for the block or cell, tree size, productivity state.
- **Branching:** size, then productivity, then the value against the band.
- **Output:** one of `Below expected` / `Within expected` / `Above expected`,
  plus the agronomic reading and the confidence level the sheet gives that cell.

---

### T01 - NDVI Canopy Vigour Check

- **Checks:** whether leaf density and greenness match what a mango tree of this
  size should show.
- **Bands (10 m):** Small `0.10 - 0.22` - Medium `0.25 - 0.40` - Big `0.65 - 0.81`.
  Same for productive and non-productive.
- **Output:** `Weak canopy for size` (below) / `Normal` / `Denser than expected`.
  Below-band on a Big tree is the strongest single signal of decline.
- **Crop / variety:** Mango, all 9 varieties. No variety branch.
- **Cases covered:** 6.
- **Confidence from sheet:** Low (Small) up to Medium-High (Big).

### T02 - EVI Dense-Canopy Vigour Check

- **Checks:** the same thing as NDVI, but it keeps working on big leafy trees
  where NDVI flattens out near its ceiling.
- **Bands:** Small `0.05 - 0.14` - Medium `0.14 - 0.24` - Big `0.43 - 0.59`.
- **Output:** `Weak` / `Normal` / `Above expected`. Preferred over T01 for Big trees.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.

### T03 - SAVI Soil-Adjusted Vigour Check

- **Checks:** canopy vigour with the bare soil between trees discounted. For
  orchards where a lot of ground shows between crowns.
- **Bands:** Small `0.12 - 0.24` - Medium `0.28 - 0.42` - Big `0.54 - 0.70`.
- **Output:** `Weak` / `Normal` / `Above expected`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.

### T04 - MSAVI Young-Orchard Vigour Check

- **Checks:** the same as SAVI but the soil correction adapts by itself. The
  sheet calls it the most accurate option for very young, newly planted trees.
- **Bands:** Small `0.15 - 0.28` - Medium `0.30 - 0.44` - Big `0.56 - 0.71`.
- **Output:** `Weak` / `Normal` / `Above expected`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.
- **Note:** T01, T02, T03 and T04 all answer "is the canopy where it should be".
  You may want only one of them live per orchard, chosen by tree size, instead
  of four alerts saying the same thing. See open question Q1.

### T05 - GNDVI Chlorophyll Check

- **Checks:** chlorophyll content and leaf age. Separates old tired leaves from
  young leaves better than NDVI in later growth.
- **Bands:** Small `0.12 - 0.24` - Medium `0.30 - 0.45` - Big `0.59 - 0.73`.
- **Output:** `Low chlorophyll` / `Normal` / `High chlorophyll`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.

### T06 - NDRE Nitrogen Sufficiency Check

- **Checks:** early fertilizer shortage, mainly nitrogen, before any yellowing
  is visible to the eye.
- **Bands:** Small `0.08 - 0.18` - Medium `0.18 - 0.30` - Big `0.38 - 0.52`.
- **Output:** `Possible nitrogen shortage` / `Normal nutrition` / `High chlorophyll`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.
- **Note:** the plan sheets say nitrogen is stopped on purpose about two months
  before flowering. A low NDRE inside that window is intended, not a fault.
  Either add that as an input, or accept a false alert in one window per year.
  See open question Q3.

### T07 - NDWI / NDMI Leaf Water Check

- **Checks:** how much water is inside the leaves. One tree, two index names,
  because the sheet confirms both use the same formula and the same numbers.
- **Bands:** Small non-productive `-0.15 to 0.00` - Small productive `-0.07 to 0.00`
  - Medium `0.00 - 0.12` - Big `0.11 - 0.27`.
- **Output:** `Leaf water low` / `Normal` / `High moisture`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6 (12 sheet rows, since NDWI and NDMI duplicate).
- **Stage note:** Small + Productive is one of the 8 stage-varying cells. The
  wider `-0.15 to 0.00` band from Fruit Development is the safe choice if you
  want a single band.

### T08 - MSI Moisture Stress Check (inverted)

- **Checks:** water stress. **This index runs backwards.** A higher value means
  a thirstier tree.
- **Bands:** Small `0.90 - 1.30` - Medium `0.60 - 0.90` - Big `0.25 - 0.45`.
- **Output:** `Normal` / `Above expected stress` (value above band) /
  `Wetter than expected` (value below band).
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.
- **Warning:** the direction must be inverted in the tree definition or every
  alert fires the wrong way round.

### T09 - CWSI Irrigation Stress Check (thermal)

- **Checks:** the tree's own canopy temperature against air temperature. The
  sheet calls this the most reliable index for irrigation decisions.
- **Bands, normal irrigation:** Small `0.15 - 0.35` - Medium `0.10 - 0.30`
  - Big `0.10 - 0.25`. Applies to all non-productive trees at all times, and to
  productive trees outside the pre-harvest window.
- **Bands, pre-harvest deficit irrigation (productive trees only):**
  Small `0.38 - 0.63` - Medium `0.25 - 0.54` - Big `0.25 - 0.45`.
- **Extra input:** `deficit irrigation active` (yes / no).
- **Output:** `Adequate irrigation` / `Water stress, irrigate` /
  `Stress within the intended deficit range`.
- **Crop / variety:** Mango, all 9 varieties. Variety group changes *when* the
  deficit window falls, not the numbers.
- **Cases covered:** 6 normal + 3 deficit = 9.

### T10 - SMI Soil Moisture Check

- **Checks:** water in the soil itself, not in the plant.
- **Bands, normal:** Small non-productive `0.35 - 0.55` - Medium non-productive
  `0.40 - 0.60` - Big non-productive `0.45 - 0.70`. Productive trees sit slightly lower.
- **Bands, deficit window (productive):** Small `0.27 - 0.47` - Medium `0.31 - 0.51`
  - Big `0.35 - 0.60`.
- **Extra input:** `deficit irrigation active` (yes / no).
- **Output:** `Dry soil` / `Normal` / `Well moistened`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6 normal + 3 deficit = 9.
- **Confidence from sheet:** Medium-Low on every cell. The sheet says there is
  no single standard SMI formula. This is the weakest tree in the set.

### T11 - BSI Ground Cover Check

- **Checks:** how much bare ground shows between trees. High value means small
  or widely spaced trees; low value means good canopy cover.
- **Bands:** Small `0.35 - 0.55` - Medium `0.15 - 0.30` - Big `0.04 - 0.14`.
- **Output:** `More bare soil than expected` (above band, canopy gap or tree
  loss) / `Normal` / `Less bare soil than expected`.
- **Crop / variety:** Mango, all 9 varieties.
- **Cases covered:** 6.

---

## 3. Section B - Combination trees (T12 to T16)

These read more than one index. They exist because a single low index does not
say **why** it is low.

### T12 - Water Stress Confirmation

- **Checks:** whether the four water indices agree before an irrigation alert
  is raised. Reads NDWI/NDMI (T07), MSI (T08), CWSI (T09), SMI (T10).
- **Output:** `Confirmed water stress` (3 or 4 agree) / `Possible water stress`
  (2 agree) / `Single-index signal, not confirmed` / `No stress`.
- **Crop / variety:** Mango, all 9 varieties.
- **Why:** CWSI is High confidence, SMI is Medium-Low. Agreement between them
  is worth more than either alone.

### T13 - Vigour Loss Cause Split

- **Checks:** when canopy vigour is below band (T01 or T02), which cause fits.
  Reads NDRE, NDWI/NDMI and BSI alongside it.
- **Output:** `Nitrogen shortage` (NDRE also low, water indices normal) /
  `Water stress` (water indices low, NDRE normal) / `Canopy gap or tree loss`
  (BSI above band) / `Combined stress` / `Cause not separated`.
- **Crop / variety:** Mango, all 9 varieties.

### T14 - Young Orchard Establishment Check

- **Checks:** whether a Small-size block is filling in as it should.
  Reads MSAVI (T04), SAVI (T03) and BSI (T11) together.
- **Output:** `Establishing normally` / `Slow canopy fill` / `Gaps or losses,
  inspect on the ground`.
- **Crop / variety:** Mango, all 9 varieties. Runs on Small trees only.

### T15 - Record vs Canopy Mismatch

- **Checks:** whether the tree size recorded in the platform matches what the
  imagery shows. A block recorded as Small reading NDVI 0.70 and BSI 0.08 is a
  record error, not an agronomy event.
- **Output:** `Record matches imagery` / `Recorded size looks too small` /
  `Recorded size looks too large`.
- **Crop / variety:** Mango, all 9 varieties.
- **Why:** every tree above branches on size first. If the size field is wrong,
  all 11 index trees give wrong answers at once and nothing flags it.

### T16 - Pre-Harvest Deficit Irrigation Verification

- **Checks:** the reverse direction. For a productive block inside its harvest
  approach, confirms CWSI and SMI actually moved into the deficit range that the
  plan sheets call for.
- **Output:** `Deficit irrigation confirmed` / `Deficit not detected, irrigation
  may still be full` / `Deeper than intended, fruit at risk`.
- **Crop / variety:** Mango. **Variety group sets the timing**, so this tree
  needs the variety: Early (Sukkary, Alphonso), Mid (Ewais, Osteen, Kent),
  Late (Keitt), General (Crimson, Yasmeena, Zebdia).
- **Why:** the sheet ties the raised CWSI/SMI numbers directly to this practice.

---

## 4. Section C - Plan trees (T17 to T22), optional

These come from the four `Plan - ...` sheets, not from the index tables. The
activity list is identical in all four sheets. Only the calendar placement
differs by variety group. Say if you want these; they are a different kind of
tree (calendar and field observation, not index value).

| Variety group | Varieties | Harvest window |
|---|---|---|
| Early | Sukkary, Alphonso | late May to August |
| Mid | Ewais, Osteen, Kent | July to September |
| Late | Keitt | August to November |
| General (no source) | Crimson, Yasmeena, Zebdia | June to September (default) |

### T17 - Post-Harvest Care Window
- **Checks:** whether structural pruning, orchard sanitation and recovery
  fertilization are done in weeks 1 to 6 after harvest.
- **Output:** the due activity, or `Overdue`.
- **Variety:** all 9. Group sets the start date.

### T18 - Flower Induction Readiness
- **Checks:** the three preconditions before the 50 to 60 day dry period starts:
  vegetative flushing has stopped, nitrogen was stopped about two months out,
  potassium-only feed switched on.
- **Output:** `Ready to start dry period` / `Wait, still flushing` /
  `Stop nitrogen first`.
- **Variety:** all 9. Group sets the date.
- **Confidence from sheet:** High for the dry period itself.

### T19 - Bloom Protection
- **Checks:** powdery mildew risk during flowering plus the pollinator rule
  (no disruptive sprays at peak bloom, weeks 3 to 4).
- **Output:** `Spray sulfur, avoid pollinator hours` / `Hold, peak bloom` /
  `Monitor only`.
- **Variety:** all 9.

### T20 - Fruit Development Sprays and Thinning
- **Checks:** the KNO3 foliar sprays at about 42 and 65 days after flower
  induction, fruit thinning at pea-to-marble size, and the shift to a
  low-nitrogen potassium-rich program.
- **Output:** the due action, or `Nothing due`.
- **Variety:** all 9. The fruit development window is shorter for Early and
  longer for Late, so the day counts land on different calendar dates.

### T21 - Anthracnose and Mealybug Watch
- **Checks:** humid-condition anthracnose risk and mango mealybug presence.
- **Output:** `Inspect` / `Treat (neem, water jet, Metarhizium anisopliae)` /
  `No action`.
- **Variety:** all 9.

### T22 - Fruit Fly, Harvest Readiness and Export Treatment
- **Checks:** fruit fly trap counts (Bactrocera dorsalis), maturity cues for
  selective picking passes, and the hot water treatment requirement for export
  (46.1 C for about 73 minutes).
- **Output:** `Trap threshold exceeded` / `Ready for a picking pass` /
  `Hot water treatment required before shipment`.
- **Variety:** all 9. Group sets the harvest window.
- **Confidence from sheet:** High.

---

## 5. Coverage check

| Section | Trees | Sheet cases covered |
|---|---|---|
| A - index bands | 11 | 72 of 72 index combinations (NDMI folded into NDWI) |
| B - combinations | 5 | no new cases, they read section A outputs |
| C - plan | 6 | 27 activities x 4 variety groups |
| **Total** | **22** | |

---

## 6. Open questions for you

**Q1 - Four vigour indices, one question.** T01 NDVI, T02 EVI, T03 SAVI and
T04 MSAVI all answer "is the canopy where it should be". Running all four gives
four alerts for one problem. Options: run one per tree size (MSAVI for Small,
SAVI for Medium, EVI for Big), or run all four and fold them into one combined
output. My recommendation is one per size.

**Q2 - SMI confidence.** Every SMI cell is Medium-Low and the sheet says the
formula is not standardized. Options: build T10 anyway but never let it raise an
alert alone, or drop it. My recommendation is build it, alert only through T12.

**Q3 - Deliberate low readings.** Two practices in the plan make an index read
"bad" on purpose: the nitrogen stop before flowering (hits T06 NDRE) and the
pre-harvest deficit irrigation (hits T09 CWSI and T10 SMI). Either the trees
take a practice flag as input, or they fire a false alert once a season.

**Q4 - Small trees, Low confidence.** Most Small-tree cells are tagged Low.
The sheet also warns that ground checking is needed before these ranges drive
decisions. Do you want Small-tree outputs marked as advisory instead of alerts?

**Q5 - Section C.** Do you want the plan trees at all, or index trees only?
