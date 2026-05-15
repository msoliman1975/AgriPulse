<#
.SYNOPSIS
  AgriPulse local-stack driver (hardened).

.DESCRIPTION
  Walks the local-development bring-up in phases. Each phase is idempotent
  and re-entrant. Background processes (API, workers, tile-server, frontend)
  are tracked in scripts/.dev-stack-state.json so they can be stopped cleanly
  by the `down` phase or surfaced by `status` / `doctor`.

  Hardening vs the prior driver:
    1. Stop uses taskkill /F /T, which walks the FULL descendant tree
       (uvicorn supervisor + reload worker + multiprocessing helpers, or
       cmd.exe + fnm-node + cmd.exe + vite + esbuild). The prior version
       only killed immediate children and left the rest holding ports.
    2. Every start phase first reclaims its port: it finds whoever is
       LISTENING on :8000 / :5173 / :5555 and kills that process tree,
       regardless of the state file. Stale state-file entries no longer
       collide with the next bring-up.
    3. uvicorn runs WITHOUT --reload. The two-PID supervisor/worker tree
       was the root cause of orphan-child sockets on Windows. To pick up
       code changes, re-run `dev-stack.ps1 -Phase api`.
    4. OTEL_EXPORTER_OTLP_ENDPOINT is forced to empty for spawned dev
       processes. The cluster-local Tempo hostname is unreachable from
       the local host; leaving it set causes DNS-retry floods and a
       structlog/OTEL bg-thread error per attempt that fills api.err.log
       to multi-GB sizes over a day.
    5. A `doctor` phase prints port owners, dev-process orphans, and log
       sizes. Use it when "the app stopped responding" -- it tells you
       what to kill.

  Phases (in order for `all`):
    1. preflight     Verify docker, python venv, fnm/node, .env files.
    2. compose       docker compose up postgres/redis/keycloak/minio.
    3. migrate       alembic upgrade head (public schema).
    4. kc-admin      Provision Keycloak admin client + patch backend/.env.
    5. bootstrap     Create dev tenant + dev user + Keycloak claims.
    6. api           uvicorn (background) on :8000 (no --reload).
    7. workers       celery light + heavy + beat (background).
    8. tile          tile-server docker container on :8001.
    9. frontend      pnpm dev (background) on :5173.
   10. smoke         healthz checks against api / tile / frontend.

  Other phases:
    status           Show what's running and what isn't.
    doctor           Diagnose orphan processes + port owners + log bloat.
    down             Stop everything brought up by this script.

.PARAMETER Phase
  Run only one phase. Default: all.

.EXAMPLE
  ./scripts/dev-stack.ps1                       # full bring-up
  ./scripts/dev-stack.ps1 -Phase api            # just (re)start the API
  ./scripts/dev-stack.ps1 -Phase doctor         # diagnose problems
  ./scripts/dev-stack.ps1 -Phase down           # stop everything
#>

[CmdletBinding()]
param(
  [ValidateSet('all','preflight','compose','migrate','kc-admin','bootstrap',
               'api','workers','tile','frontend','smoke','status','doctor','down')]
  [string]$Phase = 'all'
)

$ErrorActionPreference = 'Stop'
$RepoRoot   = Resolve-Path "$PSScriptRoot/.."
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir= Join-Path $RepoRoot 'frontend'
$TileDir    = Join-Path $RepoRoot 'tile-server'
$ComposeFile= Join-Path $RepoRoot 'infra/dev/compose.yaml'
$StateFile  = Join-Path $PSScriptRoot '.dev-stack-state.json'
$LogDir     = Join-Path $PSScriptRoot '.dev-stack-logs'
$Venv       = Join-Path $BackendDir '.venv/Scripts'

# Service-to-listening-port map. Used by start-phase port reclaim and by
# `doctor`. If you add a new background service, add its port here.
$ServicePorts = @{
  'api'      = 8000
  'frontend' = 5173
  # celery workers do not bind a TCP port
}

# ---------- helpers ---------------------------------------------------------

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    ok: $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    warn: $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "    FAIL: $msg" -ForegroundColor Red; throw $msg }

function Require-Tool($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Fail "Missing tool: $name."
  }
  Write-Ok "$name present"
}

function Load-State {
  if (-not (Test-Path $StateFile)) { return @{} }
  $raw = Get-Content $StateFile -Raw
  if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
  $obj = $raw | ConvertFrom-Json
  $h = @{}
  foreach ($p in $obj.PSObject.Properties) {
    $entry = @{}
    foreach ($q in $p.Value.PSObject.Properties) { $entry[$q.Name] = $q.Value }
    $h[$p.Name] = $entry
  }
  return $h
}

function Save-State($state) {
  $state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding utf8
}

function Test-PidAlive($processId) {
  if (-not $processId) { return $false }
  return [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

function Kill-Tree([int]$processId) {
  # taskkill /F /T walks the full descendant tree on Windows. This is the
  # only reliable way to kill `--reload`'s reloader+worker pair or the
  # pnpm -> fnm -> cmd -> vite -> esbuild chain. Stop-Process -Id alone
  # leaves descendants reparented to init and they keep holding ports.
  if (-not (Test-PidAlive $processId)) { return $false }
  & taskkill.exe /F /T /PID $processId 2>$null | Out-Null
  Start-Sleep -Milliseconds 200
  return -not (Test-PidAlive $processId)
}

function Get-PortOwner([int]$port) {
  # Returns the PID currently LISTENING on the port, or 0 if none.
  $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
       Select-Object -First 1
  if ($c) { return [int]$c.OwningProcess }
  return 0
}

function Find-TreeRoot([int]$processId) {
  # Walk up the parent chain until the parent is no longer a recognisable
  # dev process. Returns the topmost dev PID, which is what we should
  # taskkill /T to remove the whole service.
  $devNames = @('python.exe','node.exe','pnpm.exe','cmd.exe','powershell.exe','pwsh.exe','uvicorn.exe','celery.exe')
  $current = $processId
  while ($true) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
    if (-not $proc) { return $current }
    $parentId = [int]$proc.ParentProcessId
    if ($parentId -le 0) { return $current }
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
    if (-not $parent) { return $current }
    if ($devNames -notcontains $parent.Name) { return $current }
    # Don't ascend past the user's interactive shell -- heuristic:
    # if parent is powershell.exe and its command line doesn't match
    # dev-stack.ps1 or a similar wrapper, stop here.
    if ($parent.Name -in @('powershell.exe','pwsh.exe') -and ($parent.CommandLine -notmatch 'dev-stack')) {
      return $current
    }
    $current = $parentId
  }
}

function Reclaim-Port([string]$serviceName, [int]$port) {
  # Pre-flight: if anyone is holding the port we're about to bind, kill
  # their entire tree. This is what protects us from stale state files
  # and orphans left by a previous crashed run.
  $owner = Get-PortOwner $port
  if ($owner -eq 0) { return }
  $root = Find-TreeRoot $owner
  Write-Warn2 "port $port already held by pid $owner (tree root pid $root) -- reclaiming"
  $null = Kill-Tree $root
  # Verify
  $still = Get-PortOwner $port
  if ($still -ne 0) {
    Write-Fail "port $port still held by pid $still after reclaim attempt -- manual intervention required."
  }
  Write-Ok "port $port reclaimed for $serviceName"
}

function Start-Background([string]$name, [string]$exe, [string[]]$argList, [string]$workdir, [hashtable]$extraEnv = $null) {
  if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
  $state = Load-State
  if ($state.ContainsKey($name) -and (Test-PidAlive $state[$name].pid)) {
    Write-Warn2 "$name already running (pid $($state[$name].pid)) -- stopping it before restart"
    Stop-Background $name
    $state = Load-State
  }
  # Defense in depth: if state says we're not running but the port is held,
  # reclaim it anyway. Catches the case where the state file is stale.
  if ($ServicePorts.ContainsKey($name)) {
    Reclaim-Port $name $ServicePorts[$name]
  }

  $stdout = Join-Path $LogDir "$name.out.log"
  $stderr = Join-Path $LogDir "$name.err.log"

  $ext = [System.IO.Path]::GetExtension($exe).ToLower()
  switch ($ext) {
    '.ps1' {
      $wrappedExe  = (Get-Command powershell.exe).Source
      $wrappedArgs = @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$exe) + $argList
    }
    { $_ -in '.cmd','.bat' } {
      $wrappedExe  = (Get-Command cmd.exe).Source
      $wrappedArgs = @('/c',$exe) + $argList
    }
    default {
      $wrappedExe  = $exe
      $wrappedArgs = $argList
    }
  }

  # Apply env overrides to the current process (Start-Process inherits env
  # from the caller). We snapshot + restore so we don't leak overrides.
  $envBackup = @{}
  if ($extraEnv) {
    foreach ($k in $extraEnv.Keys) {
      $envBackup[$k] = [System.Environment]::GetEnvironmentVariable($k, 'Process')
      [System.Environment]::SetEnvironmentVariable($k, $extraEnv[$k], 'Process')
    }
  }
  try {
    $params = @{
      FilePath               = $wrappedExe
      ArgumentList           = $wrappedArgs
      WorkingDirectory       = $workdir
      RedirectStandardOutput = $stdout
      RedirectStandardError  = $stderr
      WindowStyle            = 'Hidden'
      PassThru               = $true
    }
    $proc = Start-Process @params
  } finally {
    foreach ($k in $envBackup.Keys) {
      [System.Environment]::SetEnvironmentVariable($k, $envBackup[$k], 'Process')
    }
  }
  $state[$name] = @{ pid = $proc.Id; cmd = "$exe $($argList -join ' ')"; started = (Get-Date).ToString('o') }
  Save-State $state
  Write-Ok "$name started (pid $($proc.Id), logs $stdout)"
}

function Stop-Background([string]$name) {
  $state = Load-State
  $trackedPid = 0
  if ($state.ContainsKey($name)) { $trackedPid = [int]$state[$name].pid }

  if ($trackedPid -gt 0 -and (Test-PidAlive $trackedPid)) {
    $null = Kill-Tree $trackedPid
    Write-Ok "$name tree killed (root was pid $trackedPid)"
  } elseif ($trackedPid -gt 0) {
    Write-Warn2 "$name tracked pid $trackedPid was not alive"
  }

  # Whether or not the tracked PID was alive, also reclaim the port: there
  # may be an orphan child still holding it.
  if ($ServicePorts.ContainsKey($name)) {
    $owner = Get-PortOwner $ServicePorts[$name]
    if ($owner -gt 0) {
      $root = Find-TreeRoot $owner
      $null = Kill-Tree $root
      Write-Ok "$name port $($ServicePorts[$name]) cleared (orphan tree root was pid $root)"
    }
  }

  if ($state.ContainsKey($name)) { $state.Remove($name); Save-State $state }
}

function Wait-Healthy([string]$container, [int]$timeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $status = (docker inspect --format '{{.State.Health.Status}}' $container 2>$null)
    if ($status -eq 'healthy') { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

# ---------- phases ----------------------------------------------------------

function Invoke-Preflight {
  Write-Step "Phase 1 - preflight"
  Require-Tool docker
  if (-not (Test-Path "$Venv/python.exe")) {
    Write-Fail "Backend venv missing at $Venv. Create it with: cd backend; python -m venv .venv; .\.venv\Scripts\pip install -e ."
  }
  Write-Ok "backend venv at $Venv"

  if (-not (Test-Path "$BackendDir/.env")) {
    if (Test-Path "$BackendDir/.env.example") {
      Copy-Item "$BackendDir/.env.example" "$BackendDir/.env"
      Write-Warn2 "Created backend/.env from .env.example - review it before continuing."
    } else {
      Write-Fail "backend/.env missing and no .env.example to copy."
    }
  } else {
    Write-Ok "backend/.env present"
  }

  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    if (Get-Command fnm -ErrorAction SilentlyContinue) {
      Write-Warn2 "pnpm not on PATH but fnm is. Activating fnm now."
      fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression
      if (Get-Command corepack -ErrorAction SilentlyContinue) { corepack enable 2>$null | Out-Null }
    }
  }
  if (Get-Command pnpm -ErrorAction SilentlyContinue) { Write-Ok "pnpm present" }
  else { Write-Warn2 "pnpm not available - frontend phase will be skipped" }

  if (-not (Test-Path "$FrontendDir/.env.local") -and (Test-Path "$FrontendDir/.env.example")) {
    Copy-Item "$FrontendDir/.env.example" "$FrontendDir/.env.local"
    Write-Warn2 "Created frontend/.env.local from .env.example"
  }
}

function Invoke-Compose {
  Write-Step "Phase 2 - docker compose (postgres/redis/keycloak/minio)"
  docker compose -f "$ComposeFile" up -d
  if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed (exit $LASTEXITCODE)." }
  Write-Ok "compose up issued. Waiting for postgres + redis healthy..."
  if (-not (Wait-Healthy 'agripulse-postgres' 60)) { Write-Fail "postgres did not become healthy in 60s." }
  if (-not (Wait-Healthy 'agripulse-redis' 30))    { Write-Fail "redis did not become healthy in 30s." }
  Write-Ok "postgres + redis healthy"
  Write-Ok "Keycloak admin:  http://localhost:8080  (admin / admin)"
  Write-Ok "MinIO console:   http://localhost:9001  (agripulse / agripulse-dev)"
}

function Invoke-Migrate {
  Write-Step "Phase 3 - alembic upgrade head (public)"
  Push-Location $BackendDir
  try {
    & "$Venv/alembic.exe" -n public upgrade head
    if ($LASTEXITCODE -ne 0) { Write-Fail "alembic failed (exit $LASTEXITCODE)." }
    Write-Ok "public schema at head"
  } finally { Pop-Location }
}

function Invoke-KcAdmin {
  Write-Step "Phase 4 - Keycloak admin client provisioning"
  Push-Location $BackendDir
  try {
    & "$Venv/python.exe" -m scripts.dev_keycloak_admin_client
    if ($LASTEXITCODE -ne 0) { Write-Fail "dev_keycloak_admin_client failed (exit $LASTEXITCODE). Is Keycloak healthy yet?" }
    Write-Ok "admin client provisioned (secret in backend/.env)"
  } finally { Pop-Location }
}

function Invoke-Bootstrap {
  Write-Step "Phase 5 - dev tenant + dev user bootstrap"
  Push-Location $BackendDir
  try {
    & "$Venv/python.exe" -m scripts.dev_bootstrap
    if ($LASTEXITCODE -ne 0) { Write-Fail "dev_bootstrap failed (exit $LASTEXITCODE)." }
    Write-Ok "dev-tenant + dev@agripulse.local seeded"
  } finally { Pop-Location }
}

# Env overrides applied to every dev Python service. OTEL endpoint is
# forced empty so the unreachable in-cluster Tempo hostname doesn't
# trigger DNS-retry storms + structlog/OTEL bg-thread errors. The
# observability module installs a no-op TracerProvider when the
# endpoint is empty.
$DevPythonEnv = @{
  'OTEL_EXPORTER_OTLP_ENDPOINT'                = ''
  'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT'         = ''
  'OTEL_TRACES_EXPORTER'                       = 'none'
  'OTEL_METRICS_EXPORTER'                      = 'none'
  'OTEL_LOGS_EXPORTER'                         = 'none'
}

function Invoke-Api {
  Write-Step "Phase 6 - API (uvicorn :8000)"
  # NOTE: --reload removed deliberately. The reloader spawns a second
  # process whose PID is not tracked; killing the reloader on restart
  # left that worker holding :8000 as an orphan. Re-run this phase to
  # pick up code changes.
  Start-Background -name 'api' -exe "$Venv/python.exe" `
    -argList @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000') `
    -workdir $BackendDir `
    -extraEnv $DevPythonEnv
}

function Invoke-Workers {
  Write-Step "Phase 7 - Celery workers (light + heavy + beat)"
  Start-Background -name 'worker-light' -exe "$Venv/python.exe" `
    -argList @('-m','celery','-A','workers.light.main','worker','-Q','light','-n','light@%h','--pool=solo','--loglevel=INFO') `
    -workdir $BackendDir `
    -extraEnv $DevPythonEnv
  Start-Background -name 'worker-heavy' -exe "$Venv/python.exe" `
    -argList @('-m','celery','-A','workers.heavy.main','worker','-Q','heavy','-n','heavy@%h','--pool=solo','--loglevel=INFO') `
    -workdir $BackendDir `
    -extraEnv $DevPythonEnv
  Start-Background -name 'worker-beat' -exe "$Venv/python.exe" `
    -argList @('-m','celery','-A','workers.beat.main','beat','--loglevel=INFO') `
    -workdir $BackendDir `
    -extraEnv $DevPythonEnv
}

function Invoke-Tile {
  Write-Step "Phase 8 - tile-server (docker :8001)"
  $existing = docker ps -a --filter "name=agripulse-tileserver" --format "{{.Names}}"
  if ($existing) {
    docker rm -f agripulse-tileserver 2>$null | Out-Null
    Write-Ok "removed stale tile-server container"
  }
  $img = (docker images -q agripulse/tile-server:dev)
  if (-not $img) {
    Write-Step "  building agripulse/tile-server:dev (first run, ~2 min)"
    docker build -t agripulse/tile-server:dev "$TileDir"
    if ($LASTEXITCODE -ne 0) { Write-Fail "tile-server build failed." }
  }
  docker run --rm -d --name agripulse-tileserver -p 8001:80 `
    -e AWS_S3_ENDPOINT_URL=http://host.docker.internal:9000 `
    -e AWS_ACCESS_KEY_ID=agripulse `
    -e AWS_SECRET_ACCESS_KEY=agripulse-dev `
    -e AWS_VIRTUAL_HOSTING=FALSE -e AWS_HTTPS=NO `
    -e CORS_ALLOW_ORIGINS=http://localhost:5173 `
    agripulse/tile-server:dev | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Fail "tile-server failed to start." }
  Write-Ok "tile-server running on :8001"
}

function Invoke-Frontend {
  Write-Step "Phase 9 - frontend (pnpm dev :5173)"
  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    if (Get-Command fnm -ErrorAction SilentlyContinue) {
      fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression
      if (Get-Command corepack -ErrorAction SilentlyContinue) { corepack enable 2>$null | Out-Null }
    }
  }
  $pnpm = (Get-Command pnpm -ErrorAction SilentlyContinue).Source
  if (-not $pnpm) { Write-Warn2 "pnpm still not available - skipping frontend"; return }

  if (-not (Test-Path "$FrontendDir/node_modules")) {
    Write-Step "  pnpm install (first run)"
    Push-Location $FrontendDir
    try {
      & $pnpm install
      if ($LASTEXITCODE -ne 0) { Write-Fail "pnpm install failed." }
    } finally { Pop-Location }
  }
  Start-Background -name 'frontend' -exe $pnpm -argList @('dev') -workdir $FrontendDir
}

function Invoke-Smoke {
  Write-Step "Phase 10 - smoke checks"
  Start-Sleep -Seconds 3
  $checks = @(
    @{ name='api';       url='http://localhost:8000/healthz' },
    @{ name='tile';      url='http://localhost:8001/healthz' },
    @{ name='frontend';  url='http://localhost:5173/' },
    @{ name='keycloak';  url='http://localhost:8080/realms/agripulse/.well-known/openid-configuration' }
  )
  foreach ($c in $checks) {
    try {
      $r = Invoke-WebRequest -Uri $c.url -Method Get -UseBasicParsing -TimeoutSec 5
      Write-Ok "$($c.name) [$($r.StatusCode)] $($c.url)"
    } catch {
      Write-Warn2 "$($c.name) FAIL $($c.url) - $($_.Exception.Message)"
    }
  }
}

function Invoke-Status {
  Write-Step "Stack status"
  Write-Host ""
  Write-Host "  Containers:" -ForegroundColor Yellow
  docker ps --filter "name=agripulse-" --format "    {{.Names}}`t{{.Status}}`t{{.Ports}}"
  Write-Host ""
  Write-Host "  Background processes:" -ForegroundColor Yellow
  $state = Load-State
  if ($state.Count -eq 0) { Write-Host "    (none tracked)"; return }
  foreach ($k in $state.Keys) {
    $alive = if (Test-PidAlive $state[$k].pid) { 'alive' } else { 'DEAD' }
    Write-Host ("    {0,-15} pid {1,-6} {2}  started {3}" -f $k, $state[$k].pid, $alive, $state[$k].started)
  }
}

function Invoke-Doctor {
  Write-Step "Diagnostic sweep"
  Write-Host ""
  Write-Host "  Port owners:" -ForegroundColor Yellow
  foreach ($svc in $ServicePorts.Keys) {
    $port = $ServicePorts[$svc]
    $owner = Get-PortOwner $port
    if ($owner -eq 0) {
      Write-Host ("    :{0,-5} ({1,-10}) free" -f $port, $svc) -ForegroundColor DarkGray
    } else {
      $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$owner" -ErrorAction SilentlyContinue
      $cmd = if ($proc) { $proc.CommandLine } else { '?' }
      if ($cmd.Length -gt 100) { $cmd = $cmd.Substring(0,100) + '...' }
      Write-Host ("    :{0,-5} ({1,-10}) pid {2,-6} {3}" -f $port, $svc, $owner, $cmd) -ForegroundColor Yellow
    }
  }

  Write-Host ""
  Write-Host "  State-file vs reality:" -ForegroundColor Yellow
  $state = Load-State
  if ($state.Count -eq 0) {
    Write-Host "    (state file empty)"
  } else {
    foreach ($k in $state.Keys) {
      $alive = Test-PidAlive $state[$k].pid
      $tag = if ($alive) { 'alive' } else { 'DEAD (orphan possible)' }
      Write-Host ("    {0,-15} state.pid={1} {2}" -f $k, $state[$k].pid, $tag)
    }
  }

  Write-Host ""
  Write-Host "  Dev-process zoo (uvicorn / celery / vite / pnpm):" -ForegroundColor Yellow
  # Build the set of "known-good roots": PIDs in the state file plus their
  # direct descendants. The venv shim on Windows always shows up as a
  # state-file PID (venv python.exe) parenting a system-python child, so
  # we should NOT flag the state-file PID itself as orphaned just because
  # the Start-Process wrapper that spawned it has since exited.
  $knownRoots = @{}
  foreach ($k in $state.Keys) {
    $rootPid = [int]$state[$k].pid
    if ($rootPid -gt 0) { $knownRoots[$rootPid] = $true }
  }
  $zoo = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in 'python.exe','node.exe','pnpm.exe') -and
    ($_.CommandLine -match 'uvicorn|celery|vite|pnpm\s+dev|app\.main|workers\.')
  } | Sort-Object ProcessId
  if (-not $zoo) {
    Write-Host "    (no dev processes found)"
  } else {
    foreach ($p in $zoo) {
      $isStateRoot = $knownRoots.ContainsKey([int]$p.ProcessId)
      $parentIsStateRoot = $knownRoots.ContainsKey([int]$p.ParentProcessId)
      $parentAlive = Test-PidAlive $p.ParentProcessId
      # Real orphan = parent dead AND we are not a state-file root AND
      # our parent is not a state-file root either. The state-file root
      # itself having a dead grand-parent (the Start-Process wrapper) is
      # expected and benign.
      $tag = ''
      if ($isStateRoot) {
        $tag = ' [state-root]'
      } elseif ($parentIsStateRoot) {
        $tag = ' [child-of-state-root]'
      } elseif (-not $parentAlive) {
        $tag = ' [ORPHAN -- parent dead, not tracked]'
      }
      $cmd = $p.CommandLine
      if ($cmd -and $cmd.Length -gt 100) { $cmd = $cmd.Substring(0,100) + '...' }
      Write-Host ("    pid {0,-6} ppid {1,-6} {2}{3}" -f $p.ProcessId, $p.ParentProcessId, $cmd, $tag)
    }
  }

  Write-Host ""
  Write-Host "  Log sizes (under $LogDir):" -ForegroundColor Yellow
  if (Test-Path $LogDir) {
    Get-ChildItem $LogDir | Sort-Object Length -Desc | ForEach-Object {
      $mb = [Math]::Round($_.Length / 1MB, 2)
      $tag = if ($mb -gt 50) { ' <-- LARGE' } elseif ($mb -gt 10) { ' <-- bloated' } else { '' }
      Write-Host ("    {0,-30} {1,8} MB{2}" -f $_.Name, $mb, $tag)
    }
  } else {
    Write-Host "    (no log dir)"
  }
  Write-Host ""
  Write-Host "  Remediation hints:" -ForegroundColor Yellow
  Write-Host "    - Port held by orphan?    ./scripts/dev-stack.ps1 -Phase down"
  Write-Host "    - State stale + orphans?  ./scripts/dev-stack.ps1 -Phase down  (port reclaim runs unconditionally)"
  Write-Host "    - Log files bloated?      Remove-Item $LogDir\*.log  (safe when stack is down)"
}

function Invoke-Down {
  Write-Step "Stopping stack"
  $state = Load-State
  $names = @($state.Keys)
  # Stop-Background also reclaims the port for services in $ServicePorts,
  # so we always pass through it even if state is empty for a given name.
  foreach ($k in $names) { Stop-Background $k }
  # Belt-and-braces: also reclaim any port in $ServicePorts that wasn't
  # in the state file (covers fully unknown orphans).
  foreach ($svc in $ServicePorts.Keys) {
    $port = $ServicePorts[$svc]
    $owner = Get-PortOwner $port
    if ($owner -gt 0) {
      $root = Find-TreeRoot $owner
      Write-Warn2 "untracked owner on :$port (pid $owner, root $root) -- killing"
      $null = Kill-Tree $root
    }
  }

  $tile = docker ps -a --filter "name=agripulse-tileserver" --format "{{.Names}}"
  if ($tile) { docker rm -f agripulse-tileserver 2>$null | Out-Null; Write-Ok "tile-server container removed" }

  Write-Step "  docker compose down (keeps volumes)"
  docker compose -f "$ComposeFile" down
  Write-Ok "compose stopped. To also drop volumes: docker compose -f $ComposeFile down -v"
}

# ---------- orchestrate -----------------------------------------------------

switch ($Phase) {
  'preflight' { Invoke-Preflight }
  'compose'   { Invoke-Compose }
  'migrate'   { Invoke-Migrate }
  'kc-admin'  { Invoke-KcAdmin }
  'bootstrap' { Invoke-Bootstrap }
  'api'       { Invoke-Api }
  'workers'   { Invoke-Workers }
  'tile'      { Invoke-Tile }
  'frontend'  { Invoke-Frontend }
  'smoke'     { Invoke-Smoke }
  'status'    { Invoke-Status }
  'doctor'    { Invoke-Doctor }
  'down'      { Invoke-Down }
  'all' {
    Invoke-Preflight
    Invoke-Compose
    Write-Step "  waiting 20s for Keycloak realm endpoint to come up"
    Start-Sleep -Seconds 20
    Invoke-Migrate
    Invoke-KcAdmin
    Invoke-Bootstrap
    Invoke-Api
    Invoke-Workers
    Invoke-Tile
    Invoke-Frontend
    Invoke-Smoke
    Invoke-Status
  }
}

Write-Step "Done."
