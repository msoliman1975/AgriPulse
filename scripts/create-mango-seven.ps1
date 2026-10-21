<#
.SYNOPSIS
  Create the seven mango folding trees and the finding codes they need.

.DESCRIPTION
  Posts the bodies scripts/emit_mango_seven_bodies.py writes:

    1. each new finding code, skipping any code the catalogue already resolves
    2. each tree, or a new draft version when the code already exists

  Nothing is published. A beta tree carries stage='beta' and the nightly sweep
  reads stage='live', so a draft runs on nothing. Publishing is a decision for
  a person and this script stops at the draft.

  Every body is posted as the file's raw bytes. PowerShell's own JSON round
  trip double-encodes Arabic and returns 200 while storing the wrong text, so
  this script never reads inside a body.

  PowerShell rather than curl: Netskope blocks curl on this network.

.PARAMETER Username
  A platform admin, so the trees and the findings land in the platform
  catalogue. A tenant admin would author that tenant's rows instead.

.EXAMPLE
  ./scripts/create-mango-seven.ps1 -Username dev@agripulse.local -Password '…'

.EXAMPLE
  ./scripts/create-mango-seven.ps1 -Username … -Password … -WhatIfOnly
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string] $Username,
  [Parameter(Mandatory = $true)][string] $Password,
  [string] $ApiBase = "https://api.agripulse.cloud/api",
  [string] $KeycloakBase = "https://keycloak.agripulse.cloud",
  [string] $Realm = "agripulse",
  [string] $ClientId = "agripulse-api",
  [switch] $WhatIfOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bodies = Join-Path $root "docs/trees/mango_seven/bodies"
if (-not (Test-Path $bodies)) {
  throw "$bodies is missing. Run: python scripts/build_mango_seven.py; python scripts/emit_mango_seven_bodies.py"
}

$tokenResponse = Invoke-RestMethod -Method Post `
  -Uri "$KeycloakBase/realms/$Realm/protocol/openid-connect/token" `
  -ContentType "application/x-www-form-urlencoded" `
  -Body @{
    grant_type = "password"
    client_id  = $ClientId
    username   = $Username
    password   = $Password
    scope      = "openid"
  }
$token = $tokenResponse.access_token
$headers = @{ Authorization = "Bearer $token" }

$payloadJson = [System.Text.Encoding]::UTF8.GetString(
  [System.Convert]::FromBase64String(
    $token.Split(".")[1].Replace("-", "+").Replace("_", "/").PadRight(
      [int][Math]::Ceiling($token.Split(".")[1].Length / 4) * 4, "=")))
$claims = $payloadJson | ConvertFrom-Json
if ($claims.tenant_id) {
  throw "This account carries tenant_id $($claims.tenant_id). Use a platform admin, or the trees land in that tenant's catalogue."
}
Write-Host "signed in as $Username, authoring scope: platform"

function Invoke-Api {
  param([string] $Method, [string] $Path, [string] $BodyFile)
  $callArgs = @{ Method = $Method; Uri = "$ApiBase$Path"; Headers = $headers; TimeoutSec = 90 }
  if ($BodyFile) {
    $callArgs.Body = [System.IO.File]::ReadAllBytes($BodyFile)
    $callArgs.ContentType = "application/json; charset=utf-8"
  }
  Invoke-RestMethod @callArgs
}

# --- findings ---------------------------------------------------------------
$have = @((Invoke-Api -Method Get -Path "/v1/decision-tree-findings?include_inactive=true").findings |
  ForEach-Object { $_.code })
Write-Host "the platform catalogue holds $($have.Count) codes"

$created = 0
foreach ($file in Get-ChildItem (Join-Path $bodies "finding.*.json") | Sort-Object Name) {
  $code = $file.BaseName -replace '^finding\.', ''
  if ($have -contains $code) {
    Write-Host "  = $code already resolves, left alone"
    continue
  }
  if ($WhatIfOnly) { Write-Host "  + $code would be created"; continue }
  Invoke-Api -Method Post -Path "/v1/decision-tree-findings" -BodyFile $file.FullName | Out-Null
  Write-Host "  + $code created"
  $created++
}
Write-Host "$created finding codes created"

# --- trees ------------------------------------------------------------------
$existing = @(Invoke-Api -Method Get -Path "/v1/platform/decision-trees/beta")
foreach ($file in Get-ChildItem (Join-Path $bodies "create.*.json") | Sort-Object Name) {
  $code = $file.BaseName -replace '^create\.', ''
  $tree = $existing | Where-Object { $_.code -eq $code } | Select-Object -First 1
  if ($WhatIfOnly) {
    Write-Host "  would $(if ($tree) { 'append a draft to' } else { 'create' }) $code"
    continue
  }
  if ($tree) {
    $versionFile = Join-Path $bodies "version.$code.json"
    Invoke-Api -Method Post -Path "/v1/platform/decision-trees/beta/$($tree.id)/versions" `
      -BodyFile $versionFile | Out-Null
    Write-Host "  ~ $code already existed, appended a draft version"
    $treeId = $tree.id
  } else {
    $new = Invoke-Api -Method Post -Path "/v1/platform/decision-trees/beta" -BodyFile $file.FullName
    Write-Host "  + $code created"
    $treeId = $new.id
  }
  Write-Host "    id $treeId"
  Write-Host "    https://app.agripulse.cloud/platform/decision-trees-beta/$code"
}

Write-Host ""
Write-Host "All seven are drafts. Nothing runs on a schedule until the sweep reads stage='live'."
