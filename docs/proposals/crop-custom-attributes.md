# Crop Custom Attributes — design & implementation plan

**Status:** proposed · **Date:** 2026-08-05

Extends the crop → block assignment with a platform-curated set of typed,
per-crop attributes. Motivating case: perennial/tree crops that are not
established from seed but **transplanted as a young tree** — the assignment
must capture establishment method, transplant date, age at transplant, and
nursery/size details. The mechanism is generic; the transplant set is just
the first seeded group.

Decisions locked with the product owner:

| Question | Decision |
|---|---|
| Who authors definitions | **Platform-curated only** (public crop catalog) |
| Relationship to Custom Signals | **New mechanism** on `block_crops`; signals stay time-series |
| Value temporality | **Stored value + full append-only change history** |
| Reports | **Column picker** on block-grain reports |
| Value types | numeric (int/decimal + unit + min/max), date, single-select, multi-select, text, boolean |
| Establishment method | **Not** a first-class column — a platform-defined attribute, with `show_when` / `required_when` gating |

---

## 0. Naming

Code uses **`crop_attribute`** throughout. The UI label is "Crop fields" /
"Custom fields" (en) and the Arabic equivalent. Avoid `custom_field` in code:
the definitions are platform-curated, not tenant-custom, and `attributes` is
already the established word in this schema (`crop_varieties.attributes`,
`block_attributes` in the conditions context).

## 1. Where things live

- **Definitions** → `public` schema, alongside the crop catalog
  (`app/modules/farms`). Read-mostly, tenants only read — same contract as
  `crops` / `crop_varieties` / `crop_variety_strains`.
- **Values** → tenant schema, hanging off `block_crops`.
- **History** → tenant schema, append-only, mirrors the `growth_stage_logs`
  pattern.

No new top-level module. Everything lands in `app/modules/farms` (catalog +
assignment) with a thin read hook in `app/shared/conditions` and
`app/modules/reports`. Keeps `lint-imports` boundaries unchanged.

## 2. Definition model — `public.crop_attribute_definitions`

Attaches at any level of the taxonomy and resolves **deepest-wins by `code`**,
exactly like `size_classes` / `default_thresholds` in
`farms/crop_thresholds.resolve`:

```
crop_id            UUID  NOT NULL  -> public.crops.id            (RESTRICT)
crop_variety_id    UUID  NULL      -> public.crop_varieties.id   (RESTRICT)
crop_variety_strain_id UUID NULL   -> public.crop_variety_strains.id
```

Resolution for a block: collect every definition whose level is on the block's
`crop_path`, then for duplicate `code` the deepest level wins. A deeper row may
also set `is_active = false` to suppress an inherited attribute.

Columns:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid v7 | |
| `code` | text | stable authoring key, immutable, `^[a-z][a-z0-9_]*$` |
| `name_en` / `name_ar` | text | both required — bilingual is non-negotiable here |
| `description_en` / `description_ar` | text null | helper text under the input |
| `value_type` | text | `integer` \| `decimal` \| `text` \| `boolean` \| `date` \| `single_select` \| `multi_select` |
| `unit_en` / `unit_ar` | text null | numeric only; e.g. `months` / `شهر` |
| `value_min` / `value_max` | numeric(14,4) null | numeric only |
| `decimal_places` | int null | `decimal` only, default 2 |
| `text_max_length` | int null | `text` only, default 500 |
| `options` | jsonb null | select types: `[{code, name_en, name_ar, sort_order}]` |
| `is_required` | bool | unconditional requiredness |
| `required_when` | jsonb null | `{"code": "establishment_method", "in": ["transplanted_tree","grafted_tree"]}` |
| `show_when` | jsonb null | same shape; controls form visibility |
| `group_code` | text null | form sectioning, e.g. `establishment` |
| `group_name_en` / `group_name_ar` | text null | |
| `sort_order` | int | |
| `is_reportable` | bool | offered in the report column picker |
| `is_active` | bool | |

CHECK constraints (fail loudly at authoring time, not at render time):
- `options` non-null and non-empty **iff** `value_type IN ('single_select','multi_select')`
- `value_min`/`value_max`/`decimal_places`/`unit_*` null unless numeric
- `value_min <= value_max`
- `text_max_length` null unless `value_type = 'text'`

**Reserved codes.** `block_crops` already carries `planting_date`,
`plant_density_per_ha`, `row_spacing_m`, `plant_spacing_m`,
`canopy_size_class`, `growth_stage`, `season_label`, `status`, and the
conditions context exposes `crop_category`, `crop_path`, `crop_strain`,
`soil_texture`, `salinity_class`. A definition using any of these codes is
rejected — otherwise a platform admin can silently shadow a first-class block
field in the decision-tree builder. Enforced in the service **and** by a
CI-visible unit test over the constant list.

### `required_when` / `show_when` evaluation

Deliberately one level deep and non-recursive: `{code, in: [...]}` or
`{code, eq: <v>}`, referencing another attribute **on the same block_crop**.
No chains, no boolean groups. This is enough for the establishment case
(`transplant_date` shown only when method ∈ transplanted/grafted) and avoids
building a second rules engine. Cycles are impossible because the referenced
attribute must have a lower `sort_order` — validated on write.

If a field is hidden by `show_when`, its stored value is **cleared** on save
(with a history entry, `change_kind = 'cleared_by_gate'`) so a stale
`transplant_date` cannot survive a switch back to `seed`.

## 3. Value storage — tenant schema

### `block_crop_attribute_values`

```
id                 uuid v7 PK
block_crop_id      uuid NOT NULL -> block_crops.id  ON DELETE CASCADE
definition_id      uuid NOT NULL     -- logical cross-schema ref (no FK; matches crop_id precedent)
definition_code    text NOT NULL     -- denormalized, like block_crops.crop_path
value_numeric      numeric(14,4) NULL
value_text         text NULL
value_boolean      boolean NULL
value_date         date NULL
value_option       text NULL         -- single_select option code
value_options      text[] NULL       -- multi_select option codes
updated_by         uuid NOT NULL
created_at / updated_at
UNIQUE (block_crop_id, definition_id)
CHECK (exactly one value_* column is non-null)
```

**Typed columns, not a JSONB blob on `block_crops`.** Two reasons, both
learned the hard way in this repo:
1. The report column picker and the decision-tree evaluator both need
   type-correct, indexable reads. JSONB forces `CAST(... AS ...)` on every
   comparison — the `CAST + string bind` family caused three production
   outages in one day (#331/#332/#335).
2. History rows need a stable shape to diff against.

This mirrors `signal_observations`, which already proved the pattern.

Index: `(definition_code, value_option)` and `(definition_code, value_numeric)`
partial indexes for the report/DT filter paths.

### `block_crop_attribute_value_log`

Append-only, same typed value columns, plus:

```
changed_at    timestamptz NOT NULL DEFAULT now()
changed_by    uuid NOT NULL
change_kind   text NOT NULL  -- 'set' | 'updated' | 'cleared' | 'cleared_by_gate'
prev_*        -- previous value columns, so a row is self-describing
```

Written by the **service** in the same transaction as the value write (not a
DB trigger) — a trigger has no access to `changed_by`. This is what makes
"value as of date" possible in reports.

## 4. API surface

**Platform authoring** (platform-admin capability, mirrors `/platform/*`):
- `GET|POST /api/platform/crops/{crop_id}/attribute-definitions`
- `PATCH|DELETE /api/platform/crop-attribute-definitions/{id}`
- Delete is soft (`is_active = false`) when any tenant holds a value; a
  `CropAttributeDefinitionInUseError` mirrors `SignalDefinitionInUseError`.
  Note: "in use" spans tenant schemas, so this needs the cross-tenant loop
  pattern **with a SAVEPOINT per tenant** — a bare `try/except/continue`
  around a tenant-schema query still 500s on an aborted transaction.

**Tenant read/write:**
- `GET /api/crops/{crop_id}/attribute-definitions?crop_path=mango.alphonso.short`
  → resolved, ordered definition list (public catalog read, cacheable)
- `PUT /api/farms/{farm_id}/blocks/{block_id}/block-crops/{id}/attributes`
  → bulk upsert of all values for the assignment; validates against the
  resolved definitions (type, range, option membership, requiredness after
  gate evaluation). Partial writes rejected — one atomic save per form.
- `GET .../attributes/history?code=...`

**Embedding.** The existing block-crop read responses gain
`attributes: [{code, name_en, name_ar, value_type, unit_en, value, ...}]`.
Loaded with a **single batched query per farm**, keyed by `block_crop_id` —
the map already died once on an N+1 that exhausted the connection pool (#311).
Definitions are fetched once per crop_path per request, not per block.

**Capabilities:** value writes reuse `block.update_metadata`; definition CRUD
uses the platform-admin gate. No new capability codes needed for v1.

## 5. Decision trees

New, ninth `ValueRef` source:

```yaml
{ source: crop_attribute, code: age_at_transplant_months, key: value }
```

- `CROP_ATTRIBUTE_KEYS = ("value",)` in `app/shared/conditions/context.py`.
- `CropAttributeValueRef` in `app/shared/conditions/models.py` + a branch in
  `_validate_ref`.
- Context load: one query per block resolving the **current** `block_crop`'s
  attribute values into `{code: python_value}`, typed by the definition
  (`integer`→int, `decimal`→Decimal, `date`→date, selects→str/list[str]).
- **Fails closed** — missing definition, missing value, or no current crop
  assignment all resolve to `None`, matching every other source.
- `multi_select` resolves to a list: only `in` and `eq`/`ne` are meaningful.
  The builder restricts the op list accordingly.

### The frontend lock-step problem (do not skip)

`frontend/src/modules/decisionTrees/lib/conditionEdit.ts` hardcodes every
source's key list as a closed array. Crop attributes are the **first dynamic
source** — the code list depends on the crop catalog. So:

1. Add `GET /api/crops/attribute-definitions` (all active, across crops, with
   `crop_path` on each) for the condition builder to populate its dropdown.
2. The builder derives the op set and the value widget from `value_type`, and
   renders select options from `options` — no free-text code entry.
3. Add `crop_attribute` to the static `ValueRefSource` union in
   `conditionEdit.ts` **in the same PR**, and extend the lock-step test added
   by #345 to assert the frontend source union equals the backend `Literal`
   union. Drift here does not error — it silently downgrades the visual
   builder to a read-only YAML blob.

### Targeting warning

A tree targeted at `crop_paths: [mango]` that references an attribute defined
only for `citrus` will evaluate to `None` forever, silently. The tree
validator emits an **authoring-time warning** (not a hard error — a tree may
legitimately target multiple paths) listing referenced attribute codes that
are not resolvable for any target path.

## 6. Reports

Block-grain reports get an opt-in column picker. Order of delivery:
`crop_health` first (`CropHealthBlockRow`), then `zone_anomaly`,
`water_balance`, `weather_risk_pressure`. `weather_summary` and
`operations_log` have the wrong grain and are untouched.

- Query param `attribute_codes=a,b,c` (only `is_reportable` definitions).
- Row gains `attributes: {code: value}`.
- Response gains `attribute_columns: [{code, name_en, name_ar, value_type,
  unit_en, unit_ar}]` so the frontend renders headers without a second call.
- **As-of semantics:** reports carry a period; values resolve as of the period
  `until` date using the history log (latest log row at or before `until`,
  falling back to the current value when no log row precedes the period). This
  is the concrete payoff of choosing full history.
- CSV and print-PDF export include the selected columns.
- Frontend: an **"Additional columns" dropdown menu** in the report toolbar —
  a button showing the selected count, opening a popover list of checkbox rows
  (one per reportable attribute: label, unit, `code`, value type) with
  All / None shortcuts. Not inline chips: the reportable set grows per crop and
  a chip row would wrap unboundedly across the toolbar. Selection persists in
  the URL query so a report link round-trips.

## 7. UI

**Farm Console** (`/labs/map`) → block → crop assignment drawer: an
**Attributes** section below the existing crop fields, grouped by
`group_code`, ordered by `sort_order`, one widget per `value_type`, honoring
`show_when` / `required_when` live. Bilingual labels and units, RTL-safe
(units must sit on the correct side in Arabic). A per-attribute "history"
popover reads the change log.

**Platform portal** → `/platform/crops/{crop}/attributes`: definition CRUD
with a live preview of the resulting assignment form, so an admin can see the
gating behave before saving.

Both surfaces follow the DS-1..DS-11 standard page pattern (#340) — the design
system components, lint is at `error` for raw elements.

## 8. Seeded attribute set (the transplant case)

Group `establishment`, attached at **crop level** for perennial crops
(`is_perennial = true`):

| code | type | notes |
|---|---|---|
| `establishment_method` | single_select | `seed`, `seedling`, `transplanted_tree`, `grafted_tree`, `rootstock`, `cutting`, `tissue_culture` |
| `transplant_date` | date | `show_when` method ∈ {transplanted_tree, grafted_tree, rootstock}; `required_when` same |
| `age_at_transplant_months` | integer | unit months, 0–600, same gate |
| `transplant_height_cm` | decimal | unit cm, 0–2000, optional |
| `transplant_trunk_diameter_cm` | decimal | unit cm, 0–500, optional |
| `nursery_source` | text | optional |
| `rootstock_type` | single_select | `show_when` method ∈ {grafted_tree, rootstock}; options are crop-specific, so this one is seeded per crop |
| `is_grafted` | boolean | optional |

Deliberately **not** seeded: anything already first-class on `block_crops`
(planting date, spacing, density, canopy size class, growth stage).

## 9. Known v1 limitation — the staleness gap

Derived/computed attributes were not selected for v1. Consequence:
`age_at_transplant_months` is a fact frozen at entry. A decision tree
**cannot** express "current tree age > 5 years" — it can only compare the
age recorded at transplant, or the age a user last edited in.

Two things keep the door open at zero cost now:
1. `transplant_date` is seeded alongside the age, so the information needed to
   derive current age is already captured.
2. A future `derived` value type (or a `days_since(<date attribute>)` key on
   the `crop_attribute` source) computes current age from `transplant_date`
   with **no data migration** — it reads columns that already exist.

Until then, "current age" must be maintained by the user; the change history
records each update. This is the one place where v1 requires manual upkeep,
and it should be stated in the field's help text.

## 10. Migrations

- **public:** next available after `origin/main` head (rebase first — the
  humidity index took a number recently). Creates
  `crop_attribute_definitions` + the seed above.
- **tenant:** next available after `0054_grid_valid_time`. Creates
  `block_crop_attribute_values` + `block_crop_attribute_value_log`.
- Public must run before tenant. The ArgoCD PreSync migrate-Job **fails
  closed** — a broken migration blocks the whole sync, and a tag rollback does
  not roll migrations back. Both migrations need a working `downgrade()` with
  convention-doubled constraint names (the migration-roundtrip CI job checks
  this).
- Register both tenant tables with the **platform purge** "no orphans" CI
  guard, or purge CI goes red.

## 11. PR breakdown

| PR | Scope |
|---|---|
| **PR-1** | public `crop_attribute_definitions` + migration + resolver (deepest-wins) + platform CRUD API + reserved-code guard + tests |
| **PR-2** | tenant value + history tables + migration + bulk upsert/read API + batched embedding in block-crop responses + purge-guard registration |
| **PR-3** | Farm Console assignment-form section + platform authoring UI + en/ar i18n + RTL check |
| **PR-4** | `crop_attribute` condition source (models/context/evaluator) + dynamic catalog endpoint + `conditionEdit.ts` + **lock-step test** + targeting warning |
| **PR-5** | Report column picker on `crop_health` (backend param + as-of resolution + CSV) and the toolbar control |
| **PR-6** | Seed migration for the establishment group; extend the picker to `zone_anomaly` / `water_balance` / `weather_risk_pressure` |

PR-1 and PR-2 are the blocking spine; PR-3/4/5 are parallelizable once PR-2
lands.
