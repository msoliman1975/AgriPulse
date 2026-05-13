# CD-2 — Repo-root prod-shaped docker-compose for local smoke

[Shared preamble — see README.md]

## Goal
Today `infra/dev/compose.yaml` runs the **infra services** (Postgres, Redis, MinIO, MailHog, Keycloak) for local dev, but the app itself is run with `uvicorn --reload` from the host venv. That diverges from what ships to EKS. This PR adds a repo-root `docker-compose.yaml` that runs the four built images (api, worker-light, worker-heavy, beat, frontend) against the infra compose, so a developer can reproduce the EKS shape on their laptop.

## Files to change
- `docker-compose.yaml` — new, at repo root.
- `Makefile` — add `make smoke` target invoking `docker compose up --build`. Create the file if it doesn't exist.
- `README.md` — short "Running the prod-shaped stack locally" subsection under Development.

## Tasks
1. Author `docker-compose.yaml` at the repo root. It should:
   - Use `include:` to layer on top of `infra/dev/compose.yaml` (compose v2.20+ syntax).
   - Define five backend services from `backend/Dockerfile`: `api`, `worker-light`, `worker-heavy`, `beat`, `migrate`. All five reference the same image (build context `backend/`) and override `command:` per service. `migrate` runs `alembic upgrade head` then exits 0.
   - Define `frontend` from `frontend/Dockerfile`.
   - Healthchecks: `/health` for api (curl in the image — confirm `curl` is installed; if not, use `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"`), `celery -A workers.light.main inspect ping` for workers.
   - `depends_on:` with `condition: service_completed_successfully` on `migrate` for api/workers/beat; `condition: service_healthy` on postgres/redis from the infra compose.
   - Shared env block via `env_file: [./backend/.env]` (host file, not baked into image).
   - Frontend served on host port 8080; api on 8000; tile-server on 8001 if you include it (optional in this PR).
2. Verify `docker compose -f docker-compose.yaml up --build` brings the stack up cleanly on a fresh checkout, and `curl localhost:8000/health` returns 200, and `curl localhost:8080` returns the SPA index.
3. Add `make smoke` and `make smoke-down` targets to Makefile.
4. README subsection: 6–10 lines, just the commands.

## Out of scope
- Don't add the tile-server service unless trivial.
- Don't modify `infra/dev/compose.yaml`.
- Don't change Dockerfiles.

## Definition of done
- `make smoke` brings the stack up; `/health` returns 200; SPA loads.
- `make smoke-down` tears it cleanly.
- Migrations run once at startup and the api waits for them.
- PR description includes the smoke commands and a screenshot or text-only confirmation of `/health` + SPA load.
