# MissionAgre

Multi-tenant satellite-driven farm management SaaS for Egyptian agribusinesses.

## Read these first

Every change touches one of these. Read before opening a PR.

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — binding architecture decisions.
- [`docs/data_model.md`](docs/data_model.md) — binding schema, table-by-table.
- [`prompts/roadmap.md`](prompts/roadmap.md) — the six-prompt build plan.
- [`docs/decisions/`](docs/decisions) — ADRs for any new architectural decision.

The first two files are binding. If something you're about to write contradicts them, stop and open an ADR.

## Layout

```
backend/      Python 3.12 / FastAPI / Pydantic v2 / SQLAlchemy 2.x async — added in PR 2
frontend/     React 18 / TypeScript / Vite / Tailwind RTL — added in PR 3
tile-server/  TiTiler-based COG → XYZ/WMTS — added in PR 4
infra/        Terraform, Helm charts, ArgoCD ApplicationSets — added in PR 4
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

After PR 2 lands, the backend `pyproject.toml` will pin `uv` as the package manager. After PR 3, `pnpm` (via `corepack enable`) is required for the frontend — see [`frontend/README.md`](frontend/README.md).

## Local services (Postgres, Redis, Keycloak, MinIO)

Stateful dependencies run in containers via `infra/dev/compose.yaml`. Application code (Python, React) runs natively on the host. See ADR [`docs/decisions/0002-local-dev-services-in-compose.md`](docs/decisions/0002-local-dev-services-in-compose.md).

```bash
docker compose -f infra/dev/compose.yaml up -d        # start
docker compose -f infra/dev/compose.yaml down         # stop, keep volumes
docker compose -f infra/dev/compose.yaml down -v      # stop + wipe data
```

Endpoints when up: Postgres `localhost:5432`, Redis `localhost:6379`, Keycloak http://localhost:8080 (admin / admin), MinIO API http://localhost:9000 / console http://localhost:9001 (`missionagre` / `missionagre-dev`). Full table and dev credentials in [`backend/README.md`](backend/README.md). Tested with Rancher Desktop on Windows in dockerd (moby) mode; works on Docker Desktop and Podman compose too.

## Branching and commits

- Trunk-based: short-lived feature branches off `main`, squash-merged.
- Conventional Commits: `feat(iam): ...`, `fix(tenancy): ...`, `chore: ...`, `docs: ...`, `test: ...`, `ci: ...`, `refactor: ...`.
- Branch protection on `main` (configured in PR 5): one reviewer, all required checks green, linear history, conversations resolved, no force-push.

## CI

`.github/workflows/ci.yml` runs on every push and PR. Six required jobs:

- `pre-commit` — repo-wide hooks (ruff, black, prettier, gitleaks, etc.)
- `backend` — `uv sync --frozen`, ruff, black, mypy, import-linter, pytest (unit + integration)
- `frontend` — `pnpm install --frozen-lockfile`, eslint, tsc, prettier, vitest, build
- `helm` — `helm dependency build` + `helm lint` + `helm template` over every chart
- `infra-tf` — `terraform fmt -check -recursive` + `init -backend=false` + `validate`
- `containers` — matrix build of `api`, `workers`, `tile-server`, `frontend` images. PR runs build-only; merge to `main` pushes to `ghcr.io/msoliman1975/missionagre/<name>` tagged with the commit SHA + `latest`.

`.github/workflows/argocd-sync.yml` opens a follow-up PR after every successful `main` build, bumping `image.tag` in the dev overlay so ArgoCD picks up the new images.

Branch protection on `main` is set by `scripts/setup-branch-protection.sh` (re-run any time the required-checks list changes).

> Dependabot security advisories are active for this repo. PR-time `actions/dependency-review-action` requires GitHub Advanced Security; we can wire it back in once GHAS is enabled or the repo goes public.

## License

Private. All rights reserved.
