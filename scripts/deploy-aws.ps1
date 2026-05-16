<#
.SYNOPSIS
  AgriPulse / AgriPulse AWS deployment driver.

.DESCRIPTION
  Walks the deployment in phases. Each phase is idempotent and re-entrant.
  If a phase fails, fix the issue and re-run â€” completed steps short-circuit.

  Phases:
    1. preflight       Verify tooling, AWS auth, region, data sheet.
    2. tf-backend      Create the S3 bucket + DynamoDB table for TF state.
    3. tf-apply        terraform init + plan + apply for the env.
    4. dns-nameservers Print the Route 53 NS records to paste at registrar.
    5. seed-secrets    Push deployment-data.yaml values into Secrets Manager.
    6. argocd          Wait for ArgoCD, print initial admin password.
    7. smoke           HTTPS checks on api / app / argocd hosts.

  Default action runs every phase in order.

.PARAMETER Phase
  Run only one phase. Default: all.

.PARAMETER DataFile
  Path to the populated data sheet. Defaults to scripts/deployment-data.yaml.

.EXAMPLE
  ./scripts/deploy-aws.ps1                          # full run
  ./scripts/deploy-aws.ps1 -Phase seed-secrets      # just push secrets
  ./scripts/deploy-aws.ps1 -Phase smoke             # re-check endpoints
#>

[CmdletBinding()]
param(
  [ValidateSet('all','preflight','tf-backend','tf-apply','dns-nameservers','seed-secrets','argocd','smoke')]
  [string]$Phase = 'all',

  [string]$DataFile = "$PSScriptRoot/deployment-data.yaml"
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path "$PSScriptRoot/.."
$TfDir    = Join-Path $RepoRoot 'infra/terraform'

# ---------- helpers ---------------------------------------------------------

function Write-Step($msg)    { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "    ok: $msg" -ForegroundColor Green }
function Write-Warn2($msg)   { Write-Host "    warn: $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "    FAIL: $msg" -ForegroundColor Red; throw $msg }

function Read-DataFile {
  if (-not (Test-Path $DataFile)) {
    Write-Fail "Data sheet not found: $DataFile. Copy scripts/deployment-data.example.yaml and fill it in."
  }
  # Lightweight YAML reader: prefer `powershell-yaml` if present, else `yq`.
  if (Get-Module -ListAvailable -Name powershell-yaml) {
    Import-Module powershell-yaml
    return (Get-Content $DataFile -Raw | ConvertFrom-Yaml)
  }
  if (Get-Command yq -ErrorAction SilentlyContinue) {
    return (yq -o=json '.' $DataFile | ConvertFrom-Json -AsHashtable)
  }
  Write-Fail "Install either the PowerShell module 'powershell-yaml' or the 'yq' CLI to parse the data sheet."
}

function Require-Tool($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Fail "Missing tool: $name. See README's prerequisites section."
  }
  Write-Ok "$name present"
}

# ---------- phases ----------------------------------------------------------

function Invoke-Preflight($d) {
  Write-Step "Phase 1 â€” preflight"

  Require-Tool aws
  Require-Tool terraform
  Require-Tool kubectl
  Require-Tool helm
  Require-Tool gh

  $env:AWS_REGION = $d.aws_region
  # Do NOT use 2>&1 here — PowerShell 5.1 wraps native stderr as NativeCommandError
  # and trips $ErrorActionPreference=Stop even when the exe exits 0. Let stderr pass
  # through to the console and gate on $LASTEXITCODE instead.
  $callerText = aws sts get-caller-identity --output json
  if ($LASTEXITCODE -ne 0) {
    Write-Fail "aws sts get-caller-identity failed (exit $LASTEXITCODE). If the error above mentions SSO / expired / token, run: aws sso login --profile $($d.aws_profile)"
  }
  $callerJson = $callerText | ConvertFrom-Json
  if ($callerJson.Account -ne $d.aws_account_id) {
    Write-Fail "AWS account mismatch. Caller says $($callerJson.Account); data sheet says $($d.aws_account_id)."
  }
  if ($callerJson.Arn -match ':root$') {
    Write-Fail "Caller is root ($($callerJson.Arn)). Set `$env:AWS_PROFILE to an IAM Identity Center profile (e.g. 'agripulse') and re-run."
  }
  Write-Ok "AWS account $($callerJson.Account) ($($callerJson.Arn))"

  foreach ($k in @('brevo.password','sentinel_hub.client_secret','keycloak.admin_password','keycloak.client_secret','jwt.signing_key','postgres.superuser_password')) {
    $parts = $k.Split('.')
    $val = $d[$parts[0]][$parts[1]]
    if ([string]::IsNullOrWhiteSpace($val) -or $val -eq 'SEED_ME') {
      Write-Warn2 "$k is still SEED_ME â€” seed-secrets phase will reject."
    }
  }
  Write-Ok "preflight complete"
}

function Invoke-TfBackend($d) {
  Write-Step "Phase 2 â€” Terraform state backend"
  $bucket = "$($d.terraform_state.bucket)-$($d.aws_account_id)"
  $table  = $d.terraform_state.lock_table
  $region = $d.aws_region

  aws s3api head-bucket --bucket $bucket --region $region 2>$null
  $bucketExists = ($LASTEXITCODE -eq 0)

  if (-not $bucketExists) {
    Write-Step "Creating S3 bucket $bucket"
    aws s3api create-bucket --bucket $bucket --region $region `
      --create-bucket-configuration LocationConstraint=$region | Out-Null
    aws s3api put-bucket-versioning --bucket $bucket --region $region --versioning-configuration Status=Enabled | Out-Null
    aws s3api put-bucket-encryption --bucket $bucket --region $region --server-side-encryption-configuration `
      '{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"AES256\"}}]}' | Out-Null
    aws s3api put-public-access-block --bucket $bucket --region $region --public-access-block-configuration `
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" | Out-Null
    Write-Ok "bucket created + locked down"
  } else {
    Write-Ok "bucket $bucket already exists"
  }

  aws dynamodb describe-table --table-name $table --region $region 2>$null | Out-Null
  $tableExists = ($LASTEXITCODE -eq 0)
  if (-not $tableExists) {
    Write-Step "Creating DynamoDB lock table $table"
    aws dynamodb create-table --table-name $table `
      --attribute-definitions AttributeName=LockID,AttributeType=S `
      --key-schema AttributeName=LockID,KeyType=HASH `
      --billing-mode PAY_PER_REQUEST --region $region | Out-Null
    Write-Ok "lock table created"
  } else {
    Write-Ok "lock table $table already exists"
  }

  $script:TfBucket = $bucket
  $script:TfTable  = $table
}

function Invoke-TfApply($d) {
  Write-Step "Phase 3 â€” terraform apply ($($d.environment))"
  Push-Location $TfDir
  try {
    if (-not $script:TfBucket) { $script:TfBucket = "$($d.terraform_state.bucket)-$($d.aws_account_id)" }
    if (-not $script:TfTable)  { $script:TfTable  = $d.terraform_state.lock_table }

    terraform init `
      -backend-config="bucket=$($script:TfBucket)" `
      -backend-config="key=$($d.environment)/terraform.tfstate" `
      -backend-config="region=$($d.aws_region)" `
      -backend-config="encrypt=true" `
      -backend-config="dynamodb_table=$($script:TfTable)" `
      -reconfigure
    if ($LASTEXITCODE -ne 0) { Write-Fail "terraform init failed (exit $LASTEXITCODE). Fix credentials/backend, then re-run." }

    # Reduce parallelism from default 10 → 4 to avoid Netskope proxy 502s
    # on STS/AWS API calls when many requests fire concurrently.
    $planFile = Join-Path $TfDir "$($d.environment).tfplan"
    terraform plan `
      -parallelism=4 `
      -var "environment=$($d.environment)" `
      -var "tf_state_bucket=$($script:TfBucket)" `
      -var "tf_lock_table=$($script:TfTable)" `
      "-out=$planFile"
    if ($LASTEXITCODE -ne 0) { Write-Fail "terraform plan failed (exit $LASTEXITCODE)." }

    Write-Warn2 "Review the plan above. Apply? [y/N]"
    $resp = Read-Host
    if ($resp -ne 'y') { Write-Fail "user aborted" }

    terraform apply -parallelism=4 "$planFile"
    if ($LASTEXITCODE -ne 0) { Write-Fail "terraform apply failed (exit $LASTEXITCODE)." }

    terraform output -json | Out-File -Encoding utf8 (Join-Path $RepoRoot "$($d.environment).outputs.json")
    if ($LASTEXITCODE -ne 0) { Write-Fail "terraform output failed (exit $LASTEXITCODE)." }
    Write-Ok "apply complete; outputs -> $($d.environment).outputs.json"
  } finally {
    Pop-Location
  }
}

function Invoke-DnsNameservers($d) {
  Write-Step "Phase 4 â€” Route 53 nameservers"
  $outputs = Get-Content (Join-Path $RepoRoot "$($d.environment).outputs.json") -Raw | ConvertFrom-Json
  $ns = $outputs.route53_nameservers.value
  if (-not $ns) { Write-Fail "route53_nameservers not in TF outputs â€” CD-5 may not have applied." }
  Write-Host ""
  Write-Host "  Paste these 4 NS records at your registrar ($($d.domain.registrar)) for $($d.domain.zone):" -ForegroundColor Yellow
  $ns | ForEach-Object { Write-Host "    $_" -ForegroundColor White }
  Write-Host ""
  Write-Host "  TTL: 3600. Propagation: 5-60 min. Verify with: dig NS $($d.domain.zone)" -ForegroundColor Yellow
  Write-Host ""
}

function Invoke-SeedSecrets($d) {
  Write-Step "Phase 5 â€” seed AWS Secrets Manager"
  $env = $d.environment
  $map = @{
    "agripulse/$env/brevo-smtp-password"         = $d.brevo.password
    "agripulse/$env/sentinel-hub-client-secret"  = $d.sentinel_hub.client_secret
    "agripulse/$env/keycloak-admin-password"     = $d.keycloak.admin_password
    "agripulse/$env/keycloak-client-secret"      = $d.keycloak.client_secret
    "agripulse/$env/jwt-signing-key"             = $d.jwt.signing_key
    "agripulse/$env/postgres-superuser-password" = $d.postgres.superuser_password
  }

  foreach ($id in $map.Keys) {
    $val = $map[$id]
    if ([string]::IsNullOrWhiteSpace($val) -or $val -eq 'SEED_ME') {
      Write-Fail "$id is still SEED_ME â€” fill in $DataFile first."
    }
    Write-Step "  put-secret-value $id"
    aws secretsmanager put-secret-value `
      --secret-id $id `
      --secret-string $val `
      --region $d.aws_region | Out-Null
    Write-Ok "$id seeded"
  }

  Write-Ok "ExternalSecret refreshInterval is 1h â€” restart pods or wait an hour for propagation."
}

function Invoke-ArgoCd($d) {
  Write-Step "Phase 6 â€” ArgoCD"
  aws eks update-kubeconfig --name "agripulse-$($d.environment)" --region $d.aws_region | Out-Null

  Write-Step "  waiting for argocd-server pod"
  kubectl -n argocd rollout status deployment/argocd-server --timeout=300s

  $argoHost = if ($d.environment -eq 'production') { "argocd.$($d.domain.zone)" }
              else                                  { "argocd.$($d.environment).$($d.domain.zone)" }

  $pwd = aws secretsmanager get-secret-value `
    --secret-id "agripulse/$($d.environment)/keycloak-admin-password" `
    --region $d.aws_region `
    --query SecretString --output text
  Write-Host ""
  Write-Host "  ArgoCD UI: https://$argoHost" -ForegroundColor Yellow
  Write-Host "  Username:  admin" -ForegroundColor Yellow
  Write-Host "  Password:  (from SM agripulse/$($d.environment)/keycloak-admin-password)" -ForegroundColor Yellow
  Write-Host ""
  Write-Host "  Bootstrap AppSet status:" -ForegroundColor Yellow
  kubectl -n argocd get applications.argoproj.io
}

function Invoke-Smoke($d) {
  Write-Step "Phase 7 â€” smoke tests"
  $env = $d.environment
  $prefix = if ($env -eq 'production') { '' } else { "$env." }
  $hosts = @(
    "https://api.$prefix$($d.domain.zone)/healthz",
    "https://app.$prefix$($d.domain.zone)/",
    "https://auth.$prefix$($d.domain.zone)/realms/agripulse/.well-known/openid-configuration",
    "https://argocd.$prefix$($d.domain.zone)/"
  )
  foreach ($u in $hosts) {
    try {
      $r = Invoke-WebRequest -Uri $u -Method Head -UseBasicParsing -TimeoutSec 10
      Write-Ok "$($r.StatusCode) $u"
    } catch {
      Write-Warn2 "FAIL $u â€” $($_.Exception.Message)"
    }
  }
}

# ---------- orchestrate -----------------------------------------------------

$data = Read-DataFile
$env:AWS_REGION         = $data.aws_region
$env:AWS_DEFAULT_REGION = $data.aws_region
if ($data.aws_profile) { $env:AWS_PROFILE = $data.aws_profile }

switch ($Phase) {
  'preflight'        { Invoke-Preflight $data }
  'tf-backend'       { Invoke-TfBackend $data }
  'tf-apply'         { Invoke-TfApply $data }
  'dns-nameservers'  { Invoke-DnsNameservers $data }
  'seed-secrets'     { Invoke-SeedSecrets $data }
  'argocd'           { Invoke-ArgoCd $data }
  'smoke'            { Invoke-Smoke $data }
  'all' {
    Invoke-Preflight $data
    Invoke-TfBackend $data
    Invoke-TfApply $data
    Invoke-DnsNameservers $data
    Write-Warn2 "Pausing â€” paste the nameservers at your registrar, then press Enter."
    Read-Host | Out-Null
    Invoke-SeedSecrets $data
    Invoke-ArgoCd $data
    Invoke-Smoke $data
  }
}

Write-Step "Done."
