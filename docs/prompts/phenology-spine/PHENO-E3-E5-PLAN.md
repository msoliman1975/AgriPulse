# MASTER PROMPT — Finish Track E (PR-E3 → E4 → E5), implement → test → deploy → verify

You are finishing the **plan-templates** track of the Phenology Spine initiative in the AgriPulse repo (`C:\Users\mosoliman\projects\MissionAgre`). Tracks A–D and PR-E1/E2 are **already merged**. Your job: implement, test, merge, and finally **deploy + prod-verify** the last three PRs (E3, E4, E5) — end to end, autonomously, in order.

## Read first
1. `docs/proposals/phenology-spine-and-stage-aware-planning.md` — §4 (plan-template integration) + §5 (E3/E4/E5 slices). Source of truth.
2. `docs/proposals/plan-templates-implementation.md` — the original (un-parked) authoring + apply-wizard design; §3 (API) and §4 (frontend).
3. `docs/prompts/phenology-spine/PR-E3-platform-authoring-ui.md`, `PR-E4-tenant-apply-wizard.md`, `PR-E5-seed-template-polish.md` — the per-PR specs.
4. Memory (in context): `project_mango_reco_extension` (read first — has the locked decisions, what's shipped, and the Track-E state), `project_ci_fully_green`, `feedback_alembic_asyncpg_gotchas`, `feedback_windows_dev_env`, `feedback_dev_stack_no_reload`, `feedback_playwright_stale_vite`, `project_farm_mgmt_ux_and_prod_test` (deploy + prod-test recipe), `feedback_overlay_bump_after_merge`, `project_kc_provisioning_incident_2026_06_14` (KC admin works now; tenant-token note).

## What already exists (built in E1/E2 — build on it, don't redo)
- Module `backend/app/modules/plan_templates/` with: models (public `plan_templates` / `plan_template_milestones` / `plan_template_activities`; anchor=start|milestone|stage), `repository.py` (catalog reads + `resolve_phenology_for_path` + tenant apply queries), `apply.py` (`resolve_schedule` — start/milestone/stage date math), `service.py` (`list_appliable`/`preview`/`apply`), `schemas.py` (incl. `PlanTemplateWriteRequest` authoring shape + `AppliableTemplate`/preview/apply shapes), `errors.py`, `router.py` (tenant endpoints: GET `/v1/plan-templates/appliable`, POST `/{id}/preview`, POST `/{id}/apply`).
- Migrations: public **0034**, tenant **0041** (already applied in CI/testcontainers; on prod only after Track-E deploy).
- Caps already registered: `plan_template.read` + `plan_template.apply` (farm), `plan_template.manage` (platform).
- `GET /v1/crops/resolved-taxonomy?crop_path=` (Track A) returns resolved phenology stages — the **stage picker source** for E3.

## PR-E3 — Platform authoring API + `/platform/plan-templates` UI
Spec: `PR-E3-platform-authoring-ui.md` + proposal §4.3.
**Backend (cap `plan_template.manage`, platform):** add authoring endpoints to the plan_templates router — `GET /v1/plan-templates` (list, status filter), `GET /{id}` (full tree), `POST /v1/plan-templates` + `PUT /{id}` (**whole-tree create/replace** atomically using `PlanTemplateWriteRequest`: header + milestones + activities; resolve milestone `code`→id; derive `crop_id` from path's first segment), `POST /{id}/publish` + `/archive`, `DELETE` (soft-archive). Validation: stage-anchored activities' `stage_code` must exist in the **resolved** phenology stages for the template's `crop_path` (call the same catalog resolution as E2 → `PlanTemplateValidationError` 422); milestone-anchored need a milestone code that exists in the payload. Add repo write methods (insert/replace tree, publish/archive). Mount these on the existing router (platform-scoped, no `_ensure_tenant`).
**Frontend `/platform/plan-templates`:** list page (crop path, status, #applied) + editor — header with the cascading **crop→variety→strain picker** that emits `crop_path` (reuse `CropPathFilter`/`CropPicker`, depth-aware via `classification_depth`), region/country, name; milestones editor (name + day_from_start); activities editor with **anchor dropdown Start / Milestone / Stage** — when **Stage**, a stage picker populated from `GET /v1/crops/resolved-taxonomy?crop_path=<chosen>`; offset_days, duration_days, defaults; **timeline/Gantt preview** of resolved days; publish/archive. `api/planTemplates.ts`; i18n en/ar. Add to `/platform` nav (PlatformAdmin only).
**Tests:** backend whole-tree PUT round-trip + stage_code validation (422); frontend tsc + eslint (+ a component/test if the page has logic worth covering).

## PR-E4 — Tenant apply wizard + board integration
Spec: `PR-E4-tenant-apply-wizard.md` + proposal §4.2.
**Frontend only** (backend endpoints exist from E2): "Apply template" entry on the Plan/board page (and farm context on `/labs/map`) → 4-step wizard: (1) pick template (appliable matches first, region hint) → (2) pick blocks (pre-checked matching-crop) + per-block **start date** (default `planting_date`) → (3) season label/year (derived, editable) → (4) **preview schedule** (show stage-anchored dates + any skipped) → confirm → apply. Board: "from template" badge on `source='template'` rows; when `anchored_stage_code` set, show "scheduled at <stage>" (resolve label). `api/planTemplates.ts` (appliable/preview/apply); i18n en/ar. tsc + eslint clean.

## PR-E5 — Seed starter template + polish + deploy + verify
Spec: `PR-E5-seed-template-polish.md`.
- Seed (public migration/loader, idempotent) a **published** mango plan template `crop_path=mango` exercising all 3 anchors: `start` land-prep; a `milestone`; **stage-anchored** items — e.g. post-harvest N fertilization → `post_harvest_flush`, pre-flowering irrigation-withhold reminder → `pre_flowering`, fruit-development fertigation → `fruit_development`. (Stage codes must match migration 0033's mango stages.)
- i18n en/ar for all new strings (Tracks E3–E5); verify RTL.
- Short runbook doc: how to author + apply a stage-anchored template.
- This is the PR that **deploys all of Track E** — see Deploy below.

## Standard workflow per PR (same as Tracks A–D)
1. Branch off fresh `main` (`feat/pheno-e3-…`, etc.); never commit to main. Use a worktree if convenient; symlink `frontend/node_modules` from main checkout for FE PRs.
2. Implement the slice.
3. **Backend verify:** `./scripts/dev-stack.ps1 -Phase api` after backend edits (uvicorn has no --reload). Run `.venv/Scripts/ruff.exe check`, `black`, `mypy`, `lint-imports`, and `pytest` for the touched areas. Integration tests use testcontainers (Docker must be up). Migrations: ASCII files, chain off current head (re-check head before writing — E1/E2 added public 0034 / tenant 0041), data-safe downgrades.
4. **Frontend verify:** tsc + eslint. Tools may need `node node_modules/typescript/bin/tsc` / `node node_modules/eslint/bin/eslint.js` if `.bin` shims are missing. Kill `:5173` if a new page doesn't render (stale-vite gotcha). Optional: Playwright smoke (OIDC automation is broken — see prod-test note).
5. Commit (git email `msoliman_75@hotmail.com`; `--reset-author` if work email attaches), push, `gh pr create`, ensure **all CI green**, squash-merge, sync main.

## Deploy + prod-verify (do this once, at the end, after E5 merges)
Deploy E3+E4+E5 together (and E1+E2, which were merged but **not yet deployed**) in one overlay bump:
1. After E5 merges, wait for the **merge commit's** CI `containers (api/workers/frontend)` jobs to publish images (don't bump before — see `feedback_overlay_bump_after_merge`).
2. Bump `infra/argocd/overlays/hetzner/values.yaml` → set `api`, `workers`, **and `frontend`** tags to the E5 merge SHA. Commit `[skip ci]`; on push rejection `git pull --rebase` then push (argocd-sync race).
3. Force ArgoCD: `ssh root@167.233.98.216` → `kubectl -n argocd annotate application api-hetzner workers-hetzner frontend-hetzner argocd.argoproj.io/refresh=hard --overwrite`. Wait for sync to the bump SHA + the PreSync `migrate` / `migrate_tenants` job to run **public 0034 + tenant 0041**.
4. **Verify on prod (agrosina-suez):**
   - Tenant token via direct-grant (Playwright OIDC broken): `curl --ssl-no-revoke -X POST https://keycloak.agripulse.cloud/realms/agripulse/protocol/openid-connect/token -d grant_type=password -d client_id=agripulse-api -d username=<u> -d password=<p> -d scope=openid` (ask the user for a TENANT user's creds — `dev@agripulse.local` is PlatformAdmin-only and can't hit the tenant apply endpoints; PlatformAdmin CAN hit the E3 authoring endpoints). API base `https://api.agripulse.cloud/api/v1`; Netskope → `--ssl-no-revoke` on every curl.
   - Confirm migrations: `ssh … kubectl -n agripulse exec -c postgres agripulse-pg-1 -- psql -U postgres -d agripulse -tA -c "SELECT version_num FROM public.alembic_version"` = 0034; tenant schema `tenant_019eafdc242c7320948e13490efc67dd` has the `plan_activities.source/applied_template_id/anchored_stage_code` columns.
   - Seed template present: `GET /v1/plan-templates` (PlatformAdmin token) shows the mango template, published.
   - Apply it end-to-end on a mango block (tenant token): `GET /plan-templates/appliable?farm_id=…` → `POST /{id}/apply` → confirm `plan_activities` rows with `source='template'` + `anchored_stage_code`. (agrosina-suez tenant `019eafdc-242c-7320-948e-13490efc67dd`, farm `019eb024-2d6a-782e-a00e-3f0c432459a3`, mango blocks AG-R0x-C0x.)
   - Frontend: hard-refresh `https://app.agripulse.cloud/platform/plan-templates` (authoring) and the tenant apply wizard; confirm the new served `assets/index-*.js` hash changed.
5. Record the result in the `project_mango_reco_extension` memory (SHAs + deploy/verify evidence) and mark the **whole phenology spine COMPLETE**.

## Guardrails / honesty
- Don't skip hooks or weaken assertions; fix root causes. Report deploy/verify outcomes faithfully (show curl status + kubectl output). If blocked on tenant creds for the final apply-verify, ask the user (one question) rather than guessing.
- If a migration head moved since this prompt was written, rebase `down_revision` onto the live head.

## Definition of done
E3+E4+E5 merged, deployed to Hetzner (api+workers+frontend on the E5 SHA, public 0034 + tenant 0041 applied), and verified live: a platform admin can author/publish a stage-anchored mango template, and a tenant can apply it to a mango block producing `plan_activities` with `source='template'` + `anchored_stage_code`. The phenology-spine initiative (Tracks A–E) is then complete.
