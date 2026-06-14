# PR-E1 — Plan-template data model (with stage anchoring)

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §1.4, §4; and `docs/proposals/plan-templates-implementation.md` §1. **Depends on:** PR-A1; re-check public + tenant heads (A1 added a public migration, B1 a tenant migration — chain off the **current** heads).

## Goal
Create the plan-template catalog tables + tenant plan-activity columns, **extending** the parked design so activities can anchor to a phenology **stage**.

## Public migration (chain off current public head)
- **`plan_templates`** — `id`, `code` (unique), `name`, `crop_path` (text, btree index), `crop_id` (denormalised first segment), `country` (null), `region` (null), `description`, `status` (`draft|published|archived`), timestamps.
- **`plan_template_milestones`** — `id`, `template_id` (cascade), `code` (unique/template), `name`, `day_from_start` (≥0), `sort_order`.
- **`plan_template_activities`** — `id`, `template_id` (cascade), `activity_type`, **`anchor` (`start|milestone|stage`)**, `milestone_id` (null; required when anchor=milestone), **`stage_code` (null; required when anchor=stage)**, `offset_days` (int, negatives ok), `duration_days` (≥1), `product_name`/`dosage`/`notes`/`start_time` (null), `sort_order`.
  - CHECK: `anchor=milestone ⇒ milestone_id NOT NULL`; `anchor=stage ⇒ stage_code NOT NULL`; resolved day for milestone-anchored ≥ 0.

## Tenant migration (chain off current tenant head)
- **`plan_activities`** add: `source` (`manual|template|recommendation`, default `manual`), `applied_template_id` (null), `template_activity_id` (null), **`anchored_stage_code` (null text)**; partial index `(plan_id, block_id, applied_template_id) WHERE applied_template_id IS NOT NULL`.
- **`vegetation_plans`** add: `applied_template_id` (null).
- All nullable/defaulted → data-safe; provide data-safe downgrades.

## Backend
- Models + repo + schemas for the 3 public tables and the tenant column adds. No business logic yet (that's E2).

## Tests / acceptance
- migrations roundtrip (public + tenant); models load; CHECK constraints enforced; CI green.
