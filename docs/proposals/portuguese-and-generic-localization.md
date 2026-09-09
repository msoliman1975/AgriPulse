# Portuguese, and a language model that survives the next language

Status: Not started. This document is a design only. No code is written.

Written 2026-09-07. Measured against `origin/main`, not against a working tree.

## Summary

The product speaks English and Arabic. Adding Portuguese is not one feature. It
is four separate pieces of work that share one design:

1. The language list itself, which exists in four places that do not agree.
2. Authored content in the database, stored as `_en` and `_ar` column pairs.
3. The web app, which asks `i18n.language === "ar"` in 39 files.
4. The words themselves. About 5,684 strings need a Portuguese translation.

This document fixes the design for all four, so the next language after
Portuguese costs one registry entry and a translation file.

## The problem

### The language list exists four times

`backend/app/shared/i18n.py` holds `SupportedLanguage = Literal["en", "ar"]`.
Its docstring says it was written to end three copies of the list. It did not.
The file is imported by exactly one module, `app/modules/iam/router.py`. Three
hard-coded lists still stand beside it:

| File | Line | Content |
| --- | --- | --- |
| `app/shared/auth/middleware.py` | 81-83 | `if preferred_language not in ("en", "ar"): preferred_language = "en"` |
| `app/shared/auth/context.py` | 78 | `preferred_language: Literal["en", "ar"] = "en"` |
| `app/modules/tenancy/schemas.py` | 26, 56 | `default_locale: Literal["en", "ar"]` |

Adding `"pt"` to `shared/i18n.py` alone produces this result. The API accepts
`pt` and stores it on the user. The middleware then rewrites the value to `en`
on every request. No error is raised and nothing is logged. The setting looks
saved and does nothing.

Caution: fixing these four lists is the first task, and nothing else should
start before it.

### Authored content is stored one language per column

There are 37 columns ending in `_ar` across 11 modules. They follow two
different patterns, and only one of them needs to change.

**Pattern A, the catalogue.** An `x_en` column that is `NOT NULL`, and an `x_ar`
column that is nullable. The English value is the source of truth. This is
authored content: crop names, index names, decision tree text, weather index
guidance. There are 21 such pairs across 12 tables.

| Table | Schema | Fields |
| --- | --- | --- |
| `countries` | public | name |
| `crops` | public | name |
| `crop_varieties` | public | name |
| `crop_variety_strains` | public | name |
| `crop_attribute_definitions` | public | name, description, unit, group_name |
| `indices_catalog` | public | name |
| `weather_derived_signals_catalog` | public | name |
| `weather_indices_catalog` | public | name, description, relation_disease, relation_indices, relation_insect |
| `decision_trees` | public | name, description |
| `recommendations` | tenant | text |
| `decision_tree_block_verdicts` | tenant | text |
| `alerts` | tenant | diagnosis, prescription |

**Pattern B, names people type.** A base column `x` with no language tag, plus a
nullable `x_ar`. Readers use `COALESCE(NULLIF(x_ar, ''), x)`. There are 16 such
columns across 9 tables: `blocks.name_ar`, `farms.name_ar`,
`farms.description_ar`, `users.full_name_ar`, `vegetation_plans.name_ar`,
`plan_templates.name_ar`, `plan_templates.description_ar`,
`plan_template_milestones.name_ar`, `resources.name_ar`,
`signal_definitions.name_ar`, `signal_definitions.description_ar`,
`signal_definitions.unit_ar`, `signal_definitions.categorical_values_ar`,
`signal_templates.name_ar`, `signal_templates.description_ar`,
`tenants.name_ar`.

Pattern B does not change in this work. See "What does not change".

### Some content is not in a column at all

Decision tree content lives inside JSON, not columns.

- `public.decision_tree_versions.tree_yaml` is the source text.
- `public.decision_tree_versions.tree_compiled` is JSONB built from it.
- `public.decision_tree_versions.compiled_hash` is a hash of that JSONB.
- Rows are immutable version history.

Inside the compiled document, node labels are `label_en` and `label_ar`, and
leaf guidance is `{horizon: [{text_en, text_ar}]}`. `loader.py:658` treats a
missing `text_en` as a hard error.

`public.crop_attribute_definitions` stores select options as a JSONB array of
`{code, name_en, name_ar, sort_order}` (`farms/models.py:215`). Language keys
are nested inside an array element.

`tenant.recommendations.actions` is JSONB holding the same
`{horizon: [{text_en, text_ar}]}` shape. It is a copy taken when the
recommendation is written.

### The web app cannot express a third language

There are 116 uses of `isAr` across 39 files in `frontend/src`. Each one is
`const isAr = i18n.language === "ar"` followed by `isAr ? x.name_ar : x.name_en`.
For a Portuguese user every one of those returns English. No error is raised.

Two partial helpers exist and are used in two places:
`frontend/src/modules/farms/lib/cropAttributeForm.ts:135` (`label`) and
`frontend/src/modules/labs/console/railSort.ts:69` (`localizedName`).

### Lists are already sorted by the wrong language

Six read paths order by the English column regardless of the reader's language.
An Arabic user sees an Arabic list ordered by the English name.

| File | Line | Order |
| --- | --- | --- |
| `farms/repository.py` | 1033 | `Country.name_en` |
| `farms/repository.py` | 1070 | `Crop.name_en` |
| `farms/repository.py` | 1080 | `CropVariety.name_en` |
| `farms/repository.py` | 1090 | `CropVarietyStrain.name_en` |
| `insights/service.py` | 368 | `c.name_en ASC` in raw SQL |
| `reports/service.py` | 1198 | `c.name_en ASC` in raw SQL |

## What already works and should be copied

Two parts of the system already have the design this document wants.

**`notification_templates`.** The primary key is
`(template_code, locale, channel, version)`. A missing locale falls back to
`en`. See `notifications/repository.py:126` and
`notifications/subscribers.py:218`. Adding Portuguese here is inserting rows.

**The Scout app.** `mobile/src/i18n/index.ts` holds a `LOCALES` registry where
each entry is `{code, endonym, dir, messages}`. `Lang` is derived as
`keyof typeof LOCALES`. `dirOf(lang)` reads direction from the entry rather
than comparing to `"ar"`. `mobile/src/i18n/types.ts` defines
`Messages = Record<MessageKey, string>`, so an incomplete catalogue is a type
error. Adding Portuguese to Scout is one file and one registry line.

The web app must be rebuilt to match Scout, not the other way round.

## Decisions taken

These were decided in discussion on 2026-09-07. They are inputs to the build,
not open questions.

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Portuguese serves a new market with its own tenants. | Gulf tenants do not need Portuguese and Brazilian tenants do not need Arabic. |
| D2 | Replace the `_en` and `_ar` column pairs with one generic model. | A third column set costs the same again for the fourth language. |
| D3 | The generic model is a JSONB map per field, not a side table. | Two of the shapes are already JSON, and a side table cannot address a value inside a JSON array. |
| D4 | Consumer endpoints return one resolved string. Authoring endpoints return the whole map. | A field screen needs one language. An editor needs every language at once. |
| D5 | The client sends `Accept-Language`, and changing language also writes `user_preferences.language`. | Assumed, not confirmed. See "Open questions", Q1. |

## The design

### 1. One language registry

`backend/app/shared/i18n.py` becomes the only list, and every other list is
deleted.

```python
SupportedLanguage = Literal["en", "ar", "pt"]
SUPPORTED_LANGUAGES: tuple[str, ...] = get_args(SupportedLanguage)
DEFAULT_LANGUAGE: SupportedLanguage = "en"
```

Changes required:

- `app/shared/auth/context.py:78` uses `SupportedLanguage`, not its own literal.
- `app/shared/auth/middleware.py:81-83` validates against `SUPPORTED_LANGUAGES`.
- `app/modules/tenancy/schemas.py:26,56` uses `SupportedLanguage`.
- Add a test that asserts no module outside `shared/i18n.py` contains the string
  `"ar"` inside a `Literal[...]` or a membership test. A grep test is enough.

The frontend gets the matching registry at `frontend/src/i18n/locales.ts`, in
the shape Scout already uses:

```ts
export const LOCALES = {
  en: { code: "en", endonym: "English",   dir: "ltr" },
  ar: { code: "ar", endonym: "العربية",    dir: "rtl" },
  pt: { code: "pt", endonym: "Portugues", dir: "ltr" },
} as const;

export type SupportedLanguage = keyof typeof LOCALES;
export const dirOf = (l: SupportedLanguage) => LOCALES[l].dir;
```

The `pt` endonym must be written with its accent, "Português". It is
spelled without the accent here only to keep this file plain ASCII.

`frontend/src/i18n/index.ts` builds `SUPPORTED_LANGUAGES` and
`syncHtmlAttributes` from `LOCALES`. The current
`language === "ar" ? "rtl" : "ltr"` is deleted.

A test must assert that the backend list and the frontend list are equal. Read
`shared/i18n.py` and `locales.ts` in one test and compare the codes. Frontend
and backend constants drift without showing any error, and this project has hit
that before.

### 2. Storage: one JSONB column per translatable field

For each of the 21 Pattern A pairs, `x_en TEXT NOT NULL` and `x_ar TEXT` become
one column:

```sql
x JSONB NOT NULL DEFAULT '{}'::jsonb
CONSTRAINT ck_<table>_<field>_has_en CHECK (x ? 'en' AND length(x->>'en') > 0)
```

Value shape: `{"en": "Mango", "ar": "...", "pt": "Manga"}`.

Rules:

- English must exist. The CHECK enforces it, in place of the old `NOT NULL`.
- A missing language means the key is absent. Do not store `null` and do not
  store an empty string. A reader treats absent and empty the same, but only one
  form is written.
- Keys are the codes from the registry. Nothing else is accepted.

Note: the JSONB containment operator is `?`, which some drivers read as a bind
marker. Confirm the behaviour with asyncpg before writing the CHECK in a
migration. `jsonb_exists(x, 'en')` is the same test written as a function call
and avoids the question.

Indexes. Where a table is ordered by name, add an expression index per language
that is actually used:

```sql
CREATE INDEX ix_crops_name_en ON public.crops ((name->>'en'));
CREATE INDEX ix_crops_name_pt ON public.crops ((name->>'pt'));
```

Only add these for `countries`, `crops`, `crop_varieties` and
`crop_variety_strains`. Those are the four tables with an `ORDER BY` on a name.
Measure the row counts first. If a table has under 500 rows the index is not
worth the write cost.

### 3. Reading: resolve on the server for consumers

Add `app/shared/i18n.py::resolve(value, lang) -> str`:

```python
def resolve(value: Mapping[str, str] | None, lang: str) -> str:
    if not value:
        return ""
    for code in (lang, DEFAULT_LANGUAGE):
        text = (value.get(code) or "").strip()
        if text:
            return text
    return ""
```

The fallback chain is the requested language, then English, then empty string.
It is two steps and no more. Do not add a region fallback such as `pt-BR` to
`pt`; strip the region at the edge instead.

Consumer response schemas change shape:

```python
# before
class CropOut(BaseModel):
    name_en: str
    name_ar: str | None

# after
class CropOut(BaseModel):
    name: str            # already resolved
    name_locale: str     # which language the string is actually in
```

`name_locale` matters. When a Portuguese user sees an English crop name because
no Portuguese exists, the client needs to know, so it can mark the string. See
"Making a gap visible".

Authoring response schemas keep the map:

```python
class CropAdminOut(BaseModel):
    name: dict[str, str]
```

The authoring endpoints are the platform catalogue console, the decision tree
editor, the crop attribute editor, the signal editor and the plan template
editor. List them explicitly in the build, and do not let a consumer route
return a map by accident.

### 4. Where the request language comes from

Assumed design, pending Q1.

A FastAPI dependency `current_language()` returns the language for this request,
in this order:

1. The `Accept-Language` request header, primary subtag only, if it is in
   `SUPPORTED_LANGUAGES`.
2. `RequestContext.preferred_language` from the JWT claim.
3. `DEFAULT_LANGUAGE`.

The web app and Scout both send the header on every request. The web app reads
its choice from `localStorage["agripulse.lang"]`. Scout reads
`localStorage["agripulse.scout.lang"]`.

Background work has no header. Celery tasks read `user_preferences.language`,
which is what `notifications/subscribers.py:160` already does with
`COALESCE(up.language, 'en')`.

Write-through. When a user changes language in the web app or in Scout, the
client also calls `PATCH /me/preferences` with the new language. Without this,
the user reads Portuguese labels and receives English email. Scout already has
the harder half of this: `mobile/src/i18n/preference.ts` tracks whether the
choice was explicit, so a server default never overrides a person's own choice.
The web app has no equivalent and needs one.

### 5. Decision trees

This is the largest single piece.

The seed files hold 841 English keys and 841 Arabic keys: 458 `text_en`,
317 `label_en`, 33 `name_en`, 33 `description_en`, across 34 files in
`app/modules/recommendations/seeds/` plus 3 files in `app/modules/health/seeds/`.

New YAML shape. A translatable value becomes a map:

```yaml
actions:
  immediate:
    - text:
        en: "Look at the flower panicles first and confirm the growth is there."
        ar: "..."
        pt: "Observe primeiro as paniculas florais e confirme o crescimento."
```

The loader must accept both shapes during the change:

- If the key is `text_en` or `text_ar`, read the old shape and build the map.
- If the key is `text`, read the map.
- A map with no `en` key, or an empty `en`, stays a hard error, exactly as
  `loader.py:658` treats a missing `text_en` today.

Accepting both shapes is what makes it possible to convert 37 files in more than
one commit without breaking the seed run.

Historical versions. `decision_tree_versions` is immutable and
`compiled_hash` is derived from `tree_compiled`. Two options:

- Option 1: migrate `tree_compiled` in place for every row and recompute
  `compiled_hash`. This edits immutable history.
- Option 2: leave old rows alone and make the reader accept both shapes, using
  the same rule as the loader.

Take Option 2. Immutable history that changes is worse than a reader with two
branches. Write the reader branch in one function, not at each call site.

### 6. Rows that copy text at write time

Three tables store a copy of the text at the moment the row is created:

- `tenant.alerts.diagnosis_en`, `diagnosis_ar`, `prescription_en`,
  `prescription_ar`
- `tenant.recommendations.text_en`, `text_ar`, and `actions` JSONB
- `tenant.decision_tree_block_verdicts.text_en`, `text_ar`

Consequence: if Portuguese is added to a decision tree card next year, every
alert and recommendation already written keeps the two languages it copied. A
Portuguese user reading history sees English for ever.

Design: convert these to the JSONB map like any other Pattern A field, and
accept that a row carries the languages that existed when it was written. Do
not switch to a reference into the tree version. That would change what a row
means, and an alert must keep the words it was raised with even after the tree
is edited.

Note for the build: this is a real limit and the product owner should be told
about it. It is not a defect to fix later.

### 7. The web app

Build the registry from section 1, then add one helper:

```ts
// frontend/src/i18n/useLocalized.ts
export function useLocalized() {
  const { i18n } = useTranslation();
  const lang = i18n.language as SupportedLanguage;
  return (value: LocalizedText | null | undefined) => resolve(value, lang);
}
```

`LocalizedText` is `Partial<Record<SupportedLanguage, string>>`.

Then replace all 116 `isAr` sites across 39 files. Most are one line. Delete
`isAr` entirely and add an ESLint rule that fails on `=== "ar"` anywhere under
`frontend/src`, so the pattern cannot come back.

The existing `label()` in `farms/lib/cropAttributeForm.ts:135` and
`localizedName()` in `labs/console/railSort.ts:69` are deleted and replaced by
the one helper.

Translation files. There are 30 namespaces holding 4,681 English strings and
4,697 Arabic strings. A Portuguese set is 30 new files. Add a test that fails
when a namespace has a key in `en` and no key in `pt`, and reports the count.
Do not make a missing key a build failure at first, or nothing can be merged
until every string is translated. Make it a reported number that must not grow.

Note: `tsc -b` passes on a stale build cache and then fails in CI. Run
`tsc -b --force` after changing the shared types, and grep for callers across
all of `src`.

### 8. Scout

Three changes:

1. `mobile/src/i18n/locales/pt.ts` exporting a complete `Messages`. The English
   catalogue has 162 keys.
2. One line in the `LOCALES` registry in `mobile/src/i18n/index.ts`.
3. `DEFAULT_LANG` stays `"ar"`. A Brazilian handset picks Portuguese through
   `navigator.language` in `preference.ts`, or through the server default on
   the user record.

Scout needs no other work. Its design already handles this.

Note: `mobile/` ships as an APK and has no CI. A merge reaches nobody until
somebody builds and distributes the file.

### 9. Sorting

Change the six `ORDER BY` sites to order by the reader's language, falling back
to English:

```sql
ORDER BY COALESCE(NULLIF(name->>:lang, ''), name->>'en')
```

Pass `lang` as a bind parameter from `current_language()`. This project has been
bitten by a string bind against a cast column, so keep this one a plain text
comparison and pass a plain string.

Collation. Portuguese sorts accented letters next to their base letter. The
database's default collation may not do this. Check
`SELECT datcollate FROM pg_database WHERE datname = current_database()` on
production before deciding. If the collation is wrong, add
`COLLATE "pt-BR-x-icu"` to the Portuguese order path only. Do not change the
database collation.

### 10. Which languages a tenant offers

`public.tenants.default_locale` already exists. It is `TEXT NOT NULL DEFAULT
'en'`, and `tenancy/schemas.py` types it as `Literal["en", "ar"]`.

Decision D1 says Portuguese serves its own tenants. Add one column:

```sql
ALTER TABLE public.tenants
  ADD COLUMN available_locales TEXT[] NOT NULL DEFAULT ARRAY['en'];
```

Rules:

- `default_locale` must be a member of `available_locales`. Add a CHECK.
- The language picker in the web app and in Scout shows only the tenant's
  `available_locales`.
- The registry in `shared/i18n.py` says which languages the product can render.
  `available_locales` says which ones this tenant may choose. The first is a
  code question, the second is a sales question.

Note: the platform catalogue in `public` is shared by every tenant. A Brazilian
tenant reads the same `crops` rows as a Gulf tenant. Portuguese content is
added to those shared rows. It is not per tenant, and the build must not try to
make it per tenant.

### 11. Making a gap visible

A missing translation falls back to English and shows a real word. That is
right for the user and wrong for whoever has to find the gaps.

Two mechanisms, both cheap:

1. `name_locale` on every consumer response, as in section 3. When
   `name_locale` differs from the requested language, the web app renders the
   string with a dotted underline and a title attribute naming the language
   actually shown. Only in the platform console, not in the tenant-facing app.
2. An endpoint `GET /platform/i18n/coverage` that returns, per table and per
   field and per language, the count of rows with a value and the count without.
   One query per table. This is the report that says whether Portuguese is
   finished.

## What does not change

- **Pattern B columns.** `farms.name`, `blocks.name`, `resources.name` and the
  other 13 are names people type. The base column has no language tag, so there
  is no way to say which language it holds. A Brazilian tenant types Portuguese
  into `farms.name` and that is correct. `name_ar` stays as an optional Arabic
  alternate for tenants that want one. Adding `name_pt` here would be wrong: a
  farm has one name, not one name per language.
- **`notification_templates`.** Already keyed by locale. Portuguese is rows.
- **`user_preferences.language`.** Already free text with an `en` default.
- **Scout's i18n design.** Already correct.
- **Unit preference.** `preferred_unit` sits next to `preferred_language` in the
  auth context with the same hard-coded validation shape. It is a separate
  concern. Do not fold it into this work.

## Volume of translation

Engineering does not produce these words. Someone must write them.

| Where | Strings |
| --- | --- |
| Web app namespaces, 30 files | 4,681 |
| Scout catalogue, 1 file | 162 |
| Decision tree and health seeds, 37 files | 841 |
| Database catalogue rows | Not measured |

Total known: 5,684 strings.

The 841 seed strings are agronomic advice. They cannot be machine translated
without review by someone who knows both the language and the crop. The 4,681
interface strings can start from machine translation with review.

Database catalogue rows are not counted here because they must be counted on
production, not in the repository. Run this on the production database:

```sql
SELECT 'crops' AS t, count(*) FROM public.crops
UNION ALL SELECT 'crop_varieties', count(*) FROM public.crop_varieties
UNION ALL SELECT 'crop_variety_strains', count(*) FROM public.crop_variety_strains
UNION ALL SELECT 'countries', count(*) FROM public.countries
UNION ALL SELECT 'crop_attribute_definitions', count(*) FROM public.crop_attribute_definitions
UNION ALL SELECT 'indices_catalog', count(*) FROM public.indices_catalog
UNION ALL SELECT 'weather_indices_catalog', count(*) FROM public.weather_indices_catalog
UNION ALL SELECT 'weather_derived_signals_catalog', count(*)
  FROM public.weather_derived_signals_catalog;
```

## Migrations

Latest on `origin/main`: public `0081_crop_health_definitions.py`, tenant
`0091_decision_tree_block_verdicts.py`.

Caution: check for a claimed number before writing a file. This project has
lost the migration-number race twice, and a duplicated public `0080` once broke
all 1,218 integration tests. Run `git ls-remote --heads origin` and check open
branches for a migration with the number you intend to use.

Each conversion migration has the same three steps, and they run in one
transaction:

1. Add the new JSONB column with a temporary nullable definition.
2. `UPDATE ... SET x = jsonb_strip_nulls(jsonb_build_object('en', x_en, 'ar',
   NULLIF(x_ar, '')))`. `jsonb_strip_nulls` is what keeps a missing language
   absent rather than `null`.
3. Set `NOT NULL`, add the CHECK, drop `x_en` and `x_ar`.

Warning: dropping the old columns in the same migration means the previous
application version cannot read the table. Either accept a short window where
the old pods fail, or split each conversion into two releases: one that adds and
fills the new column while the code reads both, and a later one that drops the
old columns. For 12 tables, the two-release path is 24 migrations. Decide this
before starting. See Q3.

Constraint names. On the production database the live `platform_alerts` CHECK
names are doubled, for example `ck_platform_alerts_ck_platform_alerts_kind`.
Read the live constraint name from `pg_constraint` before writing a
`drop_constraint`. Do not assume the name in the migration file is the name in
the database.

Views. `pg_get_viewdef` drops the schema qualification, so a view that reads a
converted column will not be found by a grep for the table name. List the views
over each of the 12 tables before converting it.

## Phases

Each phase is one pull request. Each is deployable on its own.

| Phase | Content | Depends on |
| --- | --- | --- |
| P1 | One language registry. Delete the three duplicate lists. Add the grep test and the frontend-backend equality test. Do not add `pt` yet. | - |
| P2 | Web app locale registry, `useLocalized` helper, replace all 116 `isAr` sites, add the ESLint rule. Still two languages. | P1 |
| P3 | `current_language()` dependency, `resolve()`, `Accept-Language` from both clients, write-through to `user_preferences.language`. | P1 |
| P4 | Convert the 8 public catalogue tables to JSONB maps. Consumer and authoring schemas split. Sorting by reader language. | P2, P3 |
| P5 | Convert the 4 tenant tables: `recommendations`, `alerts`, `decision_tree_block_verdicts`, and the `actions` JSONB. | P4 |
| P6 | Decision tree YAML map shape. Loader accepts both. Reader accepts both compiled shapes. Convert the 37 seed files. | P5 |
| P7 | `tenants.available_locales`, the CHECK, and the language picker reading it. | P1 |
| P8 | Add `pt` to the registry. Add `pt.ts` to Scout. Add the 30 Portuguese namespace files. Coverage endpoint. | P1-P7 |

Portuguese does not appear until P8. Phases P1 to P7 are the same work whether
the next language is Portuguese or anything else, and each one can be checked
against the existing two languages before Portuguese raises the cost of a
mistake.

## Tests

The build must add these. Tests that assert the layer below the broken one have
passed while the product showed the wrong language in this project before.

1. **Registry equality.** Read `shared/i18n.py` and
   `frontend/src/i18n/locales.ts` and assert the language codes match.
2. **No stray language list.** Grep `backend/app` for `"ar"` inside `Literal[`
   or inside a tuple membership test. Fail on any hit outside `shared/i18n.py`.
3. **No `isAr`.** ESLint rule failing on `=== "ar"` under `frontend/src`.
4. **Rendered string, not the key.** For at least one page per namespace, render
   with `lng: "pt"` and assert the visible text is the Portuguese string. A test
   that asserts a translation key was requested proves nothing. This project
   shipped 1,656 passing tests while the screen showed English under Arabic
   names.
5. **Fallback.** A row with `{"en": "Mango"}` and a request for `pt` returns
   `"Mango"` with `name_locale: "en"`.
6. **CHECK holds.** Inserting a row with `{"pt": "Manga"}` and no `en` key
   fails.
7. **Both compiled shapes.** A `decision_tree_versions` row in the old
   `text_en` shape and one in the new `text` shape both render.
8. **Migration round trip.** Follow the existing pattern in
   `tests/integration/.../test_migration_0091_verdicts.py`.
9. **Run `pytest tests/unit` as well as the integration suite.** A field added
   in the middle of a dataclass shifts positional arguments, and only the unit
   suite builds them that way. Put new dataclass fields last, with a default.
10. **Namespace registration in tests.** `setupTestI18n` needs each new
    namespace named, or a page renders with zero strings and the test still
    passes.

## Open questions

**Q1. Where does the request language come from?** This document assumes the
`Accept-Language` header, with the JWT claim as fallback, plus write-through to
`user_preferences.language`. The alternatives are the JWT claim alone, which
does not take effect until the token refreshes, or a database read on every
request. Confirm before P3.

**Q2. Portuguese of Portugal or of Brazil?** The code `pt` covers both, and the
words differ. If both are needed the registry needs `pt-BR` and `pt-PT`, and
`resolve()` needs a region fallback step it does not have. Decide before P8,
because it changes the translation contract, not the code.

**Q3. One release per table conversion, or two?** Dropping `x_en` and `x_ar` in
the same migration that adds `x` means the running pods cannot read the table
during the rollout. Two releases per table is safe and doubles the migration
count from 12 to 24. Decide before P4.

**Q4. Who writes the 841 seed strings?** They are agronomic advice. Name the
person or the service before P8 starts, because P8 cannot finish without them.

**Q5. Does the platform catalogue console let a platform admin edit Portuguese?**
If yes, the authoring screens in P4 need a language tab per field, which is
design work not covered here.
