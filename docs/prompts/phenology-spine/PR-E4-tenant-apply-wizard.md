# PR-E4 — Tenant apply wizard + plan/board integration

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §4.2; `plan-templates-implementation.md` §4. **Depends on:** PR-E2.

## Goal
Tenants apply a template to matching blocks and see generated activities on the plan/board, badged.

## Frontend (Plan/board page + farm context on `/labs/map`)
- "Apply template" → 4-step wizard:
  1. Pick template (appliable matches first, region hint).
  2. Pick blocks (pre-checked matching-crop) + **per-block start date** (default `planting_date`).
  3. Season label/year (derived, editable).
  4. **Preview schedule** (shows stage-anchored dates + any skipped activities) → confirm → apply.
- Board: show a "from template" badge on `source='template'` rows; when `anchored_stage_code` set, show "scheduled at <stage>" (resolve label).
- `api/planTemplates.ts` (apply/preview/appliable); i18n en/ar.

## Acceptance
- Apply a published template end-to-end; `plan_activities` materialise with `source='template'` + `anchored_stage_code`; re-apply preserves manual rows; badges render; tsc + eslint clean; CI green.
