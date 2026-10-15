<#
.SYNOPSIS
  Create the `mango_unified` beta tree and the 14 findings it registers.

.DESCRIPTION
  Reads the two JSON bodies `scripts/build_mango_unified.py` writes and posts
  them to the authoring API:

    1. every finding code the tree registers, skipping the ones already there
    2. the tree itself, or a new draft version when the code already exists

  Nothing is published. A published beta tree still runs nothing on a
  schedule — the sweep reads stage='live' — but publishing is a decision for a
  person, so this stops at the draft and prints the designer URL.

  PowerShell rather than curl: Netskope blocks curl on this network.

.PARAMETER Username
  A platform admin to put the tree in the platform catalogue, or a tenant admin
  to put it in that tenant's. The findings go to whichever catalogue matches.

.EXAMPLE
  ./scripts/create-mango-unified.ps1 -Username admin@example.com -Password '…'

.EXAMPLE
  ./scripts/create-mango-unified.ps1 -Username … -Password … `
      -ApiBase https://dev-api.agripulse.cloud/api `
      -KeycloakBase https://dev-keycloak.agripulse.cloud
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string] $Username,
  [Parameter(Mandatory = $true)][string] $Password,
  [string] $ApiBase = "https://api.agripulse.cloud/api",
  [string] $KeycloakBase = "https://keycloak.agripulse.cloud",
  [string] $Realm = "agripulse",
  # A second copy of the tree needs its own code: codes are unique across the
  # live and beta catalogues, tenant rows included. The definition's own `code`
  # is rewritten to match, because the API refuses a payload whose code and
  # definition disagree.
  [string] $Code = "",
  # Which tree to create. The default is the one tree; the split writes four
  # more beside it, and each is created with this pointed at its file.
  [string] $DefinitionFile = "mango_unified.definition.json",
  [string] $ClientId = "agripulse-api",
  [switch] $WhatIfOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$definitionPath = Join-Path $root "docs/trees/$DefinitionFile"
$findingsPath = Join-Path $root "docs/trees/mango_unified.findings.json"

foreach ($path in @($definitionPath, $findingsPath)) {
  if (-not (Test-Path $path)) {
    throw "$path is missing. Run: python scripts/build_mango_unified.py"
  }
}

# --- token ------------------------------------------------------------------
# `agripulse-api` is a public client with direct access grants on, so a
# username and password is enough. The SPA's own PKCE flow cannot be driven
# from a script.
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

# The scope decides which catalogue the findings go in: a caller with a
# tenant_id claim authors that tenant's rows, one without authors the
# platform's. `authoringScope.ts` and `_ensure_authoring_scope` agree on this.
$payloadJson = [System.Text.Encoding]::UTF8.GetString(
  [System.Convert]::FromBase64String(
    $token.Split(".")[1].Replace("-", "+").Replace("_", "/").PadRight(
      [int][Math]::Ceiling($token.Split(".")[1].Length / 4) * 4, "=")))
$claims = $payloadJson | ConvertFrom-Json
$tenantId = $claims.tenant_id
$scope = if ($tenantId) { "tenant" } else { "platform" }
$findingsPath_api = if ($scope -eq "tenant") { "/v1/tenant/decision-tree-findings" } else { "/v1/decision-tree-findings" }
Write-Host "signed in as $Username, authoring scope: $scope"

$headers = @{ Authorization = "Bearer $token" }

function Invoke-Api {
  param([string] $Method, [string] $Path, $Body)
  $args = @{ Method = $Method; Uri = "$ApiBase$Path"; Headers = $headers }
  if ($null -ne $Body) {
    # UTF-8 by hand: the clauses and every card text are bilingual, and
    # PowerShell's default encoding mangles Arabic on the way out.
    $args.Body = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 40 -Compress))
    $args.ContentType = "application/json; charset=utf-8"
  }
  Invoke-RestMethod @args
}

# --- findings ---------------------------------------------------------------
# What the tree needs, against what a code already resolves to. The fold reads
# the platform catalogue first, so a tenant row that repeats a platform code is
# never read — it only shows up on the catalogue screen as "Shadowed". A
# tenant-scope run therefore creates a row only when neither catalogue has the
# code.
$wanted = Get-Content $findingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$own = (Invoke-Api -Method Get -Path "$findingsPath_api`?include_inactive=true").findings
$have = @($own | ForEach-Object { $_.code })
$resolves = $have
if ($scope -eq "tenant") {
  $platform = (Invoke-Api -Method Get -Path "/v1/decision-tree-findings?include_inactive=true").findings
  $resolves = @($have) + @($platform | ForEach-Object { $_.code })
  Write-Host "this tenant holds $($have.Count) codes and the platform holds $(@($platform).Count)"
}
Write-Host "the tree needs $($wanted.Count) codes"

foreach ($finding in $wanted) {
  if ($resolves -contains $finding.code) {
    Write-Host "  = $($finding.code) already resolves, left alone"
    continue
  }
  if ($WhatIfOnly) { Write-Host "  + $($finding.code) would be created"; continue }
  $body = @{
    code = $finding.code
    name_en = $finding.name_en
    name_ar = $finding.name_ar
    clause_en = $finding.clause_en
    clause_ar = $finding.clause_ar
    default_status = $finding.default_status
  }
  Invoke-Api -Method Post -Path $findingsPath_api -Body $body | Out-Null
  Write-Host "  + $($finding.code) created"
}

# --- the tree ---------------------------------------------------------------
$definition = Get-Content $definitionPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Code) {
  $definition.code = $Code
  Write-Host "creating it under the code $Code"
}
$code = $definition.code
$trees = Invoke-Api -Method Get -Path "/v1/platform/decision-trees/beta"
$tree = $trees | Where-Object { $_.code -eq $code } | Select-Object -First 1

if ($WhatIfOnly) {
  Write-Host "would $(if ($tree) { 'append a draft to' } else { 'create' }) $code"
  exit 0
}

if ($tree) {
  Invoke-Api -Method Post -Path "/v1/platform/decision-trees/beta/$($tree.id)/versions" `
    -Body @{ definition = $definition; notes = "Rebuilt from mango-unified-tree.md" } | Out-Null
  Write-Host "appended a new draft to the existing $code"
  $treeId = $tree.id
} else {
  $created = Invoke-Api -Method Post -Path "/v1/platform/decision-trees/beta" `
    -Body @{ code = $code; definition = $definition; notes = "Built from mango-unified-tree.md" }
  Write-Host "created $code"
  $treeId = $created.id
}

$appPath = if ($scope -eq "tenant") { "/decision-trees-beta/$code" } else { "/platform/decision-trees-beta/$code" }
Write-Host ""
Write-Host "tree id: $treeId"
Write-Host "open it: https://app.agripulse.cloud$appPath"
Write-Host "It is a draft. Publish it from the designer after reading the checks."
