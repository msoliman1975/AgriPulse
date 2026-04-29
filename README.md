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

`.github/workflows/ci.yml` runs `pre-commit` on every push and PR. Backend, frontend, helm, and container-build jobs are stubbed in PR 1 and filled in by PRs 2, 3, 4, and 5 respectively.

## License

Private. All rights reserved.
