<#
.SYNOPSIS
  Point the local dev stack at either your normal checkout or the
  integration worktree that has all in-flight features merged.

.DESCRIPTION
  dev-stack.ps1 always runs the checkout it lives in. This flips the API,
  the celery workers and vite between checkouts without touching docker,
  postgres, redis or keycloak (which are shared and stay up).

  Both checkouts reuse the ONE venv and the ONE node_modules under
  projects\MissionAgre — no branch here changes dependencies, so this is
  safe. If a branch ever does add one, reinstall rather than trusting this.

.PARAMETER Target
  latest  - projects\ma-latest      (integration/local-latest: everything merged)
  mine    - projects\MissionAgre    (whatever branch you have checked out)

.EXAMPLE
  ./scripts/use-stack.ps1 -Target latest
  ./scripts/use-stack.ps1 -Target mine
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('latest', 'mine')]
  [string]$Target
)

$ErrorActionPreference = 'Stop'

$Root = if ($Target -eq 'latest') {
  'C:\Users\mosoliman\projects\ma-latest'
} else {
  'C:\Users\mosoliman\projects\MissionAgre'
}

$Venv = 'C:\Users\mosoliman\projects\MissionAgre\backend\.venv\Scripts'
$Logs = 'C:\Users\mosoliman\projects\MissionAgre\scripts\.dev-stack-logs'

if (-not (Test-Path "$Root\backend\.env")) {
  throw "$Root\backend\.env is missing. It is gitignored, so a fresh worktree never has it -- copy it from the main checkout first. Without it the API silently boots on defaults (symptom: /docs 404s)."
}

Write-Host "==> switching dev stack to: $Root" -ForegroundColor Cyan

# Free the ports by whoever holds them. Deliberately port-based rather than
# PID-based: a stale PID file can name a process Windows has since recycled
# onto something else entirely (this is how -Phase down can kill Rancher
# Desktop). The port owner is always the right target.
foreach ($port in 8000, 5173) {
  $owner = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess
  if ($owner) {
    & taskkill.exe /F /T /PID $owner 2>$null | Out-Null
    Write-Host "    freed :$port (pid $owner)"
  }
}
Get-Process -Name python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like '*MissionAgre*' } |
  ForEach-Object { & taskkill.exe /F /T /PID $_.Id 2>$null | Out-Null }
Write-Host '    celery workers stopped'

Start-Sleep -Seconds 2

$prefix = if ($Target -eq 'latest') { 'latest' } else { 'mine' }

$api = Start-Process -FilePath "$Venv\python.exe" `
  -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000' `
  -WorkingDirectory "$Root\backend" `
  -RedirectStandardOutput "$Logs\$prefix-api.out.log" `
  -RedirectStandardError "$Logs\$prefix-api.err.log" `
  -WindowStyle Hidden -PassThru
Write-Host "    api        pid $($api.Id)"

foreach ($q in 'heavy', 'light') {
  $w = Start-Process -FilePath "$Venv\python.exe" `
    -ArgumentList '-m', 'celery', '-A', "workers.$q.main", 'worker', '-Q', $q, '-n', "$q@%h", '--pool=solo', '--loglevel=INFO' `
    -WorkingDirectory "$Root\backend" `
    -RedirectStandardOutput "$Logs\$prefix-$q.out.log" `
    -RedirectStandardError "$Logs\$prefix-$q.err.log" `
    -WindowStyle Hidden -PassThru
  Write-Host "    worker-$q pid $($w.Id)"
}

Start-Process -FilePath 'pnpm.cmd' -ArgumentList 'dev' `
  -WorkingDirectory "$Root\frontend" -WindowStyle Hidden | Out-Null
Write-Host '    vite       starting on :5173'

Write-Host '==> waiting for the stack to answer...'
Start-Sleep -Seconds 14

foreach ($u in 'http://localhost:5173/', 'http://localhost:8000/docs') {
  try {
    $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 20
    Write-Host ("    ok  {0,-4} {1}" -f $r.StatusCode, $u) -ForegroundColor Green
  } catch {
    Write-Host ("    FAIL {0} -- {1}" -f $u, $_.Exception.Message) -ForegroundColor Red
  }
}

Write-Host "==> now serving: $Root" -ForegroundColor Cyan
Write-Host '    Sign out and back in if the SPA session looks wrong.'
