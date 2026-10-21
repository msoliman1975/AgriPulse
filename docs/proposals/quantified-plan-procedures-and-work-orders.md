# Quantified plan procedures and crew work orders

**Status:** Designed, not started. **Date:** 2026-08-27.
**Extends:** `docs/proposals/plan-templates-implementation.md` and
`docs/proposals/phenology-spine-and-stage-aware-planning.md`.

The plan-template catalog is live with 17 published templates. Every template
says what to do and when. None of them says how much. This document turns a
dose written as free text into a number a crew can carry to the field, and adds
the work order that carries it.

Migration heads when written: public **0055**, tenant **0072**.

---

## 1. What exists today

| Piece | Where | State |
|---|---|---|
| `public.plan_templates` (17 rows, published) | `plan_templates/models.py` | Live |
| `public.plan_template_milestones` | same | Live |
| `public.plan_template_activities` | same | Live |
| Anchors: start, milestone, stage | `plan_templates/apply.py` | Live |
| Phenology stages per crop, variety, strain | `crops.phenology_stages` JSONB | Live |
| Daily stage advance task | `farms/phenology_advance.py` | Live |
| Apply into `vegetation_plans` and `plan_activities` | `plan_templates/service.py` | Live |
| Crew and equipment on an activity | `tenant.activity_resources` | Live |
| Assignee on an activity | `plan_activities.assigned_membership_id` | Live |
| Irrigation volume in mm, planned and applied | `tenant.irrigation_schedules` | Live, not linked to plans |

Seeded content: mango 6 cultivars at 16 activities each, potato 3 seasons at 12
each, date palm 7 cultivars at 12 each.

## 2. What is missing

1. `dosage` is free text. Nothing can multiply it by block area or sum it.
2. `product_name` is free text. No nutrient content, no active ingredient, no
   pre-harvest interval.
3. One activity holds one product name. A tank mix of three products does not
   fit. The mango micronutrient spray already needs three.
4. No repeat rule. The mango powdery-mildew note says "15-day interval" and the
   seed writes one activity.
5. No spray water volume, so a rate per 100 litres cannot become a quantity.
6. No season nutrient budget, so the FAO totals stay as comment text.
7. Completion records a timestamp and nothing else. No actual product, no
   actual quantity.

## 3. Locked decisions

| # | Decision |
|---|---|
| D1 | Depth first. Rewrite the existing 17 templates with real numbers, units, and products. No new crops until that is done. |
| D2 | Platform admin authors. Tenants apply only. No tenant copy-and-edit. |
| D3 | The output is a work order for the crew. |
| D4 | A rate is value plus unit plus basis. One number field is not enough. |
| D5 | Plant count is a stored number per block. Density per hectare is offered as a calculator that fills it in, not as the stored value. |
| D6 | Canopy diameter is a new number field next to the existing `canopy_size_class`. The class stays for the rules engine. |
| D7 | The crew reads the order on paper and in the mobile app. Both. |
| D8 | A rate range stays a range. The work order prints the low and high quantity and the crew chooses. The actual is recorded on the way back. **Narrowed 2026-08-27:** the Egyptian register carries no ranges, so a registered pesticide dose prints as one number. Ranges apply only to literature-derived rates. |
| D9 | The product catalog is the Egyptian registered list, not only the products the templates name. |

## 4. Blocker to clear first

Tenant migration `0061` dropped `plant_density_per_ha`, `row_spacing_m`, and
`plant_spacing_m` from `block_crops` on 2026-08-08. All five columns were null
in production, so nothing was lost. The replacement was the tenant-authored
crop-attribute system.

A platform template cannot depend on a tenant-authored attribute. A per-plant
rate for date palm or mango produces no number without a count owned by the
platform schema. So the count returns as a column.

## 5. Data model

### 5.1 `block_crops` additions (tenant migration off 0072)

| Column | Type | Meaning |
|---|---|---|
| `plant_count` | integer, nullable | Number of trees, palms, or plants in the block. Entered by hand. Authoritative. |
| `plant_density_per_ha` | numeric(8,2), nullable | Optional. Feeds the calculator. Not read by the resolver. |
| `canopy_diameter_m` | numeric(4,2), nullable | Average canopy diameter. Needed for paclobutrazol. |

The form offers a calculator. Enter density, press Apply, and `plant_count`
fills with density multiplied by area in hectares, rounded down. The user can
overwrite it. An orchard with gaps needs the hand count.

All three live on `BlockCrop`, not `Block`. They belong to the current planting
and reset on replant, like `planting_date` and `canopy_size_class`.

### 5.2 `public.input_products` — the product catalog

Platform-curated, same pattern as crops and plan templates.

| Column | Notes |
|---|---|
| `id`, `code` (unique), `name_en`, `name_ar` | Identity |
| `category` | fertilizer, pesticide, growth_regulator, amendment, pollen, other |
| `form` | solid, liquid, wettable_powder, granule, gas |
| `n_pct`, `p2o5_pct`, `k2o_pct` | Fertilizer nutrient content. Nullable |
| `micronutrients` | JSONB, for Zn, Fe, B, Mn |
| `cas_no` | Chemical Abstracts number, from the register |
| `manufacturer`, `country_of_origin` | From the register |
| `who_class` | WHO hazard class, for example Low III or Mod II |
| `apc_product_id` | The register's internal id, so a refresh can match rows |
| `pesticide_class` | fungicide, insecticide, acaricide, herbicide, nematicide |
| `target_pests` | Text array |
| `phi_days` | Pre-harvest interval in days |
| `rei_hours` | Re-entry interval in hours |
| `max_applications_per_season` | Integer, nullable |
| `country_code`, `registration_status`, `registration_ref` | registered, withdrawn, unregistered |
| `status` | draft, published, archived |

New capability: `input_product.manage`, platform only.

**`public.input_product_actives` — one row per active ingredient.** 198 of the
631 registered products for our three crops carry two active ingredients, for
example Ridomil Gold MZ at metalaxyl 4 percent plus mancozeb 64 percent. So the
active ingredient cannot be a column on the product.

| Column | Notes |
|---|---|
| `product_id` | Cascade on delete |
| `active_ingredient` | For example Metalaxyl |
| `concentration_pct` | Nullable. The register gives one combined figure on 26 products |
| `sort_order` | |

**`public.input_product_uses` — the crop and pest a product is approved for.**
This is the register's own recommendation row, and it is what makes a template
activity checkable against the law.

| Column | Notes |
|---|---|
| `product_id` | Cascade on delete |
| `crop_path` | Mapped from the register's crop id |
| `pest` | For example Anthracnose |
| `rate_value`, `rate_unit`, `rate_basis` | Parsed from the register's rate string |
| `phi_days` | Nullable. `N/A` in the register means no interval applies |
| `growth_stage_restriction` | The register's crop description. Filled on 35 of 656 rows |
| `source_note` | For example "APC register, pulled 2026-08-27" |

### 5.3 `public.plan_template_activity_inputs` — many products per activity

| Column | Notes |
|---|---|
| `activity_id` | Cascade on delete |
| `product_id` | Nullable. Null means the activity names a product with no catalog row |
| `product_name_free` | Used when `product_id` is null |
| `rate_value_min`, `rate_value_max` | `max` may equal `min` for a single value |
| `rate_unit` | kg, g, L, mL, m3, piece |
| `rate_basis` | per_ha, per_plant, per_100L, per_m_canopy, per_block |
| `sort_order`, `note` | |

A tank mix is several rows on one activity. The mango zinc plus iron plus boron
spray becomes three rows.

### 5.4 `plan_template_activities` — new columns

| Column | Notes |
|---|---|
| `method` | soil_drench, foliar_spray, fertigation, broadcast, band, hand, mechanical |
| `water_volume_value`, `water_volume_basis` | Litres of spray water. Basis is per_ha or per_plant. Required when any input uses `per_100L` |
| `repeat_interval_days` | Nullable. Days between repeats |
| `repeat_count` | Nullable. How many times in total, counting the first |
| `repeat_until_stage_code` | Nullable. Alternative to `repeat_count` |
| `labour_hours_value`, `labour_hours_basis` | Basis is per_ha, per_plant, or per_block |

`repeat_count` and `repeat_until_stage_code` are mutually exclusive. A check
constraint enforces that, and enforces that a repeat needs an interval.

### 5.5 `public.plan_template_nutrient_budgets` — the publish check

| Column | Notes |
|---|---|
| `template_id`, `nutrient` | N, P2O5, K2O |
| `total_value`, `unit`, `basis` | For example 360, kg, per_ha |
| `source_note` | For example "FAO fertilizer use by crop in Egypt, mango over 10 years" |

At publish, the system sums the nutrient contribution of every fertilizer input
in the template, converts it to the budget basis, and compares it to the total.
A difference above 10 percent shows a warning to the platform admin. It does
not block publishing. An agronomist may have a reason.

### 5.6 `tenant.plan_activity_inputs` — planned and actual side by side

Written by the apply engine. One row per template input per created activity.

| Column | Notes |
|---|---|
| `plan_activity_id` | Cascade on delete |
| `product_id`, `product_name_snapshot` | The name is copied so a later catalog rename does not rewrite history |
| `rate_value_min`, `rate_value_max`, `rate_unit`, `rate_basis` | Copied from the template |
| `planned_quantity_min`, `planned_quantity_max`, `planned_unit` | The resolved numbers for this block |
| `resolve_status`, `resolve_reason` | resolved or unresolved, with a reason such as `missing_plant_count` |
| `actual_quantity`, `actual_unit`, `actual_note` | Written when the crew reports back |

Planned and actual in one row is what lets a report compare the plan to what
happened, and what an export audit asks for.

### 5.7 `tenant.work_orders` and `tenant.work_order_items`

A crew does not go out for one block. It goes out for one day, one operation,
several blocks.

`work_orders`

| Column | Notes |
|---|---|
| `id`, `farm_id` | |
| `reference` | Human number such as WO-2026-0142, unique per tenant |
| `scheduled_date` | |
| `operation` | The activity type shared by every item |
| `status` | draft, issued, in_progress, completed, cancelled |
| `assigned_membership_id` | |
| `issued_at`, `issued_by` | |
| `completed_at`, `completed_by` | |
| `notes` | |

`work_order_items`

| Column | Notes |
|---|---|
| `work_order_id`, `plan_activity_id`, `block_id` | |
| `sequence` | Print order |
| `snapshot` | JSONB. Resolved quantities, product names, safety numbers, block area, and plant count, frozen at issue |
| `status`, `completed_at` | Per block, because a crew can finish 3 of 5 blocks |

**Snapshot at issue.** When the status moves from draft to issued, the server
copies the numbers into `snapshot`. A later edit to the template or the
activity does not change an issued order. An order that changes after the crew
signed it is not a record.

New capabilities: `work_order.read`, `work_order.manage` for create, issue, and
cancel, and `work_order.execute` for marking items complete and writing
actuals. FarmManager and Agronomist get manage. Scout and Worker get execute.

## 6. The quantity resolver

A pure function next to `plan_templates/apply.py`, so the arithmetic is unit
tested without a database. Same shape as the existing resolver. It returns
resolved rows and a list of skipped rows with a reason.

```
quantity = rate_value * factor
```

| `rate_basis` | factor | Needs |
|---|---|---|
| `per_block` | 1 | Nothing |
| `per_ha` | `area_m2 / 10000` | `blocks.area_m2` |
| `per_plant` | `plant_count` | `block_crops.plant_count` |
| `per_m_canopy` | `plant_count * canopy_diameter_m` | Both new fields |
| `per_100L` | `total_spray_water_L / 100` | The following formula |

```
total_spray_water_L = water_volume_value * (area_ha if the water basis is
                                            per_ha else plant_count)
```

Both ends of the range go through the same formula, giving a minimum and a
maximum quantity.

**Unresolved cases and their reasons.** `missing_plant_count`,
`missing_canopy_diameter`, `missing_water_volume`, `missing_area`. The activity
is still created. Its input row carries `resolve_status = 'unresolved'` and the
reason. The board and the work order show the rate and a warning instead of a
quantity, so a gap is visible rather than absent.

**Units on display.** Store the authored unit. Convert only for display. Grams
above 1000 show as kilograms, millilitres above 1000 show as litres. Area shows
in hectares and feddan side by side. Store hectares. A stored feddan number is
wrong the moment someone reads it as hectares.

## 7. The repeat rule

The apply engine expands one template activity with a repeat into several
`plan_activities`.

- The first date comes from the anchor, as today.
- Each following date is the previous date plus `repeat_interval_days`.
- Stop after `repeat_count` rows, or when the date passes the end of the stage
  named by `repeat_until_stage_code`.
- A hard cap of 24 rows per template activity stops an authoring mistake from
  filling the board.
- Each row keeps `template_activity_id`, so re-apply still finds and replaces
  them all. Add `repeat_index` on `plan_activities` so the board can show
  "spray 2 of 5".

Check at publish. If a product carries `max_applications_per_season` and the
expanded count for that product across the template is higher, show a warning.

## 8. The work order

### 8.1 Generation

Two ways in.

1. **Automatic grouping.** Same farm, same scheduled date, same activity type,
   same assignee becomes one draft order. Run on request from the board, not on
   a schedule.
2. **By hand.** Select cells on the board and choose Create work order.

### 8.2 What the sheet says

Header: farm name, order reference, date, crew name, operation, method.

One section per block.

- Block code and name. Area in hectares and feddan. Plant count.
- Product lines. For each one: product name in Arabic and English, planned
  quantity as a range, the rate it came from, and the unit. For example, urea
  46 percent N, 110 to 121 kg, from 45 to 50 kg per feddan on 2.42 ha.
- Spray water total in litres, when the operation is a spray.
- Safety line: pre-harvest interval in days, re-entry hours, and the earliest
  safe harvest date, which is the application date plus `phi_days`.
- Equipment from `activity_resources`.
- Blank fields: actual quantity per product, start time, end time, operator
  name, signature.

Printed in Arabic, right to left. Two known traps apply. No Latin-only font
stack carries Arabic, and `letter-spacing` breaks Arabic letter joining.

### 8.3 Pre-harvest interval check

When an order is issued, compare the application date plus `phi_days` against
the date of the nearest later `harvesting` activity on the same block in the
same plan. If harvest falls inside the interval, show a warning at issue time.
This is the check that stops a rejected export shipment.

### 8.4 Mobile screen

A Work screen next to the existing Visits screen. The assignee sees issued
orders for today, opens one, sees the block list with quantities, writes the
actual quantity per block, then marks the item complete. Completing the last
item completes the order and marks the linked `plan_activities` complete.

The mobile app ships as an APK and has no continuous integration. Plan the
release the same way as the scouting screens.

## 9. Product catalog scope and sourcing

**Pulled 2026-08-27.** The register is an online database, not a document. The
extract, the puller, and the field notes are in `docs/research/`.

The Agricultural Pesticide Committee holds 5,084 products across 123 crops and
409 active ingredients. Filtered to our three crops:

| Crop | Registered products | Approved crop-and-pest rows |
|---|---|---|
| Potato | 528 | 608 |
| Mango | 100 | 120 |
| Date palm | 9 | 24 |
| Dates (stored fruit) | 1 | 1 |

731 rows in total, of which 656 are on a product that is still registered.

**What the register settles.**

- Pesticide doses are written per 100 litres of spray water (421 rows) or per
  feddan (195 rows). None is per plant or per hectare. Two extra bases appear:
  per ton of seed or tuber (10 rows) and per cubic metre for store fumigation
  (2 rows).
- No dose is a range. All 656 are single numbers.
- Every row carries a pre-harvest interval. 30 distinct values. The most common
  are 7 days (264 rows), 10 days (93), 60 days (66), and 90 days (52). 19 rows
  read `N/A`, which is biologicals and fumigants.
- 198 of the 631 registered products carry two active ingredients.

**What the register does not hold.** The spray programme: how many sprays, at
what interval, in what order. Maximum applications per season. Re-entry
interval. Arabic trade names. Those come from the product label and from the
2025 edition of the approved recommendations book for agricultural pest
control, published by the same committee in October 2025.

**Fertilizers are not in any public register.** They fall under Ministerial
Decree 84 of 2023, but no searchable database exists. Nutrient content is
chemistry, so about 15 fertilizer rows are seeded from the compound itself.

**Seed order.** Load the 631 registered products with their actives and their
approved uses. Add the 15 fertilizers, the growth regulators, and date pollen
by hand. Products whose registration was not renewed load with
`registration_status = 'withdrawn'` so an author can see why a familiar name is
not selectable.

**The register also finds gaps in what we already seeded.** The mango leafhopper
activity in template 0040 names imidacloprid or lambda-cyhalothrin. Leafhopper
is not among the six pests registered for mango in Egypt. The registered mango
insect pests are scale insects, mealy bug, and fruit flies. Each of the 55
seeded activities needs the same check.

## 10. Rewriting the 17 templates

For each of the 55 seeded activities, in this order.

1. Split the free-text dose into one or more input rows.
2. Point each input at a Tier 1 catalog row.
3. Set value, unit, and basis. Keep the range where the source gives a range.
4. Set the method.
5. Set the spray water volume where any input is per 100 litres.
6. Turn the interval notes into repeat rules.
7. Set labour hours for hand operations: pollination, bagging, thinning,
   pruning, harvesting.
8. Add the nutrient budget rows for each template that has verified totals.
9. Keep the evidence tag, `[EG]`, `[EG-FAO]`, or `[GENERIC]`, on each input.

The three crops each test a different part of the model. Potato tests `per_ha`
and days from planting. Mango tests `per_plant`, `per_m_canopy`, and the repeat
rule. Date palm tests hand operations with labour hours and no product.

## 11. Rollout

| PR | Content | Migration |
|---|---|---|
| P1 | `block_crops` plant count, density, canopy diameter. Form fields and the density calculator. i18n. | tenant off 0072 |
| P2 | `public.input_products`, the platform catalog screen, and `input_product.manage`. | public off 0055 |
| P3 | Seed the register: 631 products, their actives, and their approved uses, plus about 20 fertilizers and regulators by hand. | public |
| P4 | `plan_template_activity_inputs`, the new activity columns, the nutrient budget table, and the authoring screen for all three. | public |
| P5 | The quantity resolver and the repeat expansion. `tenant.plan_activity_inputs`. Apply writes resolved quantities. The board shows them. | tenant |
| P6 | Rewrite the 17 templates. | public |
| P7 | `work_orders`, `work_order_items`, capabilities, grouping, and the API. | tenant |
| P8 | The printable sheet in Arabic and English, with the pre-harvest interval check. | none |
| P9 | The mobile Work screen and the write-back of actual quantities. | none |

P1, P2, and P3 can run in parallel. P4 needs P2. P5 needs P4 and P1. P6 needs
P3 and P4. P7 needs P5.

The register extract is already in `docs/research/apc-egypt-register.csv`, so
P3 no longer waits on research. Re-pull it with `docs/research/apc-harvest.ps1`
when it needs a refresh.

## 12. Open items

- **Offline on mobile.** A crew often has no signal in the field. Decide whether
  the Work screen queues its write-back or requires a connection.
- **Irrigation.** `irrigation_schedules` already holds a planned and an applied
  volume in millimetres. An irrigation activity in a plan should read from it
  rather than repeat it. Not designed here.
- **Cost.** No price field is proposed. A price per product would turn the work
  order into a cost sheet. Deferred until the quantity work is proven.
- **Stock.** No inventory. The order says what to take, not what is in the store.
- **Template versioning.** Still deferred. Apply and issue both snapshot, so an
  edit does not reach an applied plan or an issued order.
