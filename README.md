# AgriPulse

Multi-tenant satellite-driven farm management SaaS for Egyptian agribusinesses, branded **AgriPulse** in the UI.

> New here? Read [`docs/onboarding.md`](docs/onboarding.md) â€” it walks you from `git clone` to "first sign-in works locally" in ~30 minutes, then points at the rest of this README for context.

## Read these first

Every change touches one of these. Read before opening a PR.

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) â€” binding architecture decisions.
- [`docs/data_model.md`](docs/data_model.md) â€” binding schema, table-by-table.
- [`prompts/roadmap.md`](prompts/roadmap.md) â€” the six-prompt build plan.
- [`docs/decisions/`](docs/decisions) â€” ADRs for any new architectural decision.

The first two files are binding. If something you're about to write contradicts them, stop and open an ADR.

## Status

Slices 1â€“5 are shipped â€” farms, imagery + indices, weather, alerts + notifications, recommendations, signals, dashboards. Slice 6 (Polish) is in progress: i18n completeness, runbooks, e2e suite. See [`prompts/roadmap.md`](prompts/roadmap.md) for the deliverable list.

## Modules

Backend domain modules and their on-call runbooks.

| Module | Reference | Runbook |
|---|---|---|
| `farms` | [`docs/modules/farms.md`](docs/modules/farms.md) | [`docs/runbooks/farms.md`](docs/runbooks/farms.md) |
| `imagery` + `indices` | (in `docs/ARCHITECTURE.md` Â§ 5â€“7) | [`docs/runbooks/imagery-pipeline-failure.md`](docs/runbooks/imagery-pipeline-failure.md) |
| `alerts` + `recommendations` | (data_model Â§ 10â€“11) | [`docs/runbooks/alert-evaluator-stuck.md`](docs/runbooks/alert-evaluator-stuck.md) |
| `notifications` | â€” | [`docs/runbooks/notifications.md`](docs/runbooks/notifications.md) |
| `tenancy` + `iam` | (data_model Â§ 3â€“4) | [`docs/runbooks/tenant-onboarding.md`](docs/runbooks/tenant-onboarding.md) Â· [`docs/runbooks/tenant-offboarding.md`](docs/runbooks/tenant-offboarding.md) |
| Platform infra | â€” | [`docs/runbooks/postgres-failover.md`](docs/runbooks/postgres-failover.md) Â· [`docs/runbooks/keycloak-reset.md`](docs/runbooks/keycloak-reset.md) Â· [`docs/runbooks/local-stack-bootstrap.md`](docs/runbooks/local-stack-bootstrap.md) Â· [`docs/runbooks/deploy-aws.md`](docs/runbooks/deploy-aws.md) |

## Layout

```
backend/      Python 3.12 / FastAPI / Pydantic v2 / SQLAlchemy 2.x async â€” added in PR 2
frontend/     React 18 / TypeScript / Vite / Tailwind RTL â€” added in PR 3
tile-server/  TiTiler-based COG â†’ XYZ/WMTS â€” added in PR 4
infra/        Terraform, Helm charts, ArgoCD ApplicationSets â€” added in PR 4
docs/         Binding docs and ADRs
prompts/      Claude Code session prompts and the roadmap
scripts/      Operational scripts (tenant migration runner, branch-protection setup, ...)
.github/      CI workflows, CODEOWNERS, issue/PR templates, Dependabot
```

## Local setup (PR 1)

You only need this much until backend/frontend land.

```bash
# 1. Python 3.12 (for pre-commit and later for the backend)
python --version  # 3.12.x

# 2. Install pre-commit and wire it in
pip install --user pre-commit==3.8.0
pre-commit install

# 3. Verify hooks
pre-commit run --all-files
```

After PR 2 lands, the backend `pyproject.toml` will pin `uv` as the package manager. After PR 3, `pnpm` (via `corepack enable`) is required for the frontend â€” see [`frontend/README.md`](frontend/README.md).

## Local services (Postgres, Redis, Keycloak, MinIO)

Stateful dependencies run in containers via `infra/dev/compose.yaml`. Application code (Python, React) runs natively on the host. See ADR [`docs/decisions/0002-local-dev-services-in-compose.md`](docs/decisions/0002-local-dev-services-in-compose.md).

```bash
docker compose -f infra/dev/compose.yaml up -d        # start
docker compose -f infra/dev/compose.yaml down         # stop, keep volumes
docker compose -f infra/dev/compose.yaml down -v      # stop + wipe data
```

Endpoints when up: Postgres `localhost:5432`, Redis `localhost:6379`, Keycloak http://localhost:8080 (admin / admin), MinIO API http://localhost:9000 / console http://localhost:9001 (`agripulse` / `agripulse-dev`). Full table and dev credentials in [`backend/README.md`](backend/README.md). Tested with Rancher Desktop on Windows in dockerd (moby) mode; works on Docker Desktop and Podman compose too.

## Branching and commits

- Trunk-based: short-lived feature branches off `main`, squash-merged.
- Conventional Commits: `feat(iam): ...`, `fix(tenancy): ...`, `chore: ...`, `docs: ...`, `test: ...`, `ci: ...`, `refactor: ...`.
- Branch protection on `main` (configured in PR 5): one reviewer, all required checks green, linear history, conversations resolved, no force-push.

## CI

`.github/workflows/ci.yml` runs on every push and PR. Six required jobs:

- `pre-commit` â€” repo-wide hooks (ruff, black, prettier, gitleaks, etc.)
- `backend` â€” `uv sync --frozen`, ruff, black, mypy, import-linter, pytest (unit + integration)
- `frontend` â€” `pnpm install --frozen-lockfile`, eslint, tsc, prettier, vitest, build
- `helm` â€” `helm dependency build` + `helm lint` + `helm template` over every chart
- `infra-tf` â€” `terraform fmt -check -recursive` + `init -backend=false` + `validate`
- `containers` â€” matrix build of `api`, `workers`, `tile-server`, `frontend` images. PR runs build-only; merge to `main` pushes to `ghcr.io/msoliman1975/agripulse/<name>` tagged with the commit SHA + `latest`.

`.github/workflows/argocd-sync.yml` opens a follow-up PR after every successful `main` build, bumping `image.tag` in the dev overlay so ArgoCD picks up the new images.

Branch protection on `main` is set by `scripts/setup-branch-protection.sh` (re-run any time the required-checks list changes). The script targets the modern Rulesets API.

> âš ï¸ GitHub's free tier blocks both classic branch protection and Rulesets on private repos. The script is ready to run; applying it requires either upgrading to GitHub Pro/Team or making the repo public. Until then, `main` is protected by convention only â€” squash-merge and one reviewer enforced through PR-author discipline.

> Dependabot security advisories are active for this repo. PR-time `actions/dependency-review-action` requires GitHub Advanced Security; we can wire it back in once GHAS is enabled or the repo goes public.

## License

Private. All rights reserved.
