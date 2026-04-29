# ADR 0002 — Local development runs services in containers, app code natively

**Status:** Accepted
**Date:** 2026-04-28
**Authors:** @msoliman1975

## Context

`docs/ARCHITECTURE.md` § 3.2 commits the production deployment topology
(EKS, CloudNativePG, External Secrets, ArgoCD) but says nothing about how
an engineer brings the platform up on a laptop. Without an explicit local-
dev arrangement, drift is inevitable: each engineer invents their own
setup, the values in `backend/.env.example` don't match anything anyone
runs, and onboarding requires reading every component's docs separately.

`backend/.env.example` already assumes Postgres on `localhost:5432`,
Redis on `localhost:6379`, and a Keycloak issuer URL — that is, it
shipped a "services on the host network" assumption without the
companion runtime to satisfy it. This ADR makes that assumption
explicit and provides the runtime.

The integration-test suite uses `testcontainers` to spin up ephemeral
Postgres+TimescaleDB and Redis instances per session. That is correct
for tests (isolation, ephemeral) but wrong for everyday development:
you cannot iterate on a Keycloak realm or populate a tenant DB if the
container disappears every time `pytest` finishes.

## Decision

Local development uses a **split runtime**:

1. **Stateful dependencies run in containers** via
   `infra/dev/compose.yaml`: Postgres+TimescaleDB+PostGIS, Redis,
   Keycloak, and MinIO. The container engine is whatever the engineer
   has installed — Docker Desktop, Rancher Desktop in dockerd (moby)
   mode, or Podman with compose support. The compose file uses only
   features available in all three.
2. **Application code runs natively** on the host (Windows, macOS,
   Linux, or WSL2): the FastAPI service via `uv run uvicorn`, Celery
   workers via `uv run celery`, and the React frontend (when it lands)
   via `pnpm dev`. Hot reload, debuggers, and profilers all behave
   the way they normally do — there is no in-container edit loop.
3. The compose stack publishes to fixed `localhost:*` ports that
   match the defaults in `backend/.env.example`: Postgres `5432`,
   Redis `6379`, Keycloak `8080`, MinIO `9000`/`9001`. The only
   environment edit a fresh engineer needs is `cp .env.example .env`.
4. Integration tests **continue to use `testcontainers`** —
   ephemeral, per-session, isolated from the compose stack. This ADR
   does not change the test infrastructure.
5. Production and staging are unaffected: they run on Kubernetes per
   ARCHITECTURE.md § 3.2. The compose file is `infra/dev/`-scoped on
   purpose and must not be mistaken for staging infrastructure.

## Consequences

- **Positive.**
  - Onboarding is two commands:
    `docker compose -f infra/dev/compose.yaml up -d`, then
    `uv sync --extra dev`.
  - App code runs natively, so debuggers, hot reload, and profilers
    behave normally. No volume-mount latency, no slow file-watch
    propagation across the WSL2/Windows boundary.
  - Persistent named volumes survive `compose down`, so a Keycloak
    realm tweak or a populated tenant DB outlives a reboot.
  - Service versions are now part of the repo and reviewable like any
    other config: image tags, ports, init scripts.
- **Negative.**
  - One more piece of dev infrastructure to maintain alongside
    `testcontainers`. Drift is possible; mitigated by using the
    same Postgres image (`timescale/timescaledb-ha:pg16`) in both.
  - Dev credentials (`missionagre/missionagre`, Keycloak `admin/admin`,
    MinIO `missionagre/missionagre-dev`) are committed. They are not
    secrets but engineers must never reuse them outside `infra/dev/`.
  - Keycloak in `start-dev` mode is not production-faithful: no
    clustering, in-memory caches, and dev-only realm import. That is
    by design at this scope; staging tests against the real
    Kubernetes deployment.

## Alternatives considered

- **Everything in compose, including the API and frontend.** Rejected.
  In-container hot reload over Windows volume mounts is slow, and the
  debugger story is poor. The natural workflow is to iterate on app
  code and only restart services when their config changes.
- **No compose; engineers install Postgres/Redis/Keycloak/MinIO via
  brew/choco/apt.** Rejected. Version drift across machines, no
  reproducible reset, no easy way to test a Keycloak realm change.
- **Reuse the `testcontainers` setup for dev.** Rejected. Containers
  tear down at the end of each pytest session; you cannot develop
  against a Keycloak realm if it disappears every five minutes.
- **Tilt or Skaffold against a local kind/k3d cluster.** Rejected
  for MVP — too much machinery for a four-service dev environment.
  Reconsider when the service count justifies it.

## Follow-ups

- [x] Add `infra/dev/compose.yaml` and the Keycloak realm export.
- [x] Update `backend/.env.example` with the dev-mode Keycloak issuer
      and MinIO endpoint variables.
- [x] Document the lifecycle (`up`, `down`, `down -v`) in the root
      and backend READMEs.
- [ ] Add an `S3` section to `app/core/settings.py` and a `boto3`
      client factory once the imagery module lands. Out of this
      ADR's scope.
- [ ] When the imagery module ships, the `pgstac` extension goes in
      via its own migration. Revisit this ADR if pgstac requires a
      different Postgres image than `timescaledb-ha:pg16`.
