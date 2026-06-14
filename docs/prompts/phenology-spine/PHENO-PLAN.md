# MASTER PROMPT — Phenology Spine & Stage-Aware Planning (implement → test → deploy, end-to-end)

You are implementing a multi-PR initiative in the AgriPulse repo (`C:\Users\mosoliman\projects\MissionAgre`). Your job: **implement, test, and deploy all of it in one session**, autonomously, in dependency order, verifying each step before moving on.

## Read first (authoritative spec)
1. **`docs/proposals/phenology-spine-and-stage-aware-planning.md`** — the full design. This is the source of truth; the per-PR prompts below are execution slices of it. If a per-PR prompt and the proposal disagree, the proposal wins (and flag it).
2. **`docs/proposals/plan-templates-implementation.md`** — the parked plan-templates design that Track E un-parks and extends (anchor gains `stage`).
3. Memory files (already in context): `project_mango_reco_extension` (locked decisions), `project_plan_templates`, `project_recommendations_module`, `project_crop_taxonomy`, `project_ci_fully_green` (data-safe-downgrade rules), `feedback_alembic_asyncpg_gotchas`, `feedback_windows_dev_env`, `feedback_dev_stack_no_reload`, `project_farm_mgmt_ux_and_prod_test` (deploy + prod-test recipe).

## The four locked decisions (do not re-litigate)
1. Cycle behaviour reuses existing `Crop.is_perennial`; **mango = calendar-DOY**, not GDD.
2. **Option 1** — phenology is the canonical timing spine; plan-template activities anchor to stage codes.
3. Stages + size classes are platform-curated defaults with variety/strain overrides (same governance as thresholds).
4. Auto-advance honours a per-block **lock flag** `BlockCrop.growth_stage_locked`.

## Per-PR prompts (execute in this order)
| PR | File | Depends on |
|----|------|-----------|
| A1 | `PR-A1-taxonomy-shape-and-sizes.md` | 0031 head |
| A2 | `PR-A2-seed-mango-potato.md` | A1 |
| B1 | `PR-B1-block-size-and-lock.md` | 0039 head |
| B2 | `PR-B2-block-frontend.md` | B1, A2 |
| C1 | `PR-C1-auto-advance-task.md` | A2, B1 |
| D1 | `PR-D1-engine-block-fields.md` | B1 |
| D2 | `PR-D2-mango-trees.md` | A2, D1 |
| E1 | `PR-E1-plan-template-datamodel.md` | A1 (+ public/tenant heads from A1/B1) |
| E2 | `PR-E2-apply-engine-stage-anchor.md` | E1, A2 |
| E3 | `PR-E3-platform-authoring-ui.md` | E2 |
| E4 | `PR-E4-tenant-apply-wizard.md` | E2 |
| E5 | `PR-E5-seed-template-polish.md` | E3, E4, D2 |

**Critical ordering:** Track A is the hard prerequisite for C, D2, and E (all consume *resolved* stages). B1 (lock flag) gates C1. Do A fully first. Then B/C/D can interleave. Then E. **Migrations are created LAST within each PR and chained off the then-current head** — when you reach E1, re-check the live head (A1 added a public migration; B1 added a tenant migration) and rebase `down_revision` accordingly.

## Standard workflow for EVERY PR
1. **Branch/worktree.** Create a feature branch off fresh `main` (never commit to `main` directly). For parallelizable PRs use a git worktree (`MissionAgre-<short>`); symlink `frontend/node_modules` from the main checkout if you touch frontend.
2. **Implement** exactly the slice in the PR prompt; match surrounding code style.
3. **Migrations (if any):** chain off the current head; `alembic.ini` and migration files must be **ASCII** (cp1252 locale — see `feedback_windows_dev_env`). Provide **data-safe downgrades** (the CI migration-roundtrip tests run up *and* down on a shared DB — see `project_ci_fully_green`). asyncpg raw SQL on nullable text needs `CAST` (see `feedback_alembic_asyncpg_gotchas`).
4. **Local verify:**
   - Backend: `./scripts/dev-stack.ps1 -Phase api` after backend edits (uvicorn runs WITHOUT --reload — changes don't take effect otherwise). Run the new module's pytest. Run alembic upgrade head + downgrade roundtrip locally if you added a migration.
   - Frontend: tsc + eslint. Tools may need `node node_modules/typescript/bin/tsc` / `node node_modules/eslint/bin/eslint.js` if `.bin` shims are missing. Vite hot-reloads but kill `:5173` if a brand-new page doesn't render.
   - Lint/format/type/import-linter must pass (mirror CI jobs #209-style).
5. **Commit** (git email `msoliman_75@hotmail.com`; `--reset-author` if work email auto-attaches). Push, open PR with `gh`, ensure CI green, squash-merge.
6. **Deploy** (only after merge to main):
   - Backend/migration PRs **and** frontend PRs: bump the **hetzner overlay** image tag(s) to the **merge-commit SHA** → ArgoCD auto-syncs. Backend changes bump api+workers and run the PreSync alembic migrate job; frontend bumps frontend. **Do NOT bump immediately after squash-merge** — wait for the containers job to publish images, or repoint to the bump-commit SHA, else ImagePullBackOff (see `feedback_overlay_bump_after_merge`). The argocd-sync workflow races overlay pushes → expect non-fast-forward; cherry-pick the bump onto fresh main.
7. **Prod-verify** on the live `agrosina-suez` farm:
   - Get a token via **direct-grant** (Playwright OIDC is broken): `curl --ssl-no-revoke -X POST https://keycloak.agripulse.cloud/realms/agripulse/protocol/openid-connect/token -d grant_type=password -d client_id=agripulse-api -d username=<u> -d password=<p> -d scope=openid`. API base `https://api.agripulse.cloud/api/v1`. Netskope → `--ssl-no-revoke` on every curl.
   - Hit the endpoints this PR added/changed and assert 200 + expected payload. For migrations, confirm `alembic head` advanced (PreSync job `agripulse-api-agripulse-api-migrate`).
   - SSH for DB checks: `ssh root@167.233.98.216` (key `~/.ssh/id_ed25519`) → `kubectl -n agripulse exec -c postgres agripulse-pg-1 -- psql -U postgres -d agripulse -c "…"`. Tenant schema = `tenant_` + tenant_id without dashes. agrosina-suez tenant `019eafdc-242c-7320-948e-13490efc67dd`, farm `019eb024-2d6a-782e-a00e-3f0c432459a3`.
8. **Record** progress in the `project_mango_reco_extension` memory after each PR merges (commit SHA + deploy state).

## Guardrails / honesty
- If tests fail, fix the root cause — don't skip hooks (`--no-verify`) or weaken assertions.
- Report deploy/verify outcomes faithfully (show the curl status / kubectl output). If a step is skipped or blocked, say so.
- Confirm-before-destructive: never run destructive DB ops on prod without showing the plan first.
- After the full run, post a summary: PRs merged (SHAs), what's live, what (if anything) is deferred, and the prod-verify evidence per track.

## Definition of done
All 13 PRs merged to `main`, deployed to Hetzner, and verified live: phenology stages seeded + auto-advancing on agrosina-suez blocks (or a seeded mango block), soil + canopy-size readable by the rules engine, a corrected mango ruleset firing, and a stage-anchored plan template that applies and materialises `plan_activities` with `anchored_stage_code`.
