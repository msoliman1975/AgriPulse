# Local stack bootstrap

This runbook brings up the full MissionAgre stack on a developer laptop —
Postgres / Redis / Keycloak / MinIO in containers, the API + Celery
workers + tile-server + SPA running natively. By the end you can sign in
at http://localhost:5173 as the seeded `dev@missionagre.local` user with
TenantAdmin scope on a pre-bootstrapped tenant.

If anything below feels heavier than it should, that's because Slice 1
shipped without any of this glue — the `dev_bootstrap.py` script is the
piece that actually makes "first sign-in just works" possible.

---

## 1 — Prereqs

- Docker Desktop, Rancher Desktop (dockerd mode), or Podman with compose.
- Python 3.12+ on PATH.
- Node 20+ + pnpm via `corepack enable`.
- For raster ingestion: Sentinel Hub credentials in your password manager
  (entry `missionagre/sentinel-hub-dev`). Optional — without them the
  pipeline records a synthetic failed job, which is enough to smoke-test
  the UI's empty/error states.

> **uv on Windows hits a TLS-trust bug** in our environment
> (`InvalidCertificate(Other(OtherError(UnsupportedCriticalExtension)))`).
> Use the existing `backend/.venv` directly, or run `uv` from WSL.

## 2 — Compose dependencies

```bash
docker compose -f infra/dev/compose.yaml up -d
docker compose -f infra/dev/compose.yaml ps
```

| Service   | URL                     | Credentials                     |
|-----------|-------------------------|---------------------------------|
| Postgres  | `localhost:5432`        | `missionagre / missionagre`     |
| Redis     | `localhost:6379`        | (no auth)                       |
| Keycloak  | http://localhost:8080   | admin: `admin / admin`          |
| MinIO API | http://localhost:9000   | `missionagre / missionagre-dev` |
| MinIO UI  | http://localhost:9001   | same                            |

Wait for `missionagre-postgres` and `missionagre-redis` to be `(healthy)`
before continuing.

## 3 — Backend deps + env

```bash
cd backend
# WSL or Linux/macOS:    uv sync --extra dev
# Windows + uv broken:   reuse the existing .venv (created by the test suite)
.venv\Scripts\Activate.ps1   # PowerShell
# .venv\Scripts\activate.bat # cmd
# source .venv/bin/activate  # bash

cp .env.example .env
```

> **Gotcha** — `pydantic-settings` 2.6+ rejects the comma-separated form
> of `CORS_ALLOWED_ORIGINS`. The `.env.example` ships the JSON-array
> form; if you've copied an older `.env`, change the line to:
>
> ```env
> CORS_ALLOWED_ORIGINS=["http://localhost:5173","http://localhost:3000"]
> ```

If you have Sentinel Hub creds, also fill `SENTINEL_HUB_CLIENT_ID` /
`SENTINEL_HUB_CLIENT_SECRET` — otherwise leave empty and the pipeline
fails closed loudly.

## 4 — Public migrations

```bash
python -m alembic -n public upgrade head
```

Should land at revision `0008` (Sentinel-2 catalog seed). Tenant schemas
are bootstrapped per tenant in step 6 — don't run tenant migrations
manually unless `scripts/migrate_tenants.py` tells you to.

## 5 — Dev tenant + user + Keycloak claims

```bash
python -m scripts.dev_bootstrap
```

Idempotent. Performs five things end-to-end:

1. Creates a tenant named `dev-tenant` in `public.tenants` and
   bootstraps its `tenant_<uuid>` schema (runs tenant migrations
   `0001` → `0004`).
2. Reads `dev@missionagre.local`'s Keycloak `sub` UUID via the Admin
   REST API.
3. Inserts a matching `public.users` row + `tenant_memberships` +
   `tenant_role_assignments` (TenantAdmin).
4. Sets the Keycloak user's `tenant_id` and `tenant_role` attributes.
5. Adds two `oidc-usermodel-attribute-mapper` protocol mappers to the
   `missionagre-api` client so those attributes ride into the JWT.

> **Keycloak 26 quirk** — the realm's user-profile feature drops
> "unmanaged" custom attributes silently by default. The script flips
> `unmanagedAttributePolicy = ENABLED` on first run. If you skip the
> script and hand-edit the user instead, you'll see empty attributes
> after PUT — that's why.

After this script, the dev user's JWT carries:

```json
{
  "sub": "<keycloak user uuid>",
  "tenant_id": "<dev-tenant uuid>",
  "tenant_role": "TenantAdmin",
  "aud": "missionagre-api"
}
```

## 6 — API + Celery workers

Four shells, all with `.venv` activated:

```bash
# Shell 1 — FastAPI
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Shell 2 — light queue (discover_scenes, register_stac_item, audit fan-out)
python -m celery -A workers.light.main worker -Q light -n light@%h --pool=solo --loglevel=INFO

# Shell 3 — heavy queue (acquire_scene, compute_indices)
python -m celery -A workers.heavy.main worker -Q heavy -n heavy@%h --pool=solo --loglevel=INFO

# Shell 4 — beat
python -m celery -A workers.beat.main beat --loglevel=INFO
```

> **`-n light@%h` / `-n heavy@%h`** is essential on Windows. Default
> Celery node names use the hostname; both workers end up under
> `celery@<hostname>` and broker inspect collapses them. Distinct node
> names keep them separable.

Confirm both queues are reachable:

```bash
python -c "
from celery import Celery
i = Celery(broker='redis://localhost:6379/1').control.inspect(timeout=3)
for w, qs in (i.active_queues() or {}).items():
    print(w, [q['name'] for q in qs])
"
# light@<host> ['light']
# heavy@<host> ['heavy']
```

## 7 — Tile-server (TiTiler)

```bash
cd ../tile-server
docker build -t missionagre/tile-server:dev .

docker run --rm -d --name missionagre-tileserver -p 8001:80 \
  -e AWS_S3_ENDPOINT_URL=http://host.docker.internal:9000 \
  -e AWS_ACCESS_KEY_ID=missionagre \
  -e AWS_SECRET_ACCESS_KEY=missionagre-dev \
  -e AWS_VIRTUAL_HOSTING=FALSE -e AWS_HTTPS=NO \
  -e CORS_ALLOW_ORIGINS=http://localhost:5173 \
  missionagre/tile-server:dev

curl http://localhost:8001/healthz
# {"versions":{"titiler":"...","rasterio":"...",...}}
```

> **Container port is 80, not 8000.** The app inside listens on 80
> (gunicorn default in our base image); we map host:8001 → container:80
> because the backend's `tile_server_base_url` setting defaults to
> `http://localhost:8001`.

## 8 — Frontend

```bash
cd ../frontend
corepack enable
pnpm install
cp .env.example .env.local
pnpm dev   # http://localhost:5173
```

## 9 — Sign in + smoke

1. Open http://localhost:5173 → bounces to Keycloak.
2. Sign in as `dev@missionagre.local` / `dev`.
3. Land on the home page → click **Farms**.
4. Empty list (200, not 403). `[+ New farm]` → draw a small polygon over
   the Nile delta (~31.20°E, 30.10°N).
5. Add a block inside the farm.
6. Block detail page now shows the three Slice-2 sections:
   - **Imagery** — empty until a scene ingests
   - **Trend** — Recharts empty-state
   - **Subscriptions** — click "Subscribe to Sentinel-2 L2A"
7. Click **Refresh imagery**:
   - With Sentinel Hub creds: workers fetch a real scene; ~30 s later
     the scene picker populates and the NDVI overlay renders.
   - Without creds: a synthetic failed job appears in the audit log
     (`error_message="sentinel_hub_not_configured"`) — confirms the
     "fail closed" gate from PR-B.

## Troubleshooting

| Symptom                                                | Cause                                                                              | Fix                                                                         |
|---|---|---|
| Sign-in loops (URL flips between `/auth/callback` and `/login`) | Stale browser session from before AuthCallback was wired                           | Clear `sessionStorage`, hard-refresh                                        |
| `Missing capability: farm.read`                        | JWT lacks `tenant_id` / `tenant_role` claims                                       | Re-run `python -m scripts.dev_bootstrap`, sign out + back in                |
| `Port 5173 is already in use`                          | Earlier Vite still bound                                                           | `Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess` then re-run `pnpm dev` |
| Celery `KeyError: 'imagery.discover_active_subscriptions'` | `_TASK_PACKAGES` pointing at the package, not the submodule                        | Pull main — `app.modules.imagery.tasks` is now the right entry              |
| Tile request 404s in MapLibre devtools                  | TiTiler can't reach MinIO at `host.docker.internal` (Linux Docker)                 | Add `--network host` to the tile-server run, or use the MinIO container IP  |
| New API routes 404 after `--reload` picked up other files | `uvicorn --reload` (watchfiles on Windows) misses *new* module files                | See [backend-stale-routes.md](backend-stale-routes.md) — full restart, nuke every `__pycache__`, drop `--reload` |

## When you're done

```bash
# Stop foreground processes (Ctrl+C in each shell)
# Stop the tile-server container
docker stop missionagre-tileserver

# Bring deps down (keep volumes)
docker compose -f infra/dev/compose.yaml down

# Or wipe state for a clean slate next time
docker compose -f infra/dev/compose.yaml down -v
```

The dev tenant + Keycloak attributes survive a `down` (volumes persist).
After a `down -v` you'll need to re-run public migrations + the bootstrap
script.
