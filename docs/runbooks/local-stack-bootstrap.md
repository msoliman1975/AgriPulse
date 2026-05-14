# Local stack bootstrap

This runbook brings up the full AgriPulse stack on a developer laptop —
Postgres / Redis / Keycloak / MinIO in containers, the API + Celery
workers + tile-server + SPA running natively. By the end you can sign in
at http://localhost:5173 as the seeded `dev@agripulse.local` user with
TenantOwner scope on a pre-bootstrapped tenant, and `PlatformAdmin`
access to `/platform/*`.

If anything below feels heavier than it should, that's because Slice 1
shipped without any of this glue — the `dev_bootstrap.py` script is the
piece that actually makes "first sign-in just works" possible.

---

## 1 — Prereqs

- Docker Desktop, Rancher Desktop (dockerd mode), or Podman with compose.
- Python 3.12+ on PATH.
- Node 20+ + pnpm via `corepack enable`.
- For raster ingestion: Sentinel Hub credentials in your password manager
  (entry `agripulse/sentinel-hub-dev`). Optional — without them the
  pipeline records a synthetic failed job, which is enough to smoke-test
  the UI's empty/error states.

> **uv on Windows behind a TLS-MITM proxy (Netskope, Zscaler, etc.)** —
> uv's default `rustls` TLS backend rejects the proxy's root CA with
> `InvalidCertificate(Other(OtherError(UnsupportedCriticalExtension)))`
> because the cert carries an X.509 critical extension `rustls` doesn't
> parse. Two-line PowerShell workaround that flips uv to Windows
> `schannel` (which loads the proxy cert from the OS trust store
> instead, and is more permissive about unknown extensions):
>
> ```powershell
> Remove-Item env:SSL_CERT_FILE -ErrorAction SilentlyContinue
> $env:UV_NATIVE_TLS = "1"
> # uv commands now work normally:
> uv lock
> uv sync --extra dev
> uv run pytest
> ```
>
> To make it permanent, paste those two lines into your PowerShell
> `$PROFILE`. Note: unsetting `SSL_CERT_FILE` only affects uv — other
> tools that key off it (git, node, grpc) keep working because the var
> remains set elsewhere; we just don't want uv to read the offending
> PEM. As a fallback, every shell-command in this runbook works against
> the existing `backend/.venv` directly, no uv required.

## 2 — Compose dependencies

```bash
docker compose -f infra/dev/compose.yaml up -d
docker compose -f infra/dev/compose.yaml ps
```

| Service   | URL                     | Credentials                     |
|-----------|-------------------------|---------------------------------|
| Postgres  | `localhost:5432`        | `agripulse / agripulse`         |
| Redis     | `localhost:6379`        | (no auth)                       |
| Keycloak  | http://localhost:8080   | admin: `admin / admin`          |
| MinIO API | http://localhost:9000   | `agripulse / agripulse-dev`     |
| MinIO UI  | http://localhost:9001   | same                            |

Wait for `agripulse-postgres` and `agripulse-redis` to be `(healthy)`
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
# Or, when `uv run` is blocked on Windows (and your shell isn't in the venv):
.\.venv\Scripts\alembic.exe -n public upgrade head
```

Should land at revision `0022` (provider probe results). Tenant schemas
are bootstrapped per tenant in the next-but-one section — don't run
tenant migrations manually unless `scripts/migrate_tenants.py` tells
you to.

> **Windows charmap gotcha** — Python's `configparser.read()` reads INI
> files with `encoding="locale"`, which on Windows is cp1252. If
> `backend/alembic.ini` ever contains non-ASCII characters (em-dashes
> creep in via copy-paste), you'll get `UnicodeDecodeError: 'charmap'
> codec can't decode byte 0x9d`. The committed `alembic.ini` is pure
> ASCII; keep it that way. Setting `PYTHONUTF8=1` does **not** override
> `encoding="locale"` here.

## 5 — Keycloak admin client + platform-admin env

The backend needs a confidential Keycloak admin client to provision
users (tenants, platform admins) via the Admin REST API. The realm JSON
ships only the SPA client (`agripulse-api`); the admin client
(`agripulse-tenancy`) is created at dev-bootstrap time and its secret
**regenerates every run** of this script.

```bash
python -m scripts.dev_keycloak_admin_client
```

The script prints the new secret at the end. Paste it into
`backend/.env`:

```env
KEYCLOAK_PROVISIONING_ENABLED=true
KEYCLOAK_BASE_URL=http://localhost:8080
KEYCLOAK_REALM=agripulse
KEYCLOAK_ADMIN_CLIENT_ID=agripulse-tenancy
KEYCLOAK_ADMIN_CLIENT_SECRET=<paste from script output>
```

While you're in `.env`, set the platform-admin seed so the backend
lifespan auto-creates a `PlatformAdmin` on the next startup (one-time,
idempotent):

```env
PLATFORM_ADMIN_EMAIL=dev@agripulse.local
PLATFORM_ADMIN_FULL_NAME=Platform Admin
```

> **Order matters** — `dev_bootstrap.py` (next section) and
> `bootstrap_platform_admin` (lifespan) both call the admin client. Run
> Section 5 *before* the next two; otherwise the lifespan silently fails
> Keycloak-side and inserts a `pending::` placeholder user row that
> blocks subsequent `dev_bootstrap` runs on `uq_users_email`.

## 6 — Dev tenant + user + Keycloak claims

```bash
python -m scripts.dev_bootstrap
```

Idempotent. Performs five things end-to-end:

1. Creates a tenant named `dev-tenant` in `public.tenants` and
   bootstraps its `tenant_<uuid>` schema (runs tenant migrations).
2. Reads `dev@agripulse.local`'s Keycloak `sub` UUID via the Admin
   REST API.
3. Inserts a matching `public.users` row + `tenant_memberships` +
   `tenant_role_assignments` (**TenantOwner** — matches production:
   every tenant has exactly one TenantOwner from creation).
4. Sets the Keycloak user's `tenant_id` and `tenant_role` attributes.
5. Adds two `oidc-usermodel-attribute-mapper` protocol mappers to the
   `agripulse-api` client so those attributes ride into the JWT.

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
  "tenant_role": "TenantOwner",
  "aud": "agripulse-api"
}
```

## 7 — Seed the PlatformAdmin

Two paths — pick one.

**Path A (preferred)** — let the backend lifespan do it. After Section 5
the env vars are in place; just start the API once and
`bootstrap_platform_admin` idempotently:

- inserts the `public.platform_role_assignments` DB row, and
- adds the `platform_role` user attribute + `platform_role-mapper`
  protocol mapper on `agripulse-api`.

Look for `platform_admin_bootstrap_succeeded` in the API stderr log.
Skip ahead to Section 8.

**Path B (manual)** — if `PLATFORM_ADMIN_EMAIL` was empty on first boot,
or the lifespan errored before Section 5 was complete:

```bash
python -m scripts.dev_promote_platform_admin
```

Sets the `platform_role` user attribute and adds the `platform_role-mapper`
on `agripulse-api`. Does **not** insert into
`public.platform_role_assignments` — restart the backend afterwards so
the lifespan writes the row (which keeps `/platform/admins` showing you
in the list).

## 8 — API + Celery workers

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

## 9 — Tile-server (TiTiler)

```bash
cd ../tile-server
docker build -t agripulse/tile-server:dev .

docker run --rm -d --name agripulse-tileserver -p 8001:80 \
  -e AWS_S3_ENDPOINT_URL=http://host.docker.internal:9000 \
  -e AWS_ACCESS_KEY_ID=agripulse \
  -e AWS_SECRET_ACCESS_KEY=agripulse-dev \
  -e AWS_VIRTUAL_HOSTING=FALSE -e AWS_HTTPS=NO \
  -e CORS_ALLOW_ORIGINS=http://localhost:5173 \
  agripulse/tile-server:dev

curl http://localhost:8001/healthz
# {"versions":{"titiler":"...","rasterio":"...",...}}
```

> **Container port is 80, not 8000.** The app inside listens on 80
> (gunicorn default in our base image); we map host:8001 → container:80
> because the backend's `tile_server_base_url` setting defaults to
> `http://localhost:8001`.

## 10 — Frontend

```bash
cd ../frontend
corepack enable
pnpm install
cp .env.example .env.local
pnpm dev   # http://localhost:5173
```

## 11 — Sign in + smoke

1. Open http://localhost:5173 → bounces to Keycloak.
2. Sign in as `dev@agripulse.local` / `dev`.
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
8. PlatformAdmin features: the top nav should expose `/platform/*` links
   (tenants, integrations health, platform admins). If they're missing,
   confirm `platform_admin_bootstrap_succeeded` in the API log and that
   you fully **signed out + back in** after Section 7 — the JWT claim
   doesn't update on refresh.

## Troubleshooting

| Symptom                                                | Cause                                                                              | Fix                                                                         |
|---|---|---|
| Sign-in loops (URL flips between `/auth/callback` and `/login`) | Stale browser session from before AuthCallback was wired                           | Clear `sessionStorage`, hard-refresh                                        |
| Login button does nothing (no redirect)                | OIDC discovery 404 — Keycloak has the wrong realm name (post-rename) or container is stale | `docker compose -f infra/dev/compose.yaml down -v && up -d`, then re-run Sections 4–7 in order |
| `Missing capability: farm.read`                        | JWT lacks `tenant_id` / `tenant_role` claims                                       | Re-run `python -m scripts.dev_bootstrap`, sign out + back in                |
| `/platform/*` returns 403 after sign-in                | `platform_role` claim not in JWT; protocol mapper missing                          | Run Section 7 Path B, sign out + back in                                    |
| API log: `platform_admin_invite_keycloak_failed`, `invalid_client` | The `agripulse-tenancy` admin client doesn't exist or its `.env` secret is stale (regen on every script run) | Re-run `dev_keycloak_admin_client`, paste new secret into `.env`, restart backend |
| `dev_bootstrap.py` fails with `duplicate key … uq_users_email` | Earlier failed `bootstrap_platform_admin` left a `pending::` placeholder user      | `psql ... -c "DELETE FROM public.users WHERE keycloak_subject LIKE 'pending::%';"` then retry |
| `alembic` exits with `UnicodeDecodeError: 'charmap'` reading `alembic.ini` | Non-ASCII characters in `alembic.ini` + cp1252 locale on Windows                   | Replace em-dashes / smart quotes with ASCII (the committed file is ASCII)   |
| `Port 5173 is already in use`                          | Earlier Vite still bound                                                           | `Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess` then re-run `pnpm dev` |
| Celery `KeyError: 'imagery.discover_active_subscriptions'` | `_TASK_PACKAGES` pointing at the package, not the submodule                        | Pull main — `app.modules.imagery.tasks` is now the right entry              |
| Tile request 404s in MapLibre devtools                  | TiTiler can't reach MinIO at `host.docker.internal` (Linux Docker)                 | Add `--network host` to the tile-server run, or use the MinIO container IP  |
| New API routes 404 after `--reload` picked up other files | `uvicorn --reload` (watchfiles on Windows) misses *new* module files                | See [backend-stale-routes.md](backend-stale-routes.md) — full restart, nuke every `__pycache__`, drop `--reload` |

## When you're done

```bash
# Stop foreground processes (Ctrl+C in each shell)
# Stop the tile-server container
docker stop agripulse-tileserver

# Bring deps down (keep volumes)
docker compose -f infra/dev/compose.yaml down

# Or wipe state for a clean slate next time
docker compose -f infra/dev/compose.yaml down -v
```

The dev tenant + Keycloak realm + Keycloak admin client survive a
`down` (volumes persist).

After a `down -v` you'll need to re-run **Sections 4 through 7 in
order**:

1. `alembic -n public upgrade head`  (Section 4)
2. `python -m scripts.dev_keycloak_admin_client` + paste new secret into `.env`  (Section 5)
3. `python -m scripts.dev_bootstrap`  (Section 6)
4. Restart backend so the lifespan auto-seeds `PlatformAdmin` (assumes `PLATFORM_ADMIN_EMAIL` is set in `.env`), **or** `python -m scripts.dev_promote_platform_admin`  (Section 7)

Skipping any step is the source of most "login works but ..." bugs.
