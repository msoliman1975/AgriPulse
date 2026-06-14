# PR-E5 — Seed a mango stage-anchored starter template + polish

**Spec:** `docs/proposals/phenology-spine-and-stage-aware-planning.md` §4, §5 (E5). **Depends on:** PR-E3, PR-E4, PR-D2.

## Goal
Ship a real, usable mango plan template that exercises stage anchoring end-to-end, plus final i18n/docs polish.

## Work
1. Seed (public migration/loader, idempotent) a **published** mango plan template targeting `crop_path = mango` with activities that exercise all three anchors:
   - `start`-anchored land-prep / planting (offset 0).
   - `milestone`-anchored items.
   - **`stage`-anchored** items keyed to seeded mango stages: e.g. **post-harvest nitrogen flush fertilization** anchored to `post_harvest_flush`; pre-flowering irrigation-withholding reminder anchored to `pre_flowering`; fruit-development fertigation anchored to `fruit_development`.
2. i18n en/ar for all new strings across Tracks A–E; verify RTL.
3. Docs: short "Phenology & Plan Templates" runbook (how stages auto-advance, how to lock, how to author/apply a stage-anchored template).
4. Final cross-track smoke (see master prompt §7) on agrosina-suez: a mango block auto-advances to today's stage, the rules engine sees soil/size, a mango tree fires, and applying the seeded template materialises stage-anchored `plan_activities`.

## Acceptance
- Seeded template appliable + applies on a mango block; stage-anchored dates correct for the season; i18n complete; runbook committed; full smoke green; CI green.
