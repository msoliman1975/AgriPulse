# Backend is serving stale routes (Windows uvicorn)

**Symptom.** You added a new module + router, restarted the backend, and the new
endpoints 404 while the *old* endpoints in the *same* router keep working. The
React app shows generic "Could not load â€¦" errors; DevTools â†’ Network shows
`status: 404`, `content-type: application/problem+json`, body
`{"type":"about:blank","title":"Not Found", ...}`.

This is *not* an authentication, capability, migration, or Vite-proxy problem.
The FastAPI app object being served by uvicorn is older than the source on disk.

## Why it happens on Windows

Two compounding causes seen in the wild:

1. **`uvicorn --reload` misses brand-new files.** The watcher (watchfiles) is
   reliable for *modifications* to known files but routinely misses *new*
   modules added to a package while the reloader is running. The reloader
   subprocess keeps the original module set in memory; routers from new files
   never get imported even after `app.include_router(...)` is added.
2. **Ghost listeners on `:8000`.** A previous `uvicorn` instance dies but its
   listening socket can survive long enough that a fresh `uvicorn` *appears* to
   start successfully (it binds because the socket is in a TIME_WAIT-ish
   state) while requests still reach the ghost. `Get-NetTCPConnection`'s
   `OwningProcess` may show a PID that no longer exists (`Get-Process -Id <pid>`
   says "process not found").

## How to confirm it's this issue and not something else

Run these in order. **The fifth one is the ground-truth answer.**

```powershell
cd C:\Users\mosoliman\projects\AgriPulse\backend
.\.venv\Scripts\Activate.ps1

# 1. Probe a new route directly. 401 ("Missing bearer token") DOES NOT prove the
#    route exists â€” auth middleware runs before routing, so it returns 401 for any
#    unauthenticated request even on a path that doesn't exist as a route. Use the
#    response shape to discriminate:
#       401 problem+json type="https://agripulse.cloud/problems/unauthorized"  -> auth ran (route MAY or may NOT exist)
#       404 problem+json type="about:blank"                                   -> route NOT registered
#       403 problem+json type=".../permission-denied"                         -> route exists, cap missing
$tid = "<some-tenant-id>"
try {
  Invoke-WebRequest "http://localhost:8000/api/v1/admin/tenants/$tid/integrations/health/farms" -UseBasicParsing | Out-Null
} catch {
  "status: $($_.Exception.Response.StatusCode.value__)"
  "body  : $($_.ErrorDetails.Message)"
}

# 2. Sanity-check openapi.json (only useful if app_debug=True â€” disabled in prod).
((Invoke-WebRequest "http://localhost:8000/openapi.json" -UseBasicParsing).Content `
  | Select-String -Pattern '/api/v1[^"]*<NEW_ROUTE_SUBSTRING>[^"]*' -AllMatches).Matches.Value | Sort-Object -Unique

# 3. What's actually listening on :8000?
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress, OwningProcess

# 4. Does that owning process actually exist?
Get-Process -Id <pid-from-step-3> -ErrorAction SilentlyContinue
```

**Step 5 is the ground truth.** It bypasses uvicorn entirely and asks the app
factory itself which routes are registered:

```powershell
python -c "from app.core.app_factory import create_app; app = create_app(); print('\n'.join(sorted(r.path for r in app.routes if '<NEW_ROUTE_SUBSTRING>' in getattr(r,'path',''))))"
```

If step 5 lists your new routes but step 2 does not, **the running uvicorn is
serving stale state**. Skip diagnosis, jump to the fix.

## Fix â€” clean restart procedure

```powershell
cd C:\Users\mosoliman\projects\AgriPulse\backend
.\.venv\Scripts\Activate.ps1

# Kill every Python process (uvicorn worker, watchfiles reloader, zombies).
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# Confirm port 8000 is free. If anything is still listening, kill that PID too.
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue

# Nuke EVERY __pycache__ under backend/ (not just app/) â€” stale .pyc files in
# migrations/, workers/, tests/ have re-imported old module versions before.
Get-ChildItem -Path . -Filter __pycache__ -Recurse -Directory -Force | Remove-Item -Recurse -Force

# Verify zero .pyc files survive under app/.
(Get-ChildItem -Path app -Filter *.pyc -Recurse -Force).Count   # expect 0

# Start uvicorn WITHOUT --reload. The reloader is what missed the new modules
# in the first place; use a plain process while iterating on a fresh module.
# Bind to 127.0.0.1 so any ghost on 0.0.0.0:8000 can't shadow this listener.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

After "Application startup complete", re-run step 2. The new routes should appear.

## When `--reload` is fine

Once a module exists on disk and uvicorn has been started fresh against it,
`--reload` correctly picks up *edits* to that module. The flake is only when
the module file itself is *new* relative to when uvicorn started.

Rule of thumb: **after adding a new module under `app/modules/`, do a full
restart (no --reload) at least once.** Subsequent `--reload`-driven iteration
on edits inside that module is fine.

## When the fix doesn't work

If step 5 also fails to list the new routes (i.e. `python -c "from
app.core.app_factory import create_app; â€¦"` shows the old set), the problem is
in the source, not the process. Common causes:

- An import inside one of the new modules raises silently (FastAPI does NOT
  skip routers whose import fails â€” the exception propagates â€” but if the
  router file imports another package conditionally and that package is missing
  from the venv, you'll see a real `ImportError` traceback at uvicorn startup).
- `_register_module_routers` doesn't call `app.include_router(...)` for the new
  router (easy to forget when adding a new router file).
- The new router file forgot `router = APIRouter(prefix=...)` or the decorators
  use `@app.get` instead of `@router.get`.

Run the smoke import to triangulate:

```powershell
python -c "@'
mods = [
    'app.modules.<your_new_module>.router',
    'app.core.app_factory',
]
for m in mods:
    try:
        __import__(m)
        print('ok ', m)
    except Exception as e:
        print('FAIL', m, '::', type(e).__name__, str(e)[:200])
'@" | python
```

## Related runbooks

- [local-stack-bootstrap.md](local-stack-bootstrap.md) â€” full first-time setup.

## History

Captured 2026-05-11 after a multi-hour investigation while shipping
`feat/integration-health-depth` (PR #70). The seven-PR series added many new
modules under `app/modules/integrations_health/` + a new router file
`platform_admins/health_tenant_drill.py`. Every route 404'd from the React app
despite the source being correct. Root cause: `uvicorn --reload` had been
running when the new files were added; the watcher missed them and the cached
app object never saw the include_router calls. Compounded by a ghost listener
on `:8000` that confused the diagnosis for an hour.
