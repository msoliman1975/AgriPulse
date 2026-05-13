# New-engineer onboarding

A walk-through that gets you from `git clone` to "I shipped a one-line
fix locally and tests pass." Roughly 30 minutes if Docker, Python, and
Node are already installed.

The platform is opinionated about its layout â€” read this once before
your first change so you're not fighting conventions.

---

## Day 0 â€” environment

What you need (versions are floors, not ceilings):

- Python 3.12 (`backend/`)
- Node 20 + pnpm via `corepack enable` (`frontend/`)
- Docker Desktop / Rancher Desktop / Podman (for the local stack)
- A POSIX-y shell. Windows works via Git Bash or WSL2; pure cmd has
  edge-case issues with the dev_bootstrap script.

Optional but recommended:

- VS Code with the recommended extensions in `.vscode/extensions.json`.
- A Sentinel Hub account (for end-to-end imagery testing). Without
  credentials the imagery pipeline records a synthetic failed job â€”
  enough to smoke-test UI error states.

---

## Day 1 â€” local stack up

```bash
git clone <repo-url> AgriPulse
cd AgriPulse

# Install pre-commit hooks (linters block bad commits before they push)
pip install --user pre-commit==3.8.0
pre-commit install

# Bring up Postgres / Redis / Keycloak / MinIO / MailHog
docker compose -f infra/dev/compose.yaml up -d

# Bootstrap the dev tenant + seed crops + create dev@agripulse.local
python backend/scripts/dev_bootstrap.py
```

The bootstrap script is idempotent â€” re-run it any time you wipe the
DB.

Full step-by-step including troubleshooting:
[`docs/runbooks/local-stack-bootstrap.md`](runbooks/local-stack-bootstrap.md).

### Backend

```bash
cd backend
# Use the pre-built venv; uv on Windows hits a TLS-trust bug.
.venv/Scripts/uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000   # Windows
# .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000        # macOS/Linux

# In separate terminals:
.venv/.../celery -A workers.celery worker -Q light --loglevel=info
.venv/.../celery -A workers.celery worker -Q heavy --loglevel=info
.venv/.../celery -A workers.beat.main beat --loglevel=info
```

Tile-server runs in compose alongside the dependencies; you don't
typically restart it.

### Frontend

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev   # â†’ http://localhost:5173
```

Sign in as `dev@agripulse.local` (password also `dev`). You'll land
on the Insights dashboard for the seeded tenant.

---

## Day 2 â€” find your way around

### Backend layout

```
app/
  core/               # logging, settings, app factory
  modules/            # one folder per domain â€” farms, imagery, alerts, â€¦
    <module>/
      models.py       # SQLAlchemy ORM
      repository.py   # async DB access (PRIVATE per import-linter)
      service.py      # public Protocol + impl + factory
      router.py       # FastAPI routes (PRIVATE)
      schemas.py      # Pydantic request/response (PRIVATE)
      events.py       # event types other modules subscribe to
      tasks.py        # Celery tasks
      errors.py       # APIError subclasses
  shared/             # cross-cutting code (db, auth, conditions, eventbus, â€¦)
migrations/
  public/             # alembic head for the platform schema
  tenant/             # alembic head applied to every tenant_<uuid>
workers/              # Celery factories + beat schedule
tests/                # mirrors app/ layout
```

`import-linter` enforces "internals are private" â€” modules import each
other through `service` / `events` / `snapshot`, never through
`repository` / `models` / `router` / `schemas`. The contract is in
`pyproject.toml`. Run `lint-imports` before a PR.

### Frontend layout

```
src/
  api/                # axios clients per backend module
  queries/            # TanStack Query hooks
  modules/<m>/pages/  # page-level components
  modules/<m>/components/   # local presentational components
  shell/              # AppShell, Header, SideNav, drawers
  hooks/              # cross-cutting hooks (useActiveFarmId, useDateLocale, â€¦)
  rbac/               # capability mirror of the backend yaml
  i18n/locales/{en,ar}/  # one JSON namespace per backend module
```

### Where to look first

- New backend feature â†’ `app/modules/<m>/service.py` and `models.py`.
  Repository + router follow the existing patterns.
- New frontend page â†’ `modules/<m>/pages/`, plus an entry in `App.tsx`
  and `shell/SideNav.tsx`. i18n strings go in
  `i18n/locales/{en,ar}/<m>.json`.
- New event subscriber â†’ see `notifications/subscribers.py` for the
  established pattern (savepoint-around-INSERT, NullPool, idempotent
  registration).

---

## Day 3 â€” first PR

Pick something small from the issue tracker labelled
`good-first-issue`. The flow:

```bash
git checkout -b feat/<scope>/<short-desc>

# Make the change. Tests for it should live next to the file you
# touched (tests/unit/... or tests/integration/...).

# Validate locally
cd backend && .venv/.../python -m pytest -x --no-cov tests/unit
cd backend && .venv/.../lint-imports
cd frontend && pnpm typecheck && pnpm test -- --run

# Conventional commit
git commit -m "feat(<scope>): <one-line summary>"
git push -u origin HEAD
gh pr create --fill   # or via the GitHub UI
```

CI runs the same checks plus a build matrix. Six required jobs; see
the README for what each does.

---

## Day 4 â€” Slice culture

The codebase has shipped six "slices" so far. Each one is bounded by a
roadmap prompt and ends in a hard human gate. We don't half-ship â€”
either a slice is "done" (the gate signal in the roadmap is true) or it
isn't, and we don't move to the next.

Reasons this matters:

- The architecture only stays coherent because each slice gets reviewed
  end-to-end.
- The gate signal also documents what "done" looks like for every
  feature â€” the recommendations slice's gate is "a daily eval produces
  one rec for a NDVI-dropping block; tree path renders in en + ar."

---

## Asking for help

- `prompts/roadmap.md` â€” what's next + why.
- `docs/decisions/` â€” every non-obvious "why didn't we just" answer.
- `docs/runbooks/` â€” operational fixes, including for things you'll
  break locally.
- The `#agripulse-backend` and `#agripulse-frontend` channels.

If a runbook step is wrong or stale, fix it in your PR. Documentation
that drifts is worse than missing.
