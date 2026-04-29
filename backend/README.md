# MissionAgre backend

FastAPI service for MissionAgre.

## Local setup

```bash
# 1. Install uv (https://docs.astral.sh/uv/), then sync the project
uv sync --extra dev

# 2. Configure environment
cp .env.example .env
# Edit .env with your local Postgres/Redis/Keycloak URLs

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

The thirteen modules under `app/modules/` are listed in `docs/ARCHITECTURE.md` § 6.
Cross-module imports of internals are forbidden — enforced by `import-linter`.
