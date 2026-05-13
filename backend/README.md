# AgriPulse backend

FastAPI service for AgriPulse.

## Local services

Postgres, Redis, Keycloak, and MinIO run in containers via the dev compose
stack; the Python backend, Celery workers, and the React frontend all run
natively against them. See ADR
[`docs/decisions/0002-local-dev-services-in-compose.md`](../docs/decisions/0002-local-dev-services-in-compose.md)
for context.

```bash
# from the repo root
docker compose -f infra/dev/compose.yaml up -d         # bring services up
docker compose -f infra/dev/compose.yaml ps            # verify health
docker compose -f infra/dev/compose.yaml logs -f keycloak  # tail one service
docker compose -f infra/dev/compose.yaml down          # stop, keep volumes
docker compose -f infra/dev/compose.yaml down -v       # stop AND wipe data
```

| Service   | URL                       | Credentials                     |
|-----------|---------------------------|---------------------------------|
| Postgres  | `localhost:5432`          | `agripulse / agripulse`     |
| Redis     | `localhost:6379`          | (no auth in dev)                |
| Keycloak  | http://localhost:8080     | admin: `admin / admin`          |
| MinIO API | http://localhost:9000     | `agripulse / agripulse-dev` |
| MinIO UI  | http://localhost:9001     | `agripulse / agripulse-dev` |

The stack pre-provisions a Keycloak realm `agripulse` with client
`agripulse-api` and a dev user `dev@agripulse.local` (password `dev`),
and creates two MinIO buckets (`agripulse-imagery`, `agripulse-uploads`).

> Tested with Rancher Desktop in dockerd (moby) mode on Windows; works the
> same on Docker Desktop and on Podman with compose support.

## Local setup

```bash
# 1. Install uv (https://docs.astral.sh/uv/), then sync the project
uv sync --extra dev

# 2. Configure environment
cp .env.example .env
# .env defaults already match infra/dev/compose.yaml â€” edit only if you
# changed ports or credentials.

# 3. Run migrations against the public schema
uv run alembic -c migrations/public/alembic.ini upgrade head

# 4. Start the API
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests

```bash
uv run pytest                    # unit + integration (uses testcontainers)
uv run pytest -m "not integration"  # unit only
```

## Lint and type-check

```bash
uv run ruff check .
uv run black --check .
uv run mypy app
uv run lint-imports
```

## Layout

```
app/
  core/        FastAPI app factory, settings, logging, observability, errors
  shared/      Cross-module utilities (db, auth, rbac, eventbus, correlation)
  modules/     One folder per domain module; only service.py and events.py are public
workers/       Celery entrypoints (light, heavy queues + beat)
migrations/    Alembic environments (public + tenant)
scripts/       Operational scripts (e.g., migrate_tenants.py)
tests/         unit/ + integration/ + e2e/
```

The thirteen modules under `app/modules/` are listed in `docs/ARCHITECTURE.md` Â§ 6.
Cross-module imports of internals are forbidden â€” enforced by `import-linter`.
