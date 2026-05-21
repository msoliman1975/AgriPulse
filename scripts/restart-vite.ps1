# Restart the AgriPulse frontend Vite dev server.
#
# Vite's HMR catches most file changes, but installing a dep or hitting
# the "outdated optimize dep" 504 (pre-bundling cache stale) requires a
# full restart. This script kills whatever is bound to :5173, clears
# Vite's optimize-deps cache so pre-bundling re-runs, and re-launches
# `pnpm dev` in a new window.
#
# Usage:
#   .\scripts\restart-vite.ps1                # restart, keep cache
#   .\scripts\restart-vite.ps1 -ClearCache    # also wipe node_modules\.vite

[CmdletBinding()]
param(
    [int]$Port = 5173,
    [string]$FrontendDir = (Join-Path $PSScriptRoot "..\frontend"),
    [switch]$ClearCache
)

$FrontendDir = (Resolve-Path $FrontendDir).Path
Write-Host "[restart-vite] frontend dir: $FrontendDir"

# 1. Kill anything listening on the dev port.
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $pids = $listeners.OwningProcess | Sort-Object -Unique
    foreach ($procId in $pids) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "[restart-vite] stopping PID $procId ($($proc.ProcessName))"
            Stop-Process -Id $procId -Force
        } catch {
            Write-Host "[restart-vite] PID $procId already gone"
        }
    }
    Start-Sleep -Milliseconds 500
} else {
    Write-Host "[restart-vite] nothing listening on :$Port"
}

# 2. Optionally clear Vite's pre-bundled-deps cache. Needed when a new
#    dep was added to package.json after the dev server already started.
if ($ClearCache) {
    $cache = Join-Path $FrontendDir "node_modules\.vite"
    if (Test-Path $cache) {
        Write-Host "[restart-vite] clearing $cache"
        Remove-Item -Recurse -Force $cache
    } else {
        Write-Host "[restart-vite] no .vite cache to clear"
    }
}

# 3. Launch `pnpm dev` in a new PowerShell window so the script returns
#    immediately and the dev server keeps running.
$cmd = "Set-Location '$FrontendDir'; pnpm dev"
Start-Process powershell -ArgumentList "-NoExit","-Command",$cmd
Write-Host "[restart-vite] launched pnpm dev in a new window"
