# PR-E3 — Platform plan-template authoring API + UI

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §4.3; `plan-templates-implementation.md` §3-§4. **Depends on:** PR-E2.

## Goal
Platform admins author templates (header + milestones + activities, incl. stage anchoring) with a timeline preview.

## Backend (cap `plan_template.manage`, platform)
- `GET /v1/plan-templates` · `POST` · `GET /{id}` (full tree) · `PUT /{id}` (**replace whole tree** atomically) · `POST /{id}/publish` · `/archive` · `DELETE` (archive).
- On save, validate stage-anchored activities: `stage_code` must exist in the **resolved** phenology stages for the template's `crop_path`.

## Frontend `/platform/plan-templates`
- List (crop path, status, #applied).
- Editor:
  - Header: cascading **crop → variety → strain picker** emitting `crop_path` (reuse `CropPathFilter`/`CropPicker`, depth-aware via `classification_depth`) + region/country + name.
  - Milestones editor (name + day_from_start).
  - Activities editor: `activity_type`, **anchor dropdown (Start / Milestone / Stage)**; when **Stage**, a stage picker populated from the **resolved phenology stages for the chosen `crop_path`** (fetch from PR-A1 `…/phenology`); offset_days, duration_days, defaults.
  - **Timeline / Gantt preview** of resolved days; publish/archive.
- `api/planTemplates.ts`; i18n en/ar.

## Acceptance
- Author + publish a mango stage-anchored template via UI; whole-tree PUT round-trips; stage picker only offers valid stages for the path; tsc + eslint clean; CI green.
