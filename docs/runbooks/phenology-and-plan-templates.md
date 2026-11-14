# Phenology, operation manuals and saved plans

How the phenology spine drives stage-aware planning; how platform admins
author operation manuals; how a farm turns a manual into a saved plan on its
board (Agri Operation); and how decision trees avoid raising work a plan
already has. Design and decisions: `docs/proposals/agri-operation-build-plan.md`.

"Operation manual" is the product name for what the API and tables still call
a plan template (`public.plan_templates`, `/api/v1/plan-templates`).

## Concepts

- **Phenology stages** are platform-curated, resolved per crop **path**
  (`crop` → `variety` → `strain`, deepest wins, same governance as
  thresholds). Each stage has an `advance` mode:
  - `calendar_doy` (perennials, e.g. **mango**, **Medjool**): the stage
    starts on a day of year, every season.
  - `days_from_planting` (annuals, e.g. **potato**): the stage starts N days
    after the block's planting date.
- **Growth stage** of a block is stored on `block_crops.growth_stage`. A
  daily Beat task (`phenology.advance_growth_stages`) advances each block to
  the stage its date resolves to and writes a `GrowthStageLog` row with
  `source='derived'`. The rules engine reads `growth_stage`.
- **Operation manuals** are platform-curated and crop-path keyed: a header,
  template-local **milestones** (named days) and **activities**. Each
  activity has a stable `code` (kept across edits), a type, a title (EN/AR),
  product, dosage and notes (each EN/AR), an optional catalogue input and
  structured dose (D20), an evidence tier (`eg_fao`, `eg`, `generic`,
  `manual`) and an optional `source_tree_code` naming the decision tree it
  answers. It anchors to one of:
  - `stage`: the resolved stage start date for the block + `offset_days`
    (perennial: stage `start_doy` mapped onto the season year; annual:
    `planting_date + start_day`). This is the normal anchor.
  - `start`: `block_start_date + offset_days`.
  - `milestone`: `block_start_date + milestone.day_from_start + offset_days`.
- **Revisions.** Each publish bumps `revision`, stamps `published_at` and
  stores a snapshot of the published activities. Saved plans keep the
  snapshot they were built from, so a farm can see what changed since.
- **Saved plans** (`plan_allocations`, tenant schema) are a farm's own copy
  of a manual for some blocks and a season: activities left out, product,
  dosage and notes changed, custom activities added, and dates moved. Saving
  writes the activities to the board (`plan_activities`, `source='template'`
  or `'custom'`, with `allocation_id`).

## Auto-advance and the lock flag

- Auto-advance runs daily and skips any block with
  `block_crops.growth_stage_locked = true`. Lock a block (PATCH the crop
  assignment) to pin its stage for manual control.
- A block only advances if its crop path resolves phenology stages. Mango is
  seeded at crop level, so every mango block resolves stages even before a
  variety or strain is assigned.

## Authoring a manual (platform admin)

Capability `plan_template.manage`.

1. **Platform → Operation manuals** (`/platform/operation-manuals`). The old
   `/platform/plan-templates` links redirect here.
2. **New manual**, or open one. The header holds the permanent `code`, the
   name (EN/AR), the crop path (crop, optionally variety and strain), country,
   region and description (EN/AR).
3. Activities are laid out by growth stage under the stage ribbon. **Add
   activity** on a stage adds one anchored to it; open a row to edit it in
   place. **More anchors** holds the milestones and the activities timed from
   the block's start date or a milestone.
4. For a manual whose crop has varieties, the **variety** picker shows the
   weeks each variety's own calendar gives.
5. **Save draft** writes the whole tree (`PUT /plan-templates/{id}`).
   Validation rejects duplicate milestone codes, milestone-anchored
   activities without a known milestone, and stage-anchored activities whose
   stage does not resolve for the path.
6. **Publish…** (only with no unsaved changes) first shows what changed since
   the last publish and how many farms and saved plans use the manual
   (`GET /plan-templates/{id}/publish-impact`), then publishes. Farms with a
   saved plan see the change on their plan and update it themselves.
7. **Archive** stops new plans from using a manual; saved plans keep working.
   **Delete** is for a manual no farm has used.

Do not save or publish a seeded manual as a check in prod.

## Planning a farm (tenant)

Capabilities `plan_template.read`, `plan_allocation.read` and
`plan_allocation.manage`.

1. **Agri Operation** (`/agri-operation/:farmId`, also linked from the board
   header). The **Catalog** tab lists the manuals for the farm's crops, by
   variety, read-only.
2. The **Plan** tab lists saved plans. **New plan** runs four steps: blocks;
   operations (leave out, edit product/dosage/notes, add your own); season
   and start date; the calendar (preview). **Save** applies it to the board.
3. Editing a saved plan and saving again regenerates its still-scheduled
   activities; completed and in-progress ones are kept, and dates moved on
   the board are remembered (`date_overrides`).
4. Phones show the page read-only below 768 px.

The board shows the activity title, a **Plan** badge and a dot on moved
dates.

## Decision trees and planned work (F1)

When the engine opens a recommendation for a block and tree, it looks for a
live plan activity on that block whose manual activity has
`source_tree_code` equal to the tree's code, status `scheduled` or
`in_progress`, within 14 days of today (nearest first), and stores it in
`recommendations.plan_activity_id` (tenant 0107). The Action Center shows the
row as **Already planned · date**, and **Open on board** goes to that
activity. Deleting the activity clears the link. This changes no engine
switch and publishes no tree.

## Seeded manuals

Published in prod: six mango cultivars (`mango-alphonso-eg`, `-crimson-`,
`-keitt-`, `-sukkary-`, `-yasmina-`, `-zebda-eg`), three potato seasons
(`potato-nili-eg`, `-summer-`, `-winter-eg`) and two organic Medjool manuals
(`medjool-organic-bearing-eg`, `medjool-organic-new-planting-eg`). Public
0110 filled their Arabic product, dosage and notes; the Medjool Arabic is a
translation of the English seed and wants review by the platform team.

## Verifying live

Use the `claude-automation` client (platform admin); never a person's
password.

```bash
TOKEN=$(curl -s -u claude-automation:<secret> -X POST \
  https://keycloak.agripulse.cloud/realms/agripulse/protocol/openid-connect/token \
  -d grant_type=client_credentials | jq -r .access_token)
B=https://api.agripulse.cloud/api/v1

# published manuals, then one manual as the editor reads it
curl -s -H "Authorization: Bearer $TOKEN" "$B/plan-templates?status=published"
curl -s -H "Authorization: Bearer $TOKEN" "$B/plan-templates/<id>/authoring-view"

# what a publish would change, and who uses it
curl -s -H "Authorization: Bearer $TOKEN" "$B/plan-templates/<id>/publish-impact"
```

Inside a session where the proxy injects the credential, the secret is a
dummy value. Migrations run on the ArgoCD PreSync job
(`agripulse-api-agripulse-api-migrate`).
