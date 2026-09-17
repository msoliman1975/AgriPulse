# The merged mango tree — `mango_unified`

Content for the unified decision tree engine. Written 2026-09-16. Not
implemented and not published to any database.

This file holds four things:

1. The tree definition, in the shape of sections 4 and 6.5 of
   `unified-decision-tree-engine.md`, at cell scope.
2. The `parameters` block, with every threshold and its default.
3. The finding catalogue rows the tree needs, with the composed clause in both
   languages.
4. The combination rules, with English, Arabic, an action type and a status.

The band numbers come from the 23 live mango trees. Where each one came from,
and where each old tree goes, is in `mango-tree-merge-map.md`.

Sessions 2, 3 and 4 use this tree as their test fixture.

---

## 1. What the engine has to support that it does not today

Three requirements come out of writing this content. Two of them are small, and
without them the tree cannot be authored at a sane size.

**1. `set` must accept a `params` value ref, not only a literal and an index
reading.** Section 4.2 says "a literal or a copy of a live reading". Every band
in this tree is keyed by tree size, so without this the size branch has to be
repeated in front of every one of the 11 checks. With it, the size branch runs
once, copies that size's whole band set into variables, and every downstream
check compares against a variable. That is the difference between 74 nodes and
roughly 180.

```yaml
n_bands_medium:
  set:
    size_class: medium
    ndvi_floor: {source: params, name: medium_ndvi_floor}
    # ... one per index
```

**2. `set` must accept a `vars` value ref.** Same reason, one level down: the
index-selection nodes copy the chosen index's reading and its baseline into
shared variable names so the band check and the baseline check are each written
once instead of four times.

**3. `register.severity` is a literal, and this tree needs it to vary by tree
size.** The 11 old trees all open at `info` on a small tree and `warning` on a
medium or large one, because the index guide grades every small-tree cell low
confidence. This tree keeps that by branching on `vars.size_class` in front of
four of the registers, which costs 12 nodes. If a later version lets
`register.severity` take a value ref, those 12 nodes collapse to 4. This is a
note, not a blocker.

Two smaller notes:

- Section 7's example rule uses `status: stressed`. That value does not exist.
  The closed list is `very_good`, `good`, `issue`, `alert`, `na`
  (`backend/app/modules/recommendations/status_codes.py:47-53`). This file uses
  the real values.
- The fold has no stated way to put a measured value on the card. This tree
  copies `index_used`, `vigour_now` and `leaf_water_now` into variables for
  exactly that purpose. Section 4.2 gives the reason for `set` but section 5
  does not say how the fold reads the variables back. Session 2 has to decide.
- Four variables are written and never read by a condition: `index_used`,
  `leaf_water_source`, `leaf_water_now` and `deficit_window`. They are there for
  the card and the trace, so a compiler check for unused variables must not flag
  them as dead. `vigour_now`, `vigour_baseline`, `vigour_floor`, `size_class`,
  the eleven band variables, `leaf_water`, `soil_water` and `canopy_temp` are
  all read by a condition.

---

## 2. Findings catalogue

Fourteen rows for `public.decision_tree_findings`. The eight the design
document's sketch named are marked with a star.

The clause is a fragment, not a sentence. It starts lower case and carries no
full stop, because the fold joins several of them into one sentence. Section 3
of this file gives the join rules.

| code | default_status | action_type |
| --- | --- | --- |
| `vigour_low` ★ | `issue` | `scout` |
| `block_declining` | `issue` | `scout` |
| `dry` ★ | `alert` | `irrigate` |
| `dry_unconfirmed` | `issue` | `scout` |
| `nutrient_low` ★ | `issue` | `fertilize` |
| `chlorophyll_low` | `issue` | `scout` |
| `cover_open` ★ | `issue` | `scout` |
| `pest_high` ★ | `alert` | `spray` |
| `pest_med` ★ | `issue` | `scout` |
| `mildew_high` ★ | `alert` | `spray` |
| `mildew_med` | `issue` | `scout` |
| `fly_high` ★ | `alert` | `harvest_window` |
| `fly_med` | `issue` | `harvest_window` |
| `size_missing` | `na` | `other` |

`other` is not in the Action Center's activity map
(`action_center/service.py:43-51`), so it falls back to `observation`. That is
what `t_size_record_check` already does for the same kind of card.

### 2.1 Names and clauses

**`vigour_low`** — Canopy vigour low / حيوية المجموع منخفضة

> clause_en: canopy vigour is below the band for this tree size
>
> clause_ar: حيوية المجموع دون النطاق المتوقع لهذا الحجم

**`block_declining`** — Block below baseline / القطعة دون خط الأساس

> clause_en: the block as a whole is below its seasonal baseline
>
> clause_ar: القطعة ككل دون خط أساسها الموسمي

This clause says *the block*, never *this cell*. Only `mean` is per cell.
`baseline_deviation` carries the block's value into every cell, so a card that
said this cell had dropped against its own history would be false. Section 7.1
of the design document is the reason.

**`dry`** — Water stress agreed / إجهاد ماء مؤكَّد

> clause_en: two of the three water readings say this cell is dry
>
> clause_ar: قراءتان من ثلاث قراءات للماء تقولان إن هذه الخلية جافة

**`dry_unconfirmed`** — One water reading only / قراءة ماء واحدة

> clause_en: one water reading says dry and the others do not
>
> clause_ar: قراءة ماء واحدة تقول جفاف والقراءتان الأخريان لا

**`nutrient_low`** — Nitrogen short / نقص نيتروجين

> clause_en: red-edge is below the band and points at a nitrogen shortage
>
> clause_ar: الحافة الحمراء دون النطاق وتشير إلى نقص نيتروجين

**`chlorophyll_low`** — Leaf chlorophyll low / كلوروفيل منخفض

> clause_en: leaf chlorophyll is below the band and the leaves may be old or starved
>
> clause_ar: الكلوروفيل دون النطاق وقد تكون الأوراق مسنّة أو جائعة

**`cover_open`** — Ground opening up / انكشاف الأرض

> clause_en: more bare ground is showing than the band allows for this tree size
>
> clause_ar: التربة العارية الظاهرة أكثر مما يسمح به نطاق هذا الحجم

**`pest_high`** — Anthracnose high / أنثراكنوز مرتفع

> clause_en: anthracnose pressure is high
>
> clause_ar: ضغط الأنثراكنوز مرتفع

**`pest_med`** — Anthracnose rising / أنثراكنوز يرتفع

> clause_en: anthracnose pressure is rising
>
> clause_ar: ضغط الأنثراكنوز يرتفع

**`mildew_high`** — Powdery mildew high / بياض دقيقي مرتفع

> clause_en: powdery mildew pressure is high while the block is in bloom
>
> clause_ar: ضغط البياض الدقيقي مرتفع والقطعة في التزهير

**`mildew_med`** — Powdery mildew rising / بياض دقيقي يرتفع

> clause_en: powdery mildew pressure is rising while the block is in bloom
>
> clause_ar: ضغط البياض الدقيقي يرتفع والقطعة في التزهير

**`fly_high`** — Fruit fly high / ذبابة فاكهة مرتفعة

> clause_en: fruit fly pressure is high on ripening fruit
>
> clause_ar: ضغط ذبابة الفاكهة مرتفع على ثمار ناضجة

**`fly_med`** — Fruit fly rising / ذبابة فاكهة ترتفع

> clause_en: fruit fly pressure is rising on ripening fruit
>
> clause_ar: ضغط ذبابة الفاكهة يرتفع على ثمار ناضجة

**`size_missing`** — Tree size not recorded / حجم الشجرة غير مسجّل

> clause_en: tree size is not recorded so no index band could be checked
>
> clause_ar: حجم الشجرة غير مسجّل فلا يوجد نطاق مؤشر يمكن فحصه

---

## 3. How the composed sentence reads

Exact matching means a third finding sends the card down the composed path. The
composed path is the main path, so its join rules are content, not plumbing.

**Order.** Findings sort by severity, `critical` first, then `warning`, then
`info`. Inside one severity they sort in the catalogue order of section 2.

**English join.** Clauses are joined with `, `, the last one gets ` and `
before it, and the sentence ends with a full stop. One clause takes no
conjunction. Two clauses take ` and ` only.

**Arabic join.** Arabic does not hold the conjunction back for the last item.
Every clause after the first is prefixed with `، و`, and the sentence ends with
`.`. Two clauses read `أ، وب.`, three read `أ، وب، وج.`

**The closing line.** After the clauses, the card adds one line naming what to
do first, taken from the highest-severity finding's action type. In English:
"Start with the irrigation." In Arabic: "ابدأ بالريّ."

### 3.1 Four sets read out loud

These are the sets a real mango block produces most often. A valve failure on a
block already carrying anthracnose weather is set 3.

**Set 1 — `{dry, vigour_low}`.** This one matches a rule, so it does not
compose. It is here for the contrast.

> EN: Water shortage is the cause of the weak canopy. Irrigate before treating
> anything else.

**Set 2 — `{vigour_low, dry, pest_high}`.** No rule matches, so it composes.
Order: `pest_high` and `dry` are critical, `vigour_low` is a warning.

> EN: Anthracnose pressure is high, two of the three water readings say this
> cell is dry, and canopy vigour is below the band for this tree size. Start
> with the spray.

> AR: ضغط الأنثراكنوز مرتفع، وقراءتان من ثلاث قراءات للماء تقولان إن هذه الخلية جافة، وحيوية المجموع دون النطاق المتوقع لهذا الحجم. ابدأ بالرشّ.

Reading it back: the sentence is long but every clause is a measurement, and
the closing line resolves the order of work. That is the right answer here — an
anthracnose spray during a water shortage is still the first job, because the
infection window closes and the irrigation fault does not.

**Set 3 — `{vigour_low, dry, nutrient_low, block_declining}`.** The rule for
`{vigour_low, dry, nutrient_low}` does not fire, because `block_declining` is a
fourth member. This is the case the design document warns about.

The first draft of the `nutrient_low` clause was "red-edge is below the band,
which points at a nitrogen shortage". Composed, that read:

> EN: ... canopy vigour is below the band for this tree size, red-edge is below
> the band, which points at a nitrogen shortage, and the block as a whole is
> below its seasonal baseline.

The clause carried its own comma, so the English sentence had two commas doing
different jobs, and the Arabic had a `و` that read as a fourth item when it was
a subclause. **That is a defect in the clause, not in the join.** The same test
applied to the other 13 clauses found two more, `chlorophyll_low` and
`size_missing`. All three are rewritten with no internal comma, and section 2.1
above carries the fixed text.
**No clause may contain a comma.** That rule belongs in the publish check, and
session 3 can write it.

With the fixed clauses the set reads:

> EN: Two of the three water readings say this cell is dry, canopy vigour is
> below the band for this tree size, red-edge is below the band and points at a
> nitrogen shortage, and the block as a whole is below its seasonal baseline.
> Start with the irrigation.

> AR: قراءتان من ثلاث قراءات للماء تقولان إن هذه الخلية جافة، وحيوية المجموع دون النطاق المتوقع لهذا الحجم، والحافة الحمراء دون النطاق وتشير إلى نقص نيتروجين، والقطعة ككل دون خط أساسها الموسمي. ابدأ بالريّ.

It is four clauses and it is long, but every clause is a measurement and the
closing line says what to do first.

**Set 4 — `{fly_med}` alone.** One clause, no conjunction.

> EN: Fruit fly pressure is rising on ripening fruit. Keep to the harvest plan.

> AR: ضغط ذبابة الفاكهة يرتفع على ثمار ناضجة. التزم بخطة الحصاد.

---

## 4. Parameters

Every threshold, with the default taken from the tree it came from. Names are
kept exactly as the old trees spell them, so a tenant override that exists today
keeps meaning the same thing, except where two trees used two names for one
concept.

### 4.1 One concept, two names

`mango_canopy_health_v1` calls the baseline drop trigger `drop_sigma` and
defaults it to -1.5. `t_vigour_cause_split` calls the same thing
`vigour_drop_z` and defaults it to -1.0.

**`mango_unified` keeps `vigour_drop_z`, at -1.0.** The name because it says
what it measures rather than which statistic it is, and it is the name the more
recent tree uses. The default because -1.0 is the value all four z-score
parameters share across both trees, so one number is easier to reason about than
two. This is a change of advice on one tree and it is listed in the pull request
body.

### 4.2 The block

```yaml
parameters:
  # --- vigour bands, four indices, three sizes ---
  small_ndvi_floor:   {type: number, default: 0.1,   min: -2.0, max: 3.0}
  medium_ndvi_floor:  {type: number, default: 0.25,  min: -2.0, max: 3.0}
  large_ndvi_floor:   {type: number, default: 0.65,  min: -2.0, max: 3.0}
  small_evi_floor:    {type: number, default: 0.05,  min: -2.0, max: 3.0}
  medium_evi_floor:   {type: number, default: 0.14,  min: -2.0, max: 3.0}
  large_evi_floor:    {type: number, default: 0.43,  min: -2.0, max: 3.0}
  small_savi_floor:   {type: number, default: 0.12,  min: -2.0, max: 3.0}
  medium_savi_floor:  {type: number, default: 0.28,  min: -2.0, max: 3.0}
  large_savi_floor:   {type: number, default: 0.54,  min: -2.0, max: 3.0}
  small_msavi_floor:  {type: number, default: 0.15,  min: -2.0, max: 3.0}
  medium_msavi_floor: {type: number, default: 0.3,   min: -2.0, max: 3.0}
  large_msavi_floor:  {type: number, default: 0.56,  min: -2.0, max: 3.0}

  # --- chlorophyll ---
  small_gndvi_floor:  {type: number, default: 0.12,  min: -2.0, max: 3.0}
  medium_gndvi_floor: {type: number, default: 0.3,   min: -2.0, max: 3.0}
  large_gndvi_floor:  {type: number, default: 0.59,  min: -2.0, max: 3.0}

  # --- nitrogen ---
  small_ndre_floor:   {type: number, default: 0.08,  min: -2.0, max: 3.0}
  medium_ndre_floor:  {type: number, default: 0.18,  min: -2.0, max: 3.0}
  large_ndre_floor:   {type: number, default: 0.38,  min: -2.0, max: 3.0}

  # --- leaf water, and the MSI stand-in ---
  small_ndmi_floor:   {type: number, default: -0.15, min: -2.0, max: 3.0}
  medium_ndmi_floor:  {type: number, default: 0.0,   min: -2.0, max: 3.0}
  large_ndmi_floor:   {type: number, default: 0.11,  min: -2.0, max: 3.0}
  small_msi_ceiling:  {type: number, default: 1.3,   min: -2.0, max: 3.0}
  medium_msi_ceiling: {type: number, default: 0.9,   min: -2.0, max: 3.0}
  large_msi_ceiling:  {type: number, default: 0.45,  min: -2.0, max: 3.0}
  ndmi_present_floor: {type: number, default: -1.0,  min: -2.0, max: 0.0}

  # --- soil moisture, normal and pre-harvest deficit ---
  small_smi_floor:          {type: number, default: 0.35, min: -2.0, max: 3.0}
  medium_smi_floor:         {type: number, default: 0.4,  min: -2.0, max: 3.0}
  large_smi_floor:          {type: number, default: 0.45, min: -2.0, max: 3.0}
  small_smi_floor_deficit:  {type: number, default: 0.27, min: -2.0, max: 3.0}
  medium_smi_floor_deficit: {type: number, default: 0.31, min: -2.0, max: 3.0}
  large_smi_floor_deficit:  {type: number, default: 0.35, min: -2.0, max: 3.0}

  # --- canopy temperature, normal and pre-harvest deficit ---
  small_cwsi_ceiling:          {type: number, default: 0.35, min: -2.0, max: 3.0}
  medium_cwsi_ceiling:         {type: number, default: 0.3,  min: -2.0, max: 3.0}
  large_cwsi_ceiling:          {type: number, default: 0.25, min: -2.0, max: 3.0}
  small_cwsi_ceiling_deficit:  {type: number, default: 0.63, min: -2.0, max: 3.0}
  medium_cwsi_ceiling_deficit: {type: number, default: 0.54, min: -2.0, max: 3.0}
  large_cwsi_ceiling_deficit:  {type: number, default: 0.45, min: -2.0, max: 3.0}
  saturation_guard:            {type: number, default: 0.99, min: 0.0,  max: 1.0}

  # --- ground cover ---
  small_bsi_ceiling:  {type: number, default: 0.55, min: -2.0, max: 3.0}
  medium_bsi_ceiling: {type: number, default: 0.3,  min: -2.0, max: 3.0}
  large_bsi_ceiling:  {type: number, default: 0.14, min: -2.0, max: 3.0}

  # --- the block-level baseline modifier ---
  vigour_drop_z: {type: number, default: -1.0, min: -6.0, max: 0.0}

  # --- weather risk score bands, shared by all three switches ---
  warn_score: {type: number, default: 40, min: 0, max: 100}
  high_score: {type: number, default: 70, min: 0, max: 100}
  score_floor: {type: number, default: 0, min: 0, max: 100}
```

Forty-five parameters. Forty-three of them are a number an old tree already
carries, under the same name and at the same default.

### 4.3 The two that are not carried across

**`ndmi_present_floor = -1.0`** is new. It is not a band. NDMI is a normalised
difference, so it is bounded at -1, and a reference that resolves to `None`
fails a comparison closed (`evaluator.py:15-18`). So
`ndmi.mean >= -1.0` is true when NDMI has a reading and false when it has none.
The engine has no `exists` operator (`evaluator.py:55`), and this is the probe
that works without adding one. It is how the tree knows to fall back to MSI.

**`score_floor = 0`** is new for the same kind of reason. It is the bottom of
the 0 to 100 weather risk scale and it separates a real low score from no score
at all, inside a `switch`. Section 5.4 below explains why that matters.

### 4.4 Parameters deliberately not carried across

| Parameter | Tree | Why not |
| --- | --- | --- |
| `drop_sigma` | `mango_canopy_health_v1` | Merged into `vigour_drop_z`. |
| `dry_z` | `t_vigour_cause_split`, `t_water_stress_confirm` | The water vote reads the size band, not the z-score. Nothing left reads it. |
| `cwsi_hot_z` | `t_water_stress_confirm` | Same. |
| `low_ndre_z` | `t_vigour_cause_split` | The nutrient check reads the NDRE size band, which `t_ndre_nitrogen` already does. |
| `bare_soil_z` | `t_vigour_cause_split` | The cover check reads the BSI size band, which `t_bsi_ground_cover` already does. |
| `flush_z` | `t_flower_induction_readiness` | That tree is kept, unchanged. |

---

## 5. The tree definition

Seventy-four nodes, eleven checks. The design document's sketch said roughly
40. The extra nodes are all structural and none of them is a decision: 14 for
the size and deficit band selection, 12 for the small-tree severity split, and
21 for the water vote, which has to be written out because the engine has no
arithmetic.

The node count, the reachability of `n_stop` from every branch, the absence of
cycles and dangling targets, the match between `registers` and the register
nodes, and the match between the declared and referenced parameters were all
checked by parsing the YAML blocks below rather than by reading them.

```yaml
code: mango_unified
name_en: Mango — one tree
name_ar: المانجو — شجرة واحدة
scope: cell
crop_path: mango
country_codes: [EG]

registers:
  - vigour_low
  - block_declining
  - dry
  - dry_unconfirmed
  - nutrient_low
  - chlorophyll_low
  - cover_open
  - pest_high
  - pest_med
  - mildew_high
  - mildew_med
  - fly_high
  - fly_med
  - size_missing

parameters: # see section 4.2

root: n_deficit_window
nodes:
```

### 5.1 Size, deficit window and the band set — 14 nodes

The pre-harvest deficit window comes first, because it changes which SMI and
CWSI numbers the whole rest of the tree compares against. It is the same gate
`t_smi_soil_moisture` and `t_cwsi_irrigation_stress` use today.

```yaml
  n_deficit_window:
    label_en: Is this a bearing block inside its pre-harvest deficit window?
    label_ar: هل هذه قطعة مثمرة داخل نافذة الريّ الناقص قبل الحصاد؟
    condition:
      tree:
        all_of:
          - {op: eq, left: {source: crop_attribute, code: bearing_status, key: value}, right: bearing}
          - {op: in, left: {source: block, field: growth_stage}, values: [maturation]}
    on_match: n_d_size_small
    on_miss: n_n_size_small

  # --- normal window ---
  n_n_size_small:
    label_en: Are the trees in the small size class?
    label_ar: هل الأشجار في فئة الحجم صغيرة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: small}
    on_match: n_bands_small
    on_miss: n_n_size_medium

  n_n_size_medium:
    label_en: Are the trees in the medium size class?
    label_ar: هل الأشجار في فئة الحجم متوسطة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: medium}
    on_match: n_bands_medium
    on_miss: n_n_size_large

  n_n_size_large:
    label_en: Are the trees in the large size class?
    label_ar: هل الأشجار في فئة الحجم كبيرة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: large}
    on_match: n_bands_large
    on_miss: n_reg_size_missing

  # --- deficit window: same three questions, different SMI and CWSI numbers ---
  n_d_size_small:
    label_en: Are the trees in the small size class?
    label_ar: هل الأشجار في فئة الحجم صغيرة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: small}
    on_match: n_bands_small_deficit
    on_miss: n_d_size_medium

  n_d_size_medium:
    label_en: Are the trees in the medium size class?
    label_ar: هل الأشجار في فئة الحجم متوسطة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: medium}
    on_match: n_bands_medium_deficit
    on_miss: n_d_size_large

  n_d_size_large:
    label_en: Are the trees in the large size class?
    label_ar: هل الأشجار في فئة الحجم كبيرة؟
    condition:
      tree: {op: eq, left: {source: crop_attribute, code: tree_size_class, key: value}, right: large}
    on_match: n_bands_large_deficit
    on_miss: n_reg_size_missing

  # --- the six band sets ---
  n_bands_small:
    label_en: Load the small-tree bands
    label_ar: حمّل نطاقات الشجرة الصغيرة
    set:
      size_class: small
      deficit_window: "no"
      ndvi_floor:   {source: params, name: small_ndvi_floor}
      evi_floor:    {source: params, name: small_evi_floor}
      savi_floor:   {source: params, name: small_savi_floor}
      msavi_floor:  {source: params, name: small_msavi_floor}
      gndvi_floor:  {source: params, name: small_gndvi_floor}
      ndre_floor:   {source: params, name: small_ndre_floor}
      ndmi_floor:   {source: params, name: small_ndmi_floor}
      msi_ceiling:  {source: params, name: small_msi_ceiling}
      smi_floor:    {source: params, name: small_smi_floor}
      cwsi_ceiling: {source: params, name: small_cwsi_ceiling}
      bsi_ceiling:  {source: params, name: small_bsi_ceiling}
    next: n_pick_sandy

  n_bands_medium:
    label_en: Load the medium-tree bands
    label_ar: حمّل نطاقات الشجرة المتوسطة
    set:
      size_class: medium
      deficit_window: "no"
      ndvi_floor:   {source: params, name: medium_ndvi_floor}
      evi_floor:    {source: params, name: medium_evi_floor}
      savi_floor:   {source: params, name: medium_savi_floor}
      msavi_floor:  {source: params, name: medium_msavi_floor}
      gndvi_floor:  {source: params, name: medium_gndvi_floor}
      ndre_floor:   {source: params, name: medium_ndre_floor}
      ndmi_floor:   {source: params, name: medium_ndmi_floor}
      msi_ceiling:  {source: params, name: medium_msi_ceiling}
      smi_floor:    {source: params, name: medium_smi_floor}
      cwsi_ceiling: {source: params, name: medium_cwsi_ceiling}
      bsi_ceiling:  {source: params, name: medium_bsi_ceiling}
    next: n_pick_sandy

  n_bands_large:
    label_en: Load the large-tree bands
    label_ar: حمّل نطاقات الشجرة الكبيرة
    set:
      size_class: large
      deficit_window: "no"
      ndvi_floor:   {source: params, name: large_ndvi_floor}
      evi_floor:    {source: params, name: large_evi_floor}
      savi_floor:   {source: params, name: large_savi_floor}
      msavi_floor:  {source: params, name: large_msavi_floor}
      gndvi_floor:  {source: params, name: large_gndvi_floor}
      ndre_floor:   {source: params, name: large_ndre_floor}
      ndmi_floor:   {source: params, name: large_ndmi_floor}
      msi_ceiling:  {source: params, name: large_msi_ceiling}
      smi_floor:    {source: params, name: large_smi_floor}
      cwsi_ceiling: {source: params, name: large_cwsi_ceiling}
      bsi_ceiling:  {source: params, name: large_bsi_ceiling}
    next: n_pick_sandy

  n_bands_small_deficit:
    label_en: Load the small-tree bands, deficit window
    label_ar: حمّل نطاقات الشجرة الصغيرة في نافذة الريّ الناقص
    set:
      size_class: small
      deficit_window: "yes"
      ndvi_floor:   {source: params, name: small_ndvi_floor}
      evi_floor:    {source: params, name: small_evi_floor}
      savi_floor:   {source: params, name: small_savi_floor}
      msavi_floor:  {source: params, name: small_msavi_floor}
      gndvi_floor:  {source: params, name: small_gndvi_floor}
      ndre_floor:   {source: params, name: small_ndre_floor}
      ndmi_floor:   {source: params, name: small_ndmi_floor}
      msi_ceiling:  {source: params, name: small_msi_ceiling}
      smi_floor:    {source: params, name: small_smi_floor_deficit}
      cwsi_ceiling: {source: params, name: small_cwsi_ceiling_deficit}
      bsi_ceiling:  {source: params, name: small_bsi_ceiling}
    next: n_pick_sandy

  n_bands_medium_deficit:
    label_en: Load the medium-tree bands, deficit window
    label_ar: حمّل نطاقات الشجرة المتوسطة في نافذة الريّ الناقص
    set:
      size_class: medium
      deficit_window: "yes"
      ndvi_floor:   {source: params, name: medium_ndvi_floor}
      evi_floor:    {source: params, name: medium_evi_floor}
      savi_floor:   {source: params, name: medium_savi_floor}
      msavi_floor:  {source: params, name: medium_msavi_floor}
      gndvi_floor:  {source: params, name: medium_gndvi_floor}
      ndre_floor:   {source: params, name: medium_ndre_floor}
      ndmi_floor:   {source: params, name: medium_ndmi_floor}
      msi_ceiling:  {source: params, name: medium_msi_ceiling}
      smi_floor:    {source: params, name: medium_smi_floor_deficit}
      cwsi_ceiling: {source: params, name: medium_cwsi_ceiling_deficit}
      bsi_ceiling:  {source: params, name: medium_bsi_ceiling}
    next: n_pick_sandy

  n_bands_large_deficit:
    label_en: Load the large-tree bands, deficit window
    label_ar: حمّل نطاقات الشجرة الكبيرة في نافذة الريّ الناقص
    set:
      size_class: large
      deficit_window: "yes"
      ndvi_floor:   {source: params, name: large_ndvi_floor}
      evi_floor:    {source: params, name: large_evi_floor}
      savi_floor:   {source: params, name: large_savi_floor}
      msavi_floor:  {source: params, name: large_msavi_floor}
      gndvi_floor:  {source: params, name: large_gndvi_floor}
      ndre_floor:   {source: params, name: large_ndre_floor}
      ndmi_floor:   {source: params, name: large_ndmi_floor}
      msi_ceiling:  {source: params, name: large_msi_ceiling}
      smi_floor:    {source: params, name: large_smi_floor_deficit}
      cwsi_ceiling: {source: params, name: large_cwsi_ceiling_deficit}
      bsi_ceiling:  {source: params, name: large_bsi_ceiling}
    next: n_pick_sandy

  n_reg_size_missing:
    label_en: Tree size is not recorded
    label_ar: حجم الشجرة غير مسجّل
    register: {code: size_missing, severity: info}
    next: n_anth_stage
```

`n_reg_size_missing` jumps past every band check to the first weather switch.
That is deliberate. All nine index checks are keyed to a size band, so with no
recorded size there is nothing to compare against, exactly as the 11 old trees
found. The three weather risk switches read no band and keep working. Today the
farmer gets eleven `na` cards and no advice; under the merged tree they get one
card that names the missing field, plus any pest finding that is real.

### 5.2 Index selection and the vigour check — 11 nodes

This is `mango_canopy_health_v1`'s soil branch extended. The order is soil
first, then size, because the soil branch is the one that already runs in
production.

Four of the five vigour indices are selectable. GNDVI is the fifth and it is
**not** in the selection, because it does not answer the same question: its own
card says a low GNDVI with a normal NDVI means old or starved leaves on a full
canopy. Making it an alternative to NDVI would lose that. It gets its own check
in section 5.3 and its own finding.

```yaml
  n_pick_sandy:
    label_en: Is the soil sandy?
    label_ar: هل التربة رملية؟
    condition:
      tree: {op: eq, left: {source: block, field: soil_texture}, right: sandy}
    on_match: n_use_savi
    on_miss: n_pick_small

  n_pick_small:
    label_en: Is this a small or young tree?
    label_ar: هل الشجرة صغيرة أو حديثة؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: small}
    on_match: n_use_msavi
    on_miss: n_pick_large

  n_pick_large:
    label_en: Is this a large, dense canopy?
    label_ar: هل المجموع كبير وكثيف؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: large}
    on_match: n_use_evi
    on_miss: n_use_ndvi

  n_use_savi:
    label_en: Use SAVI — sandy soil
    label_ar: استخدم SAVI — تربة رملية
    set:
      index_used: savi
      vigour_now:      {source: indices, index_code: savi, key: mean}
      vigour_baseline: {source: indices, index_code: savi, key: baseline_deviation}
      vigour_floor:    {source: vars, name: savi_floor}
    next: n_vigour_check

  n_use_msavi:
    label_en: Use MSAVI — small or young tree
    label_ar: استخدم MSAVI — شجرة صغيرة أو حديثة
    set:
      index_used: msavi
      vigour_now:      {source: indices, index_code: msavi, key: mean}
      vigour_baseline: {source: indices, index_code: msavi, key: baseline_deviation}
      vigour_floor:    {source: vars, name: msavi_floor}
    next: n_vigour_check

  n_use_evi:
    label_en: Use EVI — large dense canopy
    label_ar: استخدم EVI — مجموع كبير كثيف
    set:
      index_used: evi
      vigour_now:      {source: indices, index_code: evi, key: mean}
      vigour_baseline: {source: indices, index_code: evi, key: baseline_deviation}
      vigour_floor:    {source: vars, name: evi_floor}
    next: n_vigour_check

  n_use_ndvi:
    label_en: Use NDVI — the default
    label_ar: استخدم NDVI — الافتراضي
    set:
      index_used: ndvi
      vigour_now:      {source: indices, index_code: ndvi, key: mean}
      vigour_baseline: {source: indices, index_code: ndvi, key: baseline_deviation}
      vigour_floor:    {source: vars, name: ndvi_floor}
    next: n_vigour_check

  n_vigour_check:
    label_en: Is the chosen index below its band for this tree size?
    label_ar: هل المؤشر المختار دون نطاقه لهذا الحجم؟
    condition:
      tree: {op: lt, left: {source: vars, name: vigour_now}, right: {source: vars, name: vigour_floor}}
    on_match: n_vigour_sev
    on_miss: n_baseline

  n_vigour_sev:
    label_en: Is this a small tree, where the guide grades confidence low?
    label_ar: هل الشجرة صغيرة حيث يخفض الدليل الثقة؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: small}
    on_match: n_reg_vigour_info
    on_miss: n_reg_vigour_warn

  n_reg_vigour_info:
    label_en: Canopy vigour below band, small tree
    label_ar: حيوية المجموع دون النطاق، شجرة صغيرة
    register: {code: vigour_low, severity: info}
    next: n_baseline

  n_reg_vigour_warn:
    label_en: Canopy vigour below band
    label_ar: حيوية المجموع دون النطاق
    register: {code: vigour_low, severity: warning}
    next: n_baseline
```

The four `set` nodes collapse into one check node, so the band comparison is
written once. Because `vigour_baseline` is copied the same way, the block-level
baseline check below is also written once instead of four times.

### 5.3 The block-level baseline modifier — 2 nodes

```yaml
  n_baseline:
    label_en: Has the block as a whole dropped against its own seasonal baseline?
    label_ar: هل هبطت القطعة ككل دون خط أساسها الموسمي؟
    condition:
      tree: {op: le, left: {source: vars, name: vigour_baseline}, right: {source: params, name: vigour_drop_z}}
    on_match: n_reg_block_declining
    on_miss: n_water_src

  n_reg_block_declining:
    label_en: The block is below its seasonal baseline
    label_ar: القطعة دون خط أساسها الموسمي
    register: {code: block_declining, severity: info}
    next: n_water_src
```

This runs in every cell and registers the same finding in every cell of a
declining block, because `baseline_deviation` is the block's number. That is
correct and it is why the clause says *the block*. The band check above is what
tells the cells apart.

### 5.4 Water — 21 nodes

Three independent readings. `dry` registers only when two of them agree.

`leaf water` is NDMI, or MSI when NDMI has no reading for this scene. MSI is the
same measurement with the ratio inverted, so it votes in NDMI's place and never
beside it. That is what `t_msi_moisture_stress`'s own card asks for.

```yaml
  n_water_src:
    label_en: Does NDMI have a reading for this scene?
    label_ar: هل لدى NDMI قراءة في هذا المشهد؟
    condition:
      tree: {op: ge, left: {source: indices, index_code: ndmi, key: mean}, right: {source: params, name: ndmi_present_floor}}
    on_match: n_ndmi_check
    on_miss: n_msi_check

  n_ndmi_check:
    label_en: Is leaf water below its band for this tree size?
    label_ar: هل ماء الأوراق دون نطاقه لهذا الحجم؟
    condition:
      tree: {op: lt, left: {source: indices, index_code: ndmi, key: mean}, right: {source: vars, name: ndmi_floor}}
    on_match: n_set_lw_dry_ndmi
    on_miss: n_set_lw_ok_ndmi

  n_msi_check:
    label_en: NDMI is missing — is MSI above its band instead?
    label_ar: NDMI غير متاح — هل MSI فوق نطاقه بدلًا منه؟
    condition:
      tree: {op: gt, left: {source: indices, index_code: msi, key: mean}, right: {source: vars, name: msi_ceiling}}
    on_match: n_set_lw_dry_msi
    on_miss: n_set_lw_ok_msi

  n_set_lw_dry_ndmi:
    label_en: Leaf water votes dry, read from NDMI
    label_ar: صوت ماء الأوراق جفاف، من NDMI
    set:
      leaf_water: dry
      leaf_water_source: ndmi
      leaf_water_now: {source: indices, index_code: ndmi, key: mean}
    next: n_smi_check

  n_set_lw_ok_ndmi:
    label_en: Leaf water votes normal, read from NDMI
    label_ar: صوت ماء الأوراق طبيعي، من NDMI
    set:
      leaf_water: ok
      leaf_water_source: ndmi
      leaf_water_now: {source: indices, index_code: ndmi, key: mean}
    next: n_smi_check

  n_set_lw_dry_msi:
    label_en: Leaf water votes dry, read from MSI
    label_ar: صوت ماء الأوراق جفاف، من MSI
    set:
      leaf_water: dry
      leaf_water_source: msi
      leaf_water_now: {source: indices, index_code: msi, key: mean}
    next: n_smi_check

  n_set_lw_ok_msi:
    label_en: Leaf water votes normal, read from MSI
    label_ar: صوت ماء الأوراق طبيعي، من MSI
    set:
      leaf_water: ok
      leaf_water_source: msi
      leaf_water_now: {source: indices, index_code: msi, key: mean}
    next: n_smi_check

  n_smi_check:
    label_en: Is soil moisture below its band for this tree size?
    label_ar: هل رطوبة التربة دون نطاقها لهذا الحجم؟
    condition:
      tree: {op: lt, left: {source: indices, index_code: smi, key: mean}, right: {source: vars, name: smi_floor}}
    on_match: n_set_soil_dry
    on_miss: n_set_soil_ok

  n_set_soil_dry:
    label_en: Soil moisture votes dry
    label_ar: صوتت رطوبة التربة جفاف
    set: {soil_water: dry}
    next: n_cwsi_usable

  n_set_soil_ok:
    label_en: Soil moisture votes normal
    label_ar: صوتت رطوبة التربة طبيعي
    set: {soil_water: ok}
    next: n_cwsi_usable

  n_cwsi_usable:
    label_en: Is the thermal reading clipped at the index ceiling?
    label_ar: هل القراءة الحرارية ملتصقة بسقف المؤشر؟
    condition:
      tree: {op: ge, left: {source: indices, index_code: cwsi, key: mean}, right: {source: params, name: saturation_guard}}
    on_match: n_set_canopy_unreadable
    on_miss: n_cwsi_check

  n_cwsi_check:
    label_en: Is canopy temperature above its band for this tree size?
    label_ar: هل حرارة المجموع فوق نطاقها لهذا الحجم؟
    condition:
      tree: {op: gt, left: {source: indices, index_code: cwsi, key: mean}, right: {source: vars, name: cwsi_ceiling}}
    on_match: n_set_canopy_hot
    on_miss: n_set_canopy_ok

  n_set_canopy_hot:
    label_en: Canopy temperature votes dry
    label_ar: صوتت حرارة المجموع جفاف
    set: {canopy_temp: hot}
    next: n_vote_three

  n_set_canopy_ok:
    label_en: Canopy temperature votes normal
    label_ar: صوتت حرارة المجموع طبيعي
    set: {canopy_temp: ok}
    next: n_vote_three

  n_set_canopy_unreadable:
    label_en: Canopy temperature does not vote — the reading is clipped
    label_ar: لا تصوّت حرارة المجموع — القراءة ملتصقة بالسقف
    set: {canopy_temp: unreadable}
    next: n_vote_three

  n_vote_three:
    label_en: Do all three readings say dry?
    label_ar: هل تقول القراءات الثلاث جفاف؟
    condition:
      tree:
        all_of:
          - {op: eq, left: {source: vars, name: leaf_water}, right: dry}
          - {op: eq, left: {source: vars, name: soil_water}, right: dry}
          - {op: eq, left: {source: vars, name: canopy_temp}, right: hot}
    on_match: n_reg_dry_critical
    on_miss: n_vote_two

  n_vote_two:
    label_en: Do any two of the three agree?
    label_ar: هل تتفق أي قراءتين من الثلاث؟
    condition:
      tree:
        any_of:
          - all_of:
              - {op: eq, left: {source: vars, name: leaf_water}, right: dry}
              - {op: eq, left: {source: vars, name: soil_water}, right: dry}
          - all_of:
              - {op: eq, left: {source: vars, name: leaf_water}, right: dry}
              - {op: eq, left: {source: vars, name: canopy_temp}, right: hot}
          - all_of:
              - {op: eq, left: {source: vars, name: soil_water}, right: dry}
              - {op: eq, left: {source: vars, name: canopy_temp}, right: hot}
    on_match: n_reg_dry_warning
    on_miss: n_vote_one

  n_vote_one:
    label_en: Does any single reading say dry?
    label_ar: هل تقول أي قراءة منفردة جفاف؟
    condition:
      tree:
        any_of:
          - {op: eq, left: {source: vars, name: leaf_water}, right: dry}
          - {op: eq, left: {source: vars, name: soil_water}, right: dry}
          - {op: eq, left: {source: vars, name: canopy_temp}, right: hot}
    on_match: n_reg_dry_unconfirmed
    on_miss: n_ndre_stage

  n_reg_dry_critical:
    label_en: All three water readings agree
    label_ar: تتفق قراءات الماء الثلاث
    register: {code: dry, severity: critical}
    next: n_ndre_stage

  n_reg_dry_warning:
    label_en: Two of three water readings agree
    label_ar: تتفق قراءتان من ثلاث
    register: {code: dry, severity: warning}
    next: n_ndre_stage

  n_reg_dry_unconfirmed:
    label_en: One water reading only
    label_ar: قراءة ماء واحدة فقط
    register: {code: dry_unconfirmed, severity: info}
    next: n_ndre_stage
```

When the thermal reading is clipped, `canopy_temp` is `unreadable`, which is
neither `dry` nor `hot`, so the three-vote and both pairs that include it all
fail on their own. The vote falls back to leaf water and soil moisture agreeing.
That is exactly what `t_water_stress_confirm` does today, with no special case
in the vote nodes.

### 5.5 Nutrient, chlorophyll and cover — 13 nodes

```yaml
  n_ndre_stage:
    label_en: Is the block inside the deliberate nitrogen-stop window?
    label_ar: هل القطعة داخل نافذة إيقاف النيتروجين المتعمد؟
    condition:
      tree: {op: in, left: {source: block, field: growth_stage}, values: [pre_flowering, flowering]}
    on_match: n_gndvi_check
    on_miss: n_ndre_check

  n_ndre_check:
    label_en: Is red-edge below its band for this tree size?
    label_ar: هل الحافة الحمراء دون نطاقها لهذا الحجم؟
    condition:
      tree: {op: lt, left: {source: indices, index_code: ndre, key: mean}, right: {source: vars, name: ndre_floor}}
    on_match: n_nutrient_sev
    on_miss: n_gndvi_check

  n_nutrient_sev:
    label_en: Is this a small tree, where the guide grades confidence low?
    label_ar: هل الشجرة صغيرة حيث يخفض الدليل الثقة؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: small}
    on_match: n_reg_nutrient_info
    on_miss: n_reg_nutrient_warn

  n_reg_nutrient_info:
    label_en: Red-edge below band, small tree
    label_ar: الحافة الحمراء دون النطاق، شجرة صغيرة
    register: {code: nutrient_low, severity: info}
    next: n_gndvi_check

  n_reg_nutrient_warn:
    label_en: Red-edge below band
    label_ar: الحافة الحمراء دون النطاق
    register: {code: nutrient_low, severity: warning}
    next: n_gndvi_check

  n_gndvi_check:
    label_en: Is leaf chlorophyll below its band for this tree size?
    label_ar: هل الكلوروفيل دون نطاقه لهذا الحجم؟
    condition:
      tree: {op: lt, left: {source: indices, index_code: gndvi, key: mean}, right: {source: vars, name: gndvi_floor}}
    on_match: n_chlorophyll_sev
    on_miss: n_bsi_check

  n_chlorophyll_sev:
    label_en: Is this a small tree, where the guide grades confidence low?
    label_ar: هل الشجرة صغيرة حيث يخفض الدليل الثقة؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: small}
    on_match: n_reg_chlorophyll_info
    on_miss: n_reg_chlorophyll_warn

  n_reg_chlorophyll_info:
    label_en: Leaf chlorophyll below band, small tree
    label_ar: الكلوروفيل دون النطاق، شجرة صغيرة
    register: {code: chlorophyll_low, severity: info}
    next: n_bsi_check

  n_reg_chlorophyll_warn:
    label_en: Leaf chlorophyll below band
    label_ar: الكلوروفيل دون النطاق
    register: {code: chlorophyll_low, severity: warning}
    next: n_bsi_check

  n_bsi_check:
    label_en: Is more bare ground showing than the band for this tree size?
    label_ar: هل التربة العارية أكثر من نطاق هذا الحجم؟
    condition:
      tree: {op: gt, left: {source: indices, index_code: bsi, key: mean}, right: {source: vars, name: bsi_ceiling}}
    on_match: n_cover_sev
    on_miss: n_anth_stage

  n_cover_sev:
    label_en: Is this a small tree, where the guide grades confidence low?
    label_ar: هل الشجرة صغيرة حيث يخفض الدليل الثقة؟
    condition:
      tree: {op: eq, left: {source: vars, name: size_class}, right: small}
    on_match: n_reg_cover_info
    on_miss: n_reg_cover_warn

  n_reg_cover_info:
    label_en: Ground opening up, small tree
    label_ar: انكشاف الأرض، شجرة صغيرة
    register: {code: cover_open, severity: info}
    next: n_anth_stage

  n_reg_cover_warn:
    label_en: Ground opening up
    label_ar: انكشاف الأرض
    register: {code: cover_open, severity: warning}
    next: n_anth_stage
```

### 5.6 The three weather risk switches — 13 nodes

These read `weather_risk` directly. They do not read the pest trees, and they
could not: no condition source is another tree.

```yaml
  n_anth_stage:
    label_en: Is the block carrying tissue anthracnose can reach?
    label_ar: هل تحمل القطعة أنسجة يصلها الأنثراكنوز؟
    condition:
      tree:
        op: in
        left: {source: block, field: growth_stage}
        values: [flowering, fruit_set, fruit_development, maturation]
    on_match: n_anth_switch
    on_miss: n_mildew_stage

  n_anth_switch:
    label_en: How strongly do conditions favour anthracnose?
    label_ar: إلى أي حد ترجّح الظروف الأنثراكنوز؟
    switch:
      on: {source: weather_risk, risk_code: anthracnose, field: score}
      cases:
        - {ge: {source: params, name: high_score}, go: n_reg_pest_high}
        - {ge: {source: params, name: warn_score}, go: n_reg_pest_med}
        - {ge: {source: params, name: score_floor}, go: n_mildew_stage}
      default: n_mildew_stage

  n_reg_pest_high:
    label_en: Anthracnose pressure is high
    label_ar: ضغط الأنثراكنوز مرتفع
    register: {code: pest_high, severity: critical}
    next: n_mildew_stage

  n_reg_pest_med:
    label_en: Anthracnose pressure is rising
    label_ar: ضغط الأنثراكنوز يرتفع
    register: {code: pest_med, severity: warning}
    next: n_mildew_stage

  n_mildew_stage:
    label_en: Is this block flowering or setting fruit?
    label_ar: هل القطعة في التزهير أو العقد؟
    condition:
      tree: {op: in, left: {source: block, field: growth_stage}, values: [flowering, fruit_set]}
    on_match: n_mildew_switch
    on_miss: n_fly_window

  n_mildew_switch:
    label_en: How strongly do conditions favour powdery mildew?
    label_ar: إلى أي حد ترجّح الظروف البياض الدقيقي؟
    switch:
      on: {source: weather_risk, risk_code: powdery_mildew, field: score}
      cases:
        - {ge: {source: params, name: high_score}, go: n_reg_mildew_high}
        - {ge: {source: params, name: warn_score}, go: n_reg_mildew_med}
        - {ge: {source: params, name: score_floor}, go: n_fly_window}
      default: n_fly_window

  n_reg_mildew_high:
    label_en: Powdery mildew pressure is high during bloom
    label_ar: ضغط البياض الدقيقي مرتفع أثناء التزهير
    register: {code: mildew_high, severity: critical}
    next: n_fly_window

  n_reg_mildew_med:
    label_en: Powdery mildew pressure is rising during bloom
    label_ar: ضغط البياض الدقيقي يرتفع أثناء التزهير
    register: {code: mildew_med, severity: warning}
    next: n_fly_window

  n_fly_window:
    label_en: Is this a bearing block with ripening fruit on the tree?
    label_ar: هل هذه قطعة مثمرة تحمل ثمارًا ناضجة؟
    condition:
      tree:
        all_of:
          - {op: eq, left: {source: crop_attribute, code: bearing_status, key: value}, right: bearing}
          - {op: in, left: {source: block, field: growth_stage}, values: [maturation]}
    on_match: n_fly_switch
    on_miss: n_stop

  n_fly_switch:
    label_en: How strongly do conditions favour fruit fly activity?
    label_ar: إلى أي حد ترجّح الظروف نشاط ذبابة الفاكهة؟
    switch:
      on: {source: weather_risk, risk_code: fruit_fly, field: score}
      cases:
        - {ge: {source: params, name: high_score}, go: n_reg_fly_high}
        - {ge: {source: params, name: warn_score}, go: n_reg_fly_med}
        - {ge: {source: params, name: score_floor}, go: n_stop}
      default: n_stop

  n_reg_fly_high:
    label_en: Fruit fly pressure is high on ripening fruit
    label_ar: ضغط ذبابة الفاكهة مرتفع على ثمار ناضجة
    register: {code: fly_high, severity: critical}
    next: n_stop

  n_reg_fly_med:
    label_en: Fruit fly pressure is rising on ripening fruit
    label_ar: ضغط ذبابة الفاكهة يرتفع على ثمار ناضجة
    register: {code: fly_med, severity: warning}
    next: n_stop

  n_stop:
    label_en: End of the walk
    label_ar: نهاية المسار
    stop: true
```

**On the defaults.** A switch that matches no case stops the walk with an
error, so every default here is a real route, not a placeholder. Each switch
carries a third case at `score_floor`, which is 0, the bottom of the score
scale. A real score of any value lands on one of the three cases. The `default`
is therefore reached only when the score is absent, and it routes to the same
node the low case does: carry on, register nothing.

Those two are deliberately the same node, because a missing weather score and a
low weather score should both produce no advice. They are not the same event,
though, and a reader of the trace will want to tell them apart. **The node path
cannot do that, because the case taken is not a node.** Session 2 should record
the matched case index on the trace row alongside `matched_rule`. Until it
does, a missing anthracnose score looks identical to a calm week.

### 5.7 Every path reaches `stop`

Checked by hand, node by node:

- Both size chains end at either a band set or `n_reg_size_missing`.
- All six band sets go to `n_pick_sandy`. `n_reg_size_missing` goes to
  `n_anth_stage`.
- The pick chain ends at one of four `set` nodes, all of which go to
  `n_vigour_check`. Both of its branches reach `n_baseline`.
- `n_baseline` and its register both reach `n_water_src`.
- Every branch of the water section reaches `n_ndre_stage`, including all three
  vote misses.
- Nutrient, chlorophyll and cover each pass through to `n_anth_stage`.
- All three switches, their registers, their defaults and both gate misses reach
  `n_stop`.

No node has a dangling `next`, `on_match`, `on_miss`, `go` or `default`. There
is no cycle: every edge points to a node later in the order above, except the
four `set` nodes in the pick, which point forward to `n_vigour_check`.

---

## 6. Combination rules

Nine rules. Five come from the design document's sketch. Four more come from
reading the out-of-band card text of the 11 index trees, where the author had
already written the pairing as prose because there was no way to write it as a
rule. Everything else composes.

```yaml
combinations:
  - codes: [vigour_low, cover_open]
    action_type: scout
    status: issue
    text_en: >-
      Canopy vigour dropped and bare ground increased together. That pattern is
      missing trees, not a weak canopy. Count the trees on the ground before
      changing water or feed.
    text_ar: >-
      هبطت حيوية المجموع وزادت التربة العارية معًا. هذا النمط يعني أشجارًا
      مفقودة لا مجموعًا ضعيفًا. عُدّ الأشجار في الأرض قبل تغيير الماء أو السماد.

  - codes: [vigour_low, dry]
    action_type: irrigate
    status: alert
    text_en: >-
      Canopy vigour and the water readings dropped together. Water shortage is
      the cause. Irrigate before treating anything else.
    text_ar: >-
      هبطت حيوية المجموع وقراءات الماء معًا. السبب نقص ماء. اروِ القطعة قبل أي
      معالجة أخرى.

  - codes: [vigour_low, nutrient_low]
    action_type: fertilize
    status: issue
    text_en: >-
      Canopy vigour and red-edge dropped together with the water readings
      normal. Take a leaf sample and feed. Scouting can wait.
    text_ar: >-
      هبطت حيوية المجموع والحافة الحمراء معًا وقراءات الماء طبيعية. خذ عينة
      أوراق وأضف السماد. يمكن تأجيل الاستكشاف.

  - codes: [vigour_low, dry, nutrient_low]
    action_type: irrigate
    status: alert
    text_en: >-
      Water and nitrogen are both short. Irrigate first, then feed. A feed into
      dry soil does not reach the root.
    text_ar: >-
      الماء والنيتروجين ناقصان معًا. اروِ أولًا ثم أضف السماد. السماد في تربة
      جافة لا يصل إلى الجذر.

  - codes: [vigour_low, pest_high]
    action_type: spray
    status: alert
    text_en: >-
      Canopy vigour dropped while anthracnose pressure is high. Treat now. The
      infection happening this week shows up after picking, in the box.
    text_ar: >-
      هبطت حيوية المجموع وضغط الأنثراكنوز مرتفع. عالج الآن. الإصابة التي تحدث
      هذا الأسبوع تظهر بعد الجني في الصندوق.

  - codes: [chlorophyll_low, nutrient_low]
    action_type: fertilize
    status: issue
    text_en: >-
      Chlorophyll and red-edge are both below their bands. Two readings pointing
      the same way is a nutrition problem, not leaf age. Sample the leaves and
      correct the nitrogen rate.
    text_ar: >-
      الكلوروفيل والحافة الحمراء كلاهما دون نطاقه. قراءتان تشيران الاتجاه نفسه
      تعني مشكلة تغذية لا عمر أوراق. خذ عينة أوراق وصحّح معدل النيتروجين.

  - codes: [vigour_low, block_declining]
    action_type: scout
    status: issue
    text_en: >-
      This cell is below its band and the block as a whole is below its seasonal
      baseline. The decline is not confined to one cell. Walk the block, not
      just this spot.
    text_ar: >-
      هذه الخلية دون نطاقها والقطعة ككل دون خط أساسها الموسمي. التدهور لا يقتصر
      على خلية واحدة. تجوّل في القطعة كلها لا في هذه البقعة وحدها.

  - codes: [dry, cover_open]
    action_type: irrigate
    status: alert
    text_en: >-
      The cell is dry and the ground is opening up at the same time. Look for a
      blocked line or a failed emitter row before adding water to the whole
      block.
    text_ar: >-
      الخلية جافة والأرض تنكشف في الوقت نفسه. ابحث عن خط مسدود أو صف نقّاطات
      معطّل قبل زيادة الماء على القطعة كلها.

  - codes: [pest_high, mildew_high]
    action_type: spray
    status: alert
    text_en: >-
      Anthracnose and powdery mildew pressure are both high while the block is
      in bloom. One visit covers both. Spray outside peak pollinator hours —
      mango sets its crop through flies and bees, and fruit lost to a badly
      timed spray does not come back.
    text_ar: >-
      ضغط الأنثراكنوز والبياض الدقيقي مرتفع معًا والقطعة في التزهير. زيارة واحدة
      تكفي للاثنين. رُشّ خارج ساعات نشاط الملقّحات — تعقد المانجو محصولها
      بالذباب والنحل، والثمار التي تُفقد برشّ سيئ التوقيت لا تعود.
```

### 6.1 Where the four new rules come from

| Rule | Where it was already written as prose |
| --- | --- |
| `{chlorophyll_low, nutrient_low}` | `t_gndvi_chlorophyll`: "Read this beside T_NDRE: both low points at nutrition, GNDVI alone points at leaf age." |
| `{vigour_low, block_declining}` | `mango_canopy_health_v1` is this card. Without the rule its advice is lost, because under the merged tree the baseline drop is only ever one finding among several. |
| `{dry, cover_open}` | `t_ndmi_leaf_water`: "Check for a blocked line or a failed emitter row before adding water everywhere." A failed emitter row is also what opens the ground. |
| `{pest_high, mildew_high}` | `t_bloom_protection` carries the pollinator timing rule. Without this rule, a cell with both findings composes a sentence that drops the timing, which is the one thing on that card that cannot be got wrong. |

### 6.2 Pairings checked and rejected

- `{vigour_low, chlorophyll_low}` — the composed sentence already says it and
  adds nothing. `t_gndvi_chlorophyll`'s own text points at NDRE, not at vigour.
- `{fly_high, vigour_low}` — fruit fly and canopy vigour have no shared cause
  and no shared order of work. Composing is correct.
- `{dry, nutrient_low}` without `vigour_low` — possible but not seen in the old
  trees; `t_vigour_cause_split` only separates causes once vigour has dropped.
  Left to compose until there is a run to look at.
- `{dry_unconfirmed, anything}` — `dry_unconfirmed` means "do not act yet".
  A rule would turn it into advice. Composing keeps it as the hedge it is.
- `{size_missing, anything}` — `size_missing` only ever appears with the three
  weather findings, because it skips every band check. Composing reads
  correctly: "tree size is not recorded so no index band could be checked, and
  anthracnose pressure is high."

---

## 7. What still needs deciding

1. How the fold reads the variables back, so the card can quote `index_used`,
   `vigour_now` and `leaf_water_now`. Section 4.2 gives the reason for `set`
   but section 5 does not close the loop. Session 2.
2. Whether `register.severity` can take a value ref. Twelve of the 74 nodes
   exist only because it cannot. Session 2.
3. Recording the matched switch case on the trace row, so a missing weather
   score can be told from a low one. Session 2.
4. A publish check that no finding clause contains a comma. Section 3.1 found
   two that did. Session 3.
5. Whether `t_young_orchard_establishment` folds in after the merged tree has
   run a season. It reads the same MSAVI and BSI, but about the planting rather
   than the season. Left out on purpose for now.
