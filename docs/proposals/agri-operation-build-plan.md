# Agri Operation: build plan

Status: approved scope, in delivery. Owner sign-off on all 31 design decisions
on 2026-11-13 (decision page: claude.ai artifact "Agri Operation design
decisions"). This file is the source of truth for the build loop: each PR
updates the **Status** table at the end.

## 1. What we are building

Agri Operation replaces two things:

1. **The platform admin plan template editor** (`PlanTemplateEditorPage`).
   Platform admins author and publish *operation manuals* in a new, shared
   manual view (stage ribbon, activities grouped by stage, evidence and
   source on each activity).
2. **The Plan board's Apply template dialog** (`ApplyTemplateDialog`). Farms
   read the same manual view (read-only) in a Catalog tab and build **saved
   plans** in a Plan tab: blocks → operations → season and start dates →
   calendar → apply. Saved plans can be reopened and edited.

Platform admins do not build plans for specific farms, and do not see farms'
saved plans (H7).

The code keeps the `plan_templates` names; users see **"Operation manual"**
(A3).

## 2. Decisions (owner answers)

| ID | Decision | Answer |
|---|---|---|
| A1 | Where it lives | New Farm management nav item "Agri Operation" |
| A2 | Apply template dialog | Hidden behind a flag until Agri Operation is GA. With G2 = GA, it goes at launch |
| A3 | Name | "Operation manual" in the UI; code keeps `plan_templates` |
| H1 | Admin entry point | Platform → Operation manuals, opening the shared view in edit mode, outside any farm |
| H2 | Old editor retirement | Only once the new editor covers everything the old one does |
| H3 | Editing style | Inline, in the expanded stage-grouped row |
| H4 | Anchors | Stage first; start and milestone under "More anchors" |
| H5 | Variety preview | Variety switcher showing resolved weeks |
| H6 | Publish | Shows what changed and how many farms use the manual |
| H7 | Admin access to farm plans | None |
| B1 | Saved plan storage | New tenant table `plan_allocations` |
| B2 | Plans per season | Many |
| B3 | Activity identity | Stable `code` on each manual activity |
| B4 | Manual updated after allocation | Farm sees "manual updated", reviews and re-applies |
| C1 | Start date for perennials | Stage dates win; start date moves only start/milestone anchors and annual crops |
| C2 | Calendar dates | From the server preview, plus saved moves |
| C3 | Non-matching blocks | Only matching blocks; others greyed with the reason |
| C4 | Board moves | A board reschedule becomes a saved date override |
| D1 | Farm edits to manual activities | Include/exclude **and** edit product, dosage, notes |
| D2 | Custom activity fields | Type, title, product, dosage, notes, plus a week or an optional stage anchor |
| E1 | Titles | Add `title` / `title_ar`; backfill seeded manuals |
| E2 | Evidence and source | Structured fields, backfilled from notes |
| E3 | Arabic content | In v1 (`notes_ar`, `product_name_ar`, `dosage_ar`, `title_ar`) |
| E4 | Draft manuals for farms | Hidden; "no manual published yet" |
| F1 | Decision-tree duplicates | Recommendation links to the planned activity ("already planned") |
| F2 | Assignees | Unchanged; Action Center |
| F3 | Permission | New capability for saved plans |
| F4 | Delete saved plan | Remove still-scheduled activities (soft delete); keep done and in-progress |
| G1 | Crops | Mango and date palm |
| G2 | Launch | GA for every farm |
| G3 | Devices | Desktop first; phones read-only for saved plans |

## 3. Design

### 3.1 Manual (public schema)

`plan_template_activities` gains:

- `code` text, unique per template, stable across saves (B3). Backfill:
  `<activity_type>-<n>` by current `sort_order`.
- `title`, `title_ar`, `notes_ar`, `product_name_ar`, `dosage_ar` (E1, E3).
- `evidence_tier` text, CHECK in (`eg_fao`, `eg`, `generic`) or null (E2).
- `source_tree_code` text, nullable: the decision tree the activity comes
  from (E2, F1).

`plan_templates` gains `revision` int (bumped on every publish) and
`published_at` (B4, H6), and `published_snapshot` (public 0107): the
manual's activities by code at its last publish. A saved plan keeps
`manual_snapshot` (tenant 0103), the manual as it last applied it. Diffs by
code feed the Publish step (H6) and the farm's "manual updated" (B4).

`replace_full_tree` upserts activities **by code** instead of delete +
insert, so ids survive a save. Activities whose code disappears are
deleted (they were never referenced by code from tenants except through
allocations, which handle missing codes, see 3.3).

### 3.2 Plan activities (tenant schema)

`plan_activities` gains `title`, `title_ar`, `allocation_id` (nullable),
`activity_key` (manual activity code, or `custom:<uuid>`), and
`date_overridden` bool.

### 3.3 Saved plans (tenant schema, B1, B2)

`plan_allocations`:

| Column | Notes |
|---|---|
| `id`, `farm_id`, `plan_id` | `plan_id` = the season's `vegetation_plans` row (find-or-create, as today) |
| `template_id`, `template_revision` | revision applied last (B4) |
| `season_label`, `season_year` | |
| `start_mode` | `same` / `per_block` |
| `blocks` jsonb | `[{block_id, start_date}]` |
| `excluded_codes` text[] | D1 |
| `activity_edits` jsonb | `{code: {product_name, dosage, notes, *_ar}}` (D1) |
| `custom_activities` jsonb | `[{key, activity_type, title, title_ar, anchor: week/stage, week, stage_code, offset_days, duration_days, product_name, dosage, notes}]` (D2) |
| `date_overrides` jsonb | `{block_id: {activity_key: date}}` (C2, C4) |
| `status` | `active` / `deleted` |
| audit columns, `deleted_at` | |

Apply for an allocation (pure resolver + service):

1. Resolve the manual for each block (stage anchors from the block's
   resolved phenology, C1), drop excluded codes, merge activity edits, add
   custom activities, then apply date overrides (`date_overridden = true`).
2. Soft-delete this allocation's still-`scheduled` rows, insert the new set.
   Rows that are `in_progress` / `completed` / `skipped` stay.
3. Blocks whose crop does not match the manual path are rejected (C3).
4. A code in `excluded_codes` / `activity_edits` / overrides that no longer
   exists in the manual is reported in the preview as "removed from manual".

Board reschedule of a row with an `allocation_id` writes the new date into
that allocation's `date_overrides` (C4). Delete of an allocation soft-deletes
its still-scheduled rows (F4); nothing is hard-deleted.

### 3.4 API

Platform (cap `plan_template.manage`), existing routes kept, plus:

- `GET /v1/plan-templates/{id}/authoring-view` → the manual (drafts
  included) with its resolved stages and the resolved stages of every variety
  it covers (H5). The client turns stage starts into week numbers.
- `GET /v1/plan-templates/{id}/publish-impact` → diff since the last
  published revision (by code) and the count of farms with active
  allocations (H6). Cross-tenant count only, no farm names (H7).

Tenant:

- `GET /v1/plan-templates/catalog?farm_id=&crop=` and
  `GET /v1/plan-templates/{id}/manual?farm_id=` (cap `plan_template.read` on
  the farm): published manuals only (E4); the manual carries the full tree,
  its resolved stages and the stages per variety it covers.
- Saved plans, all under `/v1/farms/{farm_id}/plan-allocations`:
  `GET` (list), `POST` (save a new plan and apply it), `POST .../preview`
  (unsaved state → per-block dated schedule, rejected blocks, codes the
  manual no longer has; C2, C3), `GET|PUT|DELETE .../{id}` (read, replace and
  re-apply, delete with soft delete of still-scheduled rows; F4). Saving
  always applies. Each saved plan reports `manual_updated` when its manual
  was published again after it was applied (B4); the change diff lands in
  PR 4.
- New capabilities (F3): `plan_allocation.read`, `plan_allocation.manage`,
  granted to the roles that hold `plan_template.apply` today.

### 3.5 Frontend

- `modules/agriOperation/`: `ManualView` (shared; `mode="read" | "edit"`),
  `CatalogTab`, `PlanWizard` (4 steps), `SavedPlansList`,
  `WeekCalendar` (day-precision lanes, drag and date entry, keyboard
  accessible), i18n namespace `agriOperation` in `en` and `ar`.
- Route `farms/:farmId/agri-operation`; nav item under Farm management (A1).
- Platform route `platform/operation-manuals` (+ `/:id`), using `ManualView`
  in edit mode with the variety switcher (H5) and publish-impact dialog (H6).
  The old editor stays at `platform/plan-templates/:id` until parity (H2).
- Board: show `title`, the "moved" dot for `date_overridden`, a link to the
  saved plan; the Apply template button is removed (A2 + G2).
- Phones: the Agri Operation page is read-only below 768 px (G3).

### 3.6 Decision trees (F1)

When the recommendation engine is about to open a recommendation for a
block and tree, it looks for a non-deleted `plan_activities` row on that
block with `source_tree_code` (through its manual activity) equal to the
tree's code, status `scheduled` or `in_progress`, and `scheduled_date`
within ±14 days. If one exists, the recommendation is created with
`plan_activity_id` set and shown as "Already planned" in the Action Center
instead of as new work. This adds a lookup to recommendation creation only;
it does not switch engines or publish trees.

## 4. Delivery: PRs

Each PR is self-contained, ships tests, and keeps CI green. "Deploy" means
the promotion procedure in `CLAUDE.md`.

| # | PR | Main contents | Tests | Deploy |
|---|---|---|---|---|
| 1 | Manual content model | Public migration (3.1), backfill codes, titles (en/ar), evidence tiers and source trees for the seeded mango, potato and Medjool manuals; the current editor carries codes and new fields through a save; upsert-by-code in `replace_full_tree`; schemas; apply copies titles; tenant migration for `plan_activities.title/title_ar` | unit: resolver unchanged; integration: save keeps ids, backfill values, apply writes titles | api + workers |
| 1b | Arabic manual text | `notes_ar`, `product_name_ar`, `dosage_ar` for the seeded manuals (E3); Medjool from the manual's Arabic edition | integration: no live manual activity without Arabic | api (before farm launch) |
| 2 | Tenant manual read API + capabilities | Catalog and manual endpoints, `plan_allocation.*` capabilities in RBAC yaml + frontend `capabilities.ts`, varieties-preview endpoint | integration: drafts hidden, caps enforced | api |
| 3 | Saved plans backend | Tenant migration (3.2, 3.3), resolver extensions (exclusions, edits, customs, overrides), service + router, board-reschedule override hook, soft-delete on allocation delete, audit events | unit: resolver matrix; integration: re-apply keeps board moves and done rows, two allocations per season, C3 rejection, F4 | api + workers |
| 4 | Manual revisions | `revision` bump on publish, `manual-changes` diff, `publish-impact` count | unit: diff by code; integration: outdated flag after publish | api |
| 5 | Agri Operation page + Catalog tab | `ManualView` read mode, crop/variety picker, ribbon, stage groups, evidence and source, empty state for unpublished crops; route without nav yet | vitest: rendering, RTL, empty state | frontend |
| 6 | Plan tab | 4-step wizard, server preview calendar with drag/keyboard moves, saved plans list, edit, delete, phone read-only; nav item live (GA) | vitest: each step, gating, override persistence; Playwright e2e on the wizard happy path | frontend (farm launch) |
| 7 | Board integration | Titles, moved dot, saved-plan link, Apply template button removed, telemetry events | vitest | frontend |
| 8 | Platform manual editor | `platform/operation-manuals`, `ManualView` edit mode (inline, H3), anchors (H4), variety switcher (H5), publish dialog (H6), validation parity checklist | vitest: parity checklist covers every old-editor capability | frontend |
| 9 | Decision-tree dedupe | F1 lookup + `recommendations.plan_activity_id` column, Action Center "Already planned" | unit + integration on the engine path | api + workers + frontend |
| 10 | Cleanup | Remove old editor and `ApplyTemplateDialog` once PR 8 parity is confirmed in prod; runbook `docs/runbooks/phenology-and-plan-templates.md` rewritten; telemetry taxonomy | full suites | frontend |

Deploy waves: after PR 1, after PR 2–4 (backend complete), after PR 5–7
(farm launch), after PR 8, after PR 9, after PR 10.

## 5. How the build loop works

The loop is self-paced. Each iteration:

1. Read this file's **Status** table and the open PR from the working
   branch `claude/modest-darwin-5y1rvp`. PRs go one at a time from that
   branch; after each merge the branch restarts from the latest `main`.
2. Do the next action for the earliest unfinished PR:
   build → test locally (unit; integration with Docker; frontend lint,
   typecheck, vitest, build) → push → open PR → subscribe to PR activity →
   fix CI → merge when required CI is green (read `backend-integration`'s
   pytest summary, not its conclusion) → when the PR closes a deploy wave,
   wait for `ci` on the merge commit and open the promotion PR in
   `infra/argocd/overlays/hetzner/values.yaml` with notes and rollback
   tags → merge → verify (`verify-prod-frontend.sh`,
   `check-prod-beta-designer.cjs` in token mode, plus an API smoke of the new
   endpoints with the `claude-automation` client).
3. Update the Status table in the PR that finishes each step.
4. While waiting on CI, the PR subscription wakes the session; the loop
   fallback wake is 20–30 minutes.

### Stop and ask the owner when

- an action is on the `CLAUDE.md` "may not" list (force-push or rewrite
  `main`, disable or skip tests, switch the decision engine, publish decision
  trees, hard-delete data);
- a migration would destroy or rewrite tenant data beyond the additive
  changes above;
- prod verification fails and one fix-forward does not clear it (roll back
  to the noted tag first, then ask);
- the work needs a decision that contradicts section 2;
- the session needs network access to `app.` / `api.agripulse.cloud`
  (environment approval prompt).

## 6. Status

| # | PR | State | Link | Deployed |
|---|---|---|---|---|
| 0 | Build plan | merged | [#848](https://github.com/msoliman1975/AgriPulse/pull/848) | n/a |
| 1 | Manual content model | merged | [#848](https://github.com/msoliman1975/AgriPulse/pull/848) | e842760 via [#850](https://github.com/msoliman1975/AgriPulse/pull/850), verified 2026-11-14 |
| 1b | Arabic manual text | `notes_ar`, `product_name_ar`, `dosage_ar` for the seeded manuals (E3); Medjool from the manual's Arabic edition | integration: no live manual activity without Arabic | api (before farm launch) |
| 1b | Arabic manual text | not started | | |
| 2 | Tenant manual read API + capabilities | in review | [#852](https://github.com/msoliman1975/AgriPulse/pull/852) | |
| 3 | Saved plans backend | in review | [#852](https://github.com/msoliman1975/AgriPulse/pull/852) | |
| 4 | Manual revisions | in review | [#852](https://github.com/msoliman1975/AgriPulse/pull/852) | |
| 5 | Agri Operation page + Catalog tab | not started | | |
| 6 | Plan tab | not started | | |
| 7 | Board integration | not started | | |
| 8 | Platform manual editor | not started | | |
| 9 | Decision-tree dedupe | not started | | |
| 10 | Cleanup | not started | | |
