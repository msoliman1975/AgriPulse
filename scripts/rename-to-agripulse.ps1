<#
.SYNOPSIS
  Mechanical case-aware rename: MissionAgre -> AgriPulse across the repo.

.DESCRIPTION
  Replaces all four casings of the brand name plus the two domain-like
  strings (missionagre.io -> agripulse.cloud, missionagre.local ->
  agripulse.local). Skips binaries, lockfiles, vendored deps, and VCS
  metadata.

  File and directory renames (e.g., the Keycloak realm JSON files) are NOT
  handled here — see docs/runbooks/rename-to-agripulse.md for the manual
  steps to run before/after this script.

.PARAMETER DryRun
  Print what would change without writing.

.PARAMETER Root
  Repo root. Defaults to current working directory.

.EXAMPLE
  pwsh -File scripts/rename-to-agripulse.ps1 -DryRun
  pwsh -File scripts/rename-to-agripulse.ps1
#>

[CmdletBinding()]
param(
  [switch]$DryRun,
  [string]$Root = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

# Order matters: longer/more-specific patterns first so we don't double-replace.
# The domain entries MUST run before the bare 'missionagre' rule, otherwise
# the bare rule would eat the brand half and we'd lose the TLD swap.
$replacements = @(
  @{ From = 'MissionAgre';        To = 'AgriPulse'       },   # PascalCase
  @{ From = 'MISSIONAGRE';        To = 'AGRIPULSE'       },   # CONSTANT_CASE
  @{ From = 'missionagre\.io';    To = 'agripulse.cloud' },   # synthetic namespaces (ProblemDetails URIs, K8s annotation prefix)
  @{ From = 'missionagre\.local'; To = 'agripulse.local' },   # dev hostnames
  @{ From = 'missionagre';        To = 'agripulse'       },   # lowercase / kebab / dns / db role
  @{ From = 'Agri\.Pulse';        To = 'AgriPulse'       },   # unify dotted brand variant
  @{ From = 'mission_agre';       To = 'agripulse'       }    # snake_case (defensive)
)

# Directory names to skip entirely
$excludeDirs = @(
  '\.git', 'node_modules', '\.venv', 'venv', 'dist', 'build', '\.next',
  '__pycache__', '\.pytest_cache', '\.terraform', 'coverage', '\.idea', '\.vscode',
  '\.claude',          # user-local Claude settings
  '\.run-logs'         # backend/.run-logs — generated uvicorn/celery logs
)

# File patterns to skip (lockfiles regenerate, binaries un-grep-able,
# generated artifacts, and this rename infrastructure itself).
$excludeFiles = @(
  'uv\.lock', 'package-lock\.json', 'pnpm-lock\.yaml', 'yarn\.lock',
  '\.tfstate(\.backup)?$',
  'coverage\.xml',                        # generated test report
  'rename-dryrun\.log',                   # output of this script
  'rename-to-agripulse\.ps1',             # the script itself (would corrupt its own patterns)
  'rename-to-agripulse\.md',              # the runbook (documents from->to mapping)
  '\.(png|jpg|jpeg|gif|webp|ico|pdf|zip|gz|tar|woff2?|ttf|eot|mp4|mov)$'
)

$excludeDirPattern  = '(?i)[\\/](' + ($excludeDirs  -join '|') + ')([\\/]|$)'
$excludeFilePattern = '(?i)(' + ($excludeFiles -join '|') + ')$'

$filesChanged = 0
$totalSubs    = 0
$utf8NoBom    = New-Object System.Text.UTF8Encoding($false)

Get-ChildItem -Path $Root -Recurse -File | Where-Object {
  $_.FullName -notmatch $excludeDirPattern -and
  $_.Name     -notmatch $excludeFilePattern
} | ForEach-Object {
  $path = $_.FullName
  try {
    $orig = Get-Content -LiteralPath $path -Raw -ErrorAction Stop
  } catch {
    return
  }
  if ($null -eq $orig -or $orig.Length -eq 0) { return }

  # Skip binary-looking files (presence of NUL byte)
  if ($orig.IndexOf([char]0) -ge 0) { return }

  $new = $orig
  $fileSubs = 0
  foreach ($r in $replacements) {
    $count = [regex]::Matches($new, $r.From).Count
    if ($count -gt 0) {
      $new = [regex]::Replace($new, $r.From, $r.To)
      $fileSubs += $count
    }
  }

  if ($fileSubs -gt 0 -and $new -ne $orig) {
    $filesChanged++
    $totalSubs += $fileSubs
    $rel = $path.Substring($Root.Length).TrimStart('\','/')
    Write-Host ("{0,5} subs  {1}" -f $fileSubs, $rel)
    if (-not $DryRun) {
      [System.IO.File]::WriteAllText($path, $new, $utf8NoBom)
    }
  }
}

Write-Host ""
Write-Host ("Files changed:      {0}" -f $filesChanged)
Write-Host ("Total replacements: {0}" -f $totalSubs)
if ($DryRun) { Write-Host "(dry-run - no files written)" }
