# Phenology & Plan Templates

How the phenology spine drives stage-aware planning, and how to author and
apply a plan template end-to-end.

## Concepts

- **Phenology stages** are platform-curated, resolved per crop **path**
  (`crop` → `variety` → `strain`, deepest-wins, same governance as
  thresholds). Each stage has an `advance` mode:
  - `calendar_doy` (perennials, e.g. **mango**) — stage starts on a
    day-of-year, recurring every season.
  - `days_from_planting` (annuals, e.g. **potato**) — stage starts N days
    after the block's planting date.
- **Growth stage** of a block is stored on `block_crops.growth_stage`. A
  daily Beat task (`phenology.advance_growth_stages`) advances each block to
  the stage its date resolves to and writes a `GrowthStageLog` row with
  `source='derived'`. The rules engine reads `growth_stage`.
- **Plan templates** are platform-curated, crop-path-keyed. A template is a
  header + template-local **milestones** (named days) + **activities**. Each
  activity anchors to one of:
  - `start` — `block_start_date + offset_days`.
  - `milestone` — `block_start_date + milestone.day_from_start + offset_days`.
  - `stage` — the resolved **stage start date for the block** + `offset_days`
    (perennial: stage `start_doy` mapped onto the season year; annual:
    `planting_date + start_day`). This is the spine link.

## Auto-advance & the lock flag

- Auto-advance runs daily and skips any block with
  `block_crops.growth_stage_locked = true`. Lock a block (PATCH the crop
  assignment) when you want to pin its stage for manual control.
- A block only advances if its crop path resolves phenology stages. Mango is
  seeded at crop level, so every mango block resolves stages even before a
  variety/strain is assigned.

## Authoring a template (PlatformAdmin)

1. Go to **Platform → Plan templates → New template** (cap
   `plan_template.manage`).
2. Header: pick the **crop targeting** path (crop, optionally variety/strain),
   a permanent `code`, and a name.
3. Add **milestones** (name + day-from-start) if you want milestone-anchored
   activities.
4. Add **activities**. For each, pick the **anchor**:
   - *Start + offset* / *Milestone* / *Growth stage*. The stage picker only
     offers stages that resolve for the chosen crop path (it calls
     `GET /v1/plan-templates/phenology?crop_path=...`).
5. The **timeline preview** plots start/milestone activities on a relative-day
   axis; stage-anchored activities are listed by stage (their concrete date
   depends on the block at apply time).
6. **Save** (whole-tree PUT), then **Publish**. Only published templates are
   appliable by tenants. Archiving/Delete retire the template (Delete also
   frees the code).

Validation on save rejects: duplicate milestone codes, milestone-anchored
activities referencing an undefined milestone, and stage-anchored activities
referencing a stage that isn't in the resolved phenology for the path.

## Applying a template (tenant)

1. On the farm **Plan** board, click **Apply template** (cap
   `plan_template.apply`).
2. **Step 1** — pick a template (only published, crop-matching templates show).
3. **Step 2** — matching-crop blocks are pre-checked; set each block's start
   date (defaults to its `planting_date`).
4. **Step 3** — season label/year (derived, editable).
5. **Step 4** — **preview** the resolved schedule (stage-anchored dates +
   anything skipped because a stage didn't resolve), then **Apply**.

Apply is **idempotent per (farm, season)**: it regenerates this template's
still-`scheduled` rows and **preserves** manual rows + completed/in-progress
template rows. Generated rows carry `source='template'` and, for
stage-anchored activities, `anchored_stage_code`. The board shows a **Tpl**
badge on template rows and a "scheduled at &lt;stage&gt;" line on
stage-anchored ones.

## Seeded starter

Migration `0035` seeds a published **`mango-season-eg`** template
(`crop_path = mango`) exercising all three anchors:

- `soil_prep` (start, offset 0),
- `irrigation` (milestone `irrigation_setup`, day 14),
- `irrigation` withholding (stage `pre_flowering`),
- `fertilizing` fertigation (stage `fruit_development`),
- `fertilizing` nitrogen flush (stage `post_harvest_flush`, +7d).

The seed is idempotent (skips if the code already exists).

## Verifying live

```bash
# token (direct grant; Playwright OIDC is broken)
curl --ssl-no-revoke -X POST \
  https://keycloak.agripulse.cloud/realms/agripulse/protocol/openid-connect/token \
  -d grant_type=password -d client_id=agripulse-api -d username=<u> -d password=<p> -d scope=openid

# appliable templates for a farm
curl --ssl-no-revoke -H "Authorization: Bearer $TOKEN" \
  "https://api.agripulse.cloud/api/v1/plan-templates/appliable?farm_id=<farm>"

# preview / apply (POST body: farm_id, season_label, season_year, blocks[])
```

Public alembic head should be **`0035`** after deploy (PreSync job
`agripulse-api-agripulse-api-migrate`).
