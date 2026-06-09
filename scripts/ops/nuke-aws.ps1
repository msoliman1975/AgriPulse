#requires -Version 5.1
<#
.SYNOPSIS
    Full AWS decommission for AgriPulse -- tears the dev/demo deployment down to
    ZERO recurring billing. Intended to run ONCE, after the Cloudflare/Hetzner
    cutover passes smoke and AWS is no longer the live environment.

.DESCRIPTION
    A naive `terraform destroy` is NOT enough to stop billing here, because the
    most expensive long-tail resources are not in Terraform state:

      * Karpenter-launched EC2 nodes        (Karpenter owns them, not TF)
      * The NLB + ENIs from the ingress      (k8s cloud-controller owns them)
        Service type=LoadBalancer            -> these also BLOCK vpc/subnet destroy
      * EBS volumes from CNPG / PVCs         (ebs-csi owns them)
      * EBS snapshots                        (survive destroy entirely)
      * Versioned S3 buckets                 (destroy refuses while versions exist)
      * tfstate bucket + DynamoDB lock table (created outside TF by bootstrap)
      * KMS key                              (bills ~$1/mo until deletion scheduled)
      * Route53 zone + external-dns records  (records block zone deletion)

    So this runs in phases: drain k8s cloud resources -> terraform destroy ->
    tag-based orphan sweep -> residual cleanup -> verify. It is idempotent and
    safe to re-run; each step tolerates "already gone".

    Account CLOSURE is deliberately NOT automated here (it is a console action
    with a 90-day grace window and org-membership implications). See the runbook
    section printed at the end and docs/runbooks/hetzner-migration.md.

.PARAMETER Execute
    Without this switch the script runs DRY (prints every action, changes
    nothing). This is the default and the safe mode. Review the dry-run output
    first, every time.

.PARAMETER ConfirmPhrase
    Required when -Execute is set. Must equal exactly:
        NUKE agripulse 328972548541
    A guard against a fat-fingered -Execute against the wrong account.

.PARAMETER Profile
    AWS CLI profile. Defaults to 'agripulse' (IAM Identity Center SSO).

.PARAMETER Region
    Defaults to eu-south-1.

.PARAMETER SkipTerraform
    Skip the `terraform destroy` phase (e.g. state already gone / drifted) and
    rely purely on the tag-based sweep. The sweep alone can fully decommission a
    drifted stack, but leaves the TF state itself untouched.

.EXAMPLE
    # 1. Always start here -- see exactly what it would touch:
    pwsh scripts/ops/nuke-aws.ps1

.EXAMPLE
    # 2. When you're ready to actually destroy:
    pwsh scripts/ops/nuke-aws.ps1 -Execute -ConfirmPhrase "NUKE agripulse 328972548541"
#>
[CmdletBinding()]
param(
    [switch] $Execute,
    [string] $ConfirmPhrase = "",
    [string] $Profile       = "agripulse",
    [string] $Region        = "eu-south-1",
    [switch] $SkipTerraform
)

$ErrorActionPreference = 'Continue'

# --- Constants tied to this account/stack ---------------------------------
$EXPECTED_ACCOUNT = '328972548541'
$EXPECTED_PHRASE  = "NUKE agripulse $EXPECTED_ACCOUNT"
$PROJECT_TAG      = 'agripulse'           # default_tags Project=agripulse on every TF resource
$CLUSTER_NAME     = 'agripulse-dev'
$BUCKET_PREFIX    = 'agripulse-'          # every bucket this project owns starts with this
$STATE_BUCKET     = "agripulse-tfstate-$EXPECTED_ACCOUNT"
$LOCK_TABLE       = 'agripulse-tfstate-lock'
$ROOT_DOMAIN      = 'agripulse.cloud'
$TF_DIR           = Join-Path $PSScriptRoot '..\..\infra\terraform'

$env:AWS_PROFILE         = $Profile
$env:AWS_DEFAULT_REGION  = $Region
$env:AWS_PAGER           = ''             # never invoke an interactive pager

# --- Output helpers (match scripts/ops/pause.ps1 style) -------------------
function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Done($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Step($m) { Write-Host ""; Write-Host "### $m" -ForegroundColor Magenta }

# Act: the single chokepoint between dry-run and reality. In dry mode it only
# prints; with -Execute it invokes the scriptblock. ALWAYS route mutations here.
function Act([string]$desc, [scriptblock]$action) {
    if ($Execute) {
        Write-Host "  -> $desc" -ForegroundColor White
        & $action
    } else {
        Write-Host "  [DRY-RUN] would: $desc" -ForegroundColor DarkGray
    }
}

# aws(): thin wrapper so every call inherits profile/region and stays quiet on
# the benign "does not exist / already deleted" errors that make re-runs noisy.
function aws-q {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    $out = & aws @Args 2>&1
    return $out
}

# ==========================================================================
# 0/10  Preflight + guardrails
# ==========================================================================
Step "0/10  Preflight"

foreach ($tool in @('aws','kubectl','terraform')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Warn "'$tool' not found on PATH. Some phases will be skipped."
    }
}

Info "Resolving caller identity (profile=$Profile, region=$Region)"
$idJson = & aws sts get-caller-identity --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn "aws sts get-caller-identity failed. Are you logged in? Try: aws sso login --profile $Profile"
    Write-Host $idJson
    exit 1
}
$id = $idJson | ConvertFrom-Json
Write-Host "    account: $($id.Account)"
Write-Host "    arn:     $($id.Arn)"

if ($id.Account -ne $EXPECTED_ACCOUNT) {
    Warn "Account $($id.Account) != expected $EXPECTED_ACCOUNT. ABORTING -- wrong account."
    exit 1
}
Done "Account verified ($EXPECTED_ACCOUNT)"

if (-not $Execute) {
    Warn "DRY-RUN mode (default). Nothing will be changed."
    Warn "Re-run with:  -Execute -ConfirmPhrase `"$EXPECTED_PHRASE`"  to actually destroy."
} else {
    if ($ConfirmPhrase -ne $EXPECTED_PHRASE) {
        Warn "-Execute requires -ConfirmPhrase `"$EXPECTED_PHRASE`" (got: `"$ConfirmPhrase`")."
        Warn "ABORTING."
        exit 1
    }
    Write-Host ""
    Warn "================  LIVE DESTRUCTION MODE  ================"
    Warn "This will IRREVERSIBLY delete the AgriPulse AWS deployment"
    Warn "in account $EXPECTED_ACCOUNT / $Region."
    Warn "Last chance: Ctrl+C within 10s to abort."
    Start-Sleep -Seconds 10
    Warn "Proceeding."
}

# ==========================================================================
# 1/10  Drain Kubernetes-owned cloud resources (LBs, Karpenter nodes, EBS)
#        These are NOT in TF state and otherwise block / outlive destroy.
# ==========================================================================
Step "1/10  Drain Kubernetes-owned AWS resources"

$kubeOk = $false
if (Get-Command kubectl -ErrorAction SilentlyContinue) {
    # Refresh kubeconfig best-effort; cluster may already be gone.
    & aws eks update-kubeconfig --name $CLUSTER_NAME --region $Region 2>&1 | Out-Null
    $ctx = (& kubectl config current-context 2>&1)
    if ($LASTEXITCODE -eq 0 -and "$ctx" -match $CLUSTER_NAME) {
        # Is the API actually reachable?
        & kubectl get ns 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $kubeOk = $true }
    }
}

if (-not $kubeOk) {
    Warn "EKS API not reachable (cluster may already be destroyed). Skipping k8s drain."
    Warn "The tag-based sweep in phase 3 will catch any orphaned NLB/ENIs/EBS."
} else {
    Done "Connected to $CLUSTER_NAME"

    # 1a. Delete every type=LoadBalancer Service -> releases the NLB + its ENIs.
    Info "Deleting Service type=LoadBalancer (releases NLB + ENIs that block VPC destroy)"
    $lbSvcs = & kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}' 2>&1
    foreach ($line in ($lbSvcs -split "`n" | Where-Object { $_ -match '\S' })) {
        $ns, $name = $line.Trim() -split '\s+', 2
        Act "kubectl -n $ns delete svc $name" { & kubectl -n $ns delete svc $name --wait=false 2>&1 | Out-Null }
    }

    # 1b. Tell Karpenter to terminate its nodes: delete NodePools + NodeClaims.
    Info "Deleting Karpenter NodePools + NodeClaims (terminates Karpenter EC2)"
    Act "kubectl delete nodepools --all" { & kubectl delete nodepools.karpenter.sh --all 2>&1 | Out-Null }
    Act "kubectl delete nodeclaims --all" { & kubectl delete nodeclaims.karpenter.sh --all 2>&1 | Out-Null }
    Act "kubectl delete ec2nodeclasses --all" { & kubectl delete ec2nodeclasses.karpenter.k8s.aws --all 2>&1 | Out-Null }

    # 1c. Delete PVCs so ebs-csi releases the underlying EBS volumes.
    #     (CNPG/StatefulSet PVCs survive a pod delete by design -- must be explicit.)
    Info "Deleting PVCs in app + observability namespaces (releases EBS volumes)"
    foreach ($ns in @('agripulse','observability','argocd')) {
        Act "kubectl -n $ns delete pvc --all" { & kubectl -n $ns delete pvc --all --wait=false 2>&1 | Out-Null }
    }

    if ($Execute) {
        Info "Waiting up to 4min for the NLB to deregister (so VPC destroy won't hang)..."
        $deadline = 240; $t = 0
        while ($t -lt $deadline) {
            $remaining = & kubectl get svc -A -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{"\n"}{end}' 2>&1
            if (-not ($remaining -match '\S')) { break }
            Start-Sleep -Seconds 15; $t += 15
            Write-Host "    still draining LB services ($t s)..."
        }
    }
    Done "k8s drain issued"
}

# ==========================================================================
# 2/10  terraform destroy
# ==========================================================================
Step "2/10  terraform destroy"

if ($SkipTerraform) {
    Warn "-SkipTerraform set; relying on the tag sweep instead."
} elseif (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Warn "terraform not on PATH; skipping. The sweep will still decommission resources."
} else {
    Push-Location $TF_DIR
    try {
        # State lives in S3 (see versions.tf). It must already be initialised in
        # this checkout; if not, init with the documented backend-config first.
        if (-not (Test-Path (Join-Path $TF_DIR '.terraform'))) {
            Warn "TF not initialised here. Initialising backend for dev..."
            Act "terraform init -backend-config bucket/key/region" {
                & terraform init -reconfigure `
                    -backend-config="bucket=$STATE_BUCKET" `
                    -backend-config="key=dev/terraform.tfstate" `
                    -backend-config="region=$Region" `
                    -backend-config="encrypt=true" `
                    -backend-config="dynamodb_table=$LOCK_TABLE"
            }
        }
        # environment + tf_state_bucket are required vars with no default.
        # (tf_state_bucket has no default in github-oidc.tf; without it terraform
        # blocks on an interactive prompt and hangs a non-interactive run.)
        Act "terraform destroy -auto-approve (env=dev)" {
            & terraform destroy -auto-approve -var "environment=dev" -var "tf_state_bucket=$STATE_BUCKET"
            if ($LASTEXITCODE -ne 0) {
                Warn "terraform destroy returned non-zero. The phase-3 sweep will mop up the rest."
            }
        }
    } finally {
        Pop-Location
    }
}

# ==========================================================================
# 3/10  Tag-based orphan sweep -- the safety net for everything not in TF/k8s.
#        Ordered so dependencies clear before their parents.
# ==========================================================================
Step "3/10  Orphan sweep (tag Project=$PROJECT_TAG + cluster tag)"

$tagFilter = "Name=tag:Project,Values=$PROJECT_TAG"

# 3a. EC2 instances (Karpenter leftovers / managed node group stragglers)
Info "EC2 instances"
$instIds = (& aws ec2 describe-instances --filters $tagFilter "Name=instance-state-name,Values=pending,running,stopping,stopped" `
    --query "Reservations[].Instances[].InstanceId" --output text 2>&1) -split '\s+' | Where-Object { $_ -match '^i-' }
foreach ($i in $instIds) {
    Act "terminate instance $i" { & aws ec2 terminate-instances --instance-ids $i | Out-Null }
}

# 3b. Load balancers (ELBv2 + classic) -- match by VPC tag / name. Sweep all in
#     the project VPC; ENIs they hold block subnet + SG deletion.
Info "Load balancers (ELBv2)"
$albs = (& aws elbv2 describe-load-balancers --query "LoadBalancers[].LoadBalancerArn" --output text 2>&1) -split '\s+' | Where-Object { $_ -match 'loadbalancer' }
foreach ($arn in $albs) {
    $tags = & aws elbv2 describe-tags --resource-arns $arn --query "TagDescriptions[].Tags[?Key=='Project'].Value" --output text 2>&1
    if ("$tags" -match $PROJECT_TAG -or "$arn" -match $CLUSTER_NAME) {
        Act "delete ELBv2 $arn" { & aws elbv2 delete-load-balancer --load-balancer-arn $arn | Out-Null }
    }
}
Info "Target groups (orphaned)"
$tgs = (& aws elbv2 describe-target-groups --query "TargetGroups[?VpcId!=null].TargetGroupArn" --output text 2>&1) -split '\s+' | Where-Object { $_ -match 'targetgroup' }
foreach ($tg in $tgs) {
    $tags = & aws elbv2 describe-tags --resource-arns $tg --query "TagDescriptions[].Tags[?Key=='Project'].Value" --output text 2>&1
    if ("$tags" -match $PROJECT_TAG) {
        Act "delete target group $tg" { & aws elbv2 delete-target-group --target-group-arn $tg | Out-Null }
    }
}

# 3c. EBS volumes (CNPG / PVC leftovers) -- by cluster tag and project tag.
Info "EBS volumes"
$vols = (& aws ec2 describe-volumes --filters $tagFilter --query "Volumes[].VolumeId" --output text 2>&1) -split '\s+' | Where-Object { $_ -match '^vol-' }
$volsK = (& aws ec2 describe-volumes --filters "Name=tag-key,Values=kubernetes.io/cluster/$CLUSTER_NAME" --query "Volumes[].VolumeId" --output text 2>&1) -split '\s+' | Where-Object { $_ -match '^vol-' }
foreach ($v in ($vols + $volsK | Select-Object -Unique)) {
    Act "delete volume $v" { & aws ec2 delete-volume --volume-id $v 2>&1 | Out-Null }
}

# 3d. EBS snapshots (these silently bill forever otherwise)
Info "EBS snapshots (owned by this account, project-tagged)"
$snaps = (& aws ec2 describe-snapshots --owner-ids $EXPECTED_ACCOUNT --filters $tagFilter --query "Snapshots[].SnapshotId" --output text 2>&1) -split '\s+' | Where-Object { $_ -match '^snap-' }
foreach ($s in $snaps) {
    Act "delete snapshot $s" { & aws ec2 delete-snapshot --snapshot-id $s 2>&1 | Out-Null }
}

# 3e. NAT gateways + EIPs (the big hourly + idle-address charges)
Info "NAT gateways"
$nats = (& aws ec2 describe-nat-gateways --filter $tagFilter "Name=state,Values=available,pending" --query "NatGateways[].NatGatewayId" --output text 2>&1) -split '\s+' | Where-Object { $_ -match '^nat-' }
foreach ($n in $nats) {
    Act "delete NAT gateway $n" { & aws ec2 delete-nat-gateway --nat-gateway-id $n | Out-Null }
}
if ($Execute -and $nats) { Info "Waiting 60s for NAT deletion before releasing EIPs"; Start-Sleep -Seconds 60 }
Info "Elastic IPs (release idle addresses)"
$eips = & aws ec2 describe-addresses --filters $tagFilter --query "Addresses[].AllocationId" --output text 2>&1
foreach ($a in (($eips -split '\s+') | Where-Object { $_ -match '^eipalloc-' })) {
    Act "release EIP $a" { & aws ec2 release-address --allocation-id $a 2>&1 | Out-Null }
}

# 3f. Leftover ENIs (released LBs sometimes leave 'available' ENIs that block SG/subnet)
Info "Dangling network interfaces (status=available)"
$enis = & aws ec2 describe-network-interfaces --filters "Name=status,Values=available" $tagFilter --query "NetworkInterfaces[].NetworkInterfaceId" --output text 2>&1
foreach ($e in (($enis -split '\s+') | Where-Object { $_ -match '^eni-' })) {
    Act "delete ENI $e" { & aws ec2 delete-network-interface --network-interface-id $e 2>&1 | Out-Null }
}

Done "Orphan sweep issued (re-run later to catch async-deleting resources)"

# ==========================================================================
# 4/10  S3 -- empty (ALL versions + delete markers) then delete every
#        agripulse-* bucket EXCEPT the tfstate bucket (deleted last, phase 9).
# ==========================================================================
Step "4/10  S3 buckets"

function Clear-And-Remove-Bucket([string]$bucket) {
    # Delete all object versions + delete markers in batches of 1000, then rb.
    Info "Emptying s3://$bucket (all versions)"
    if ($Execute) {
        do {
            $page = & aws s3api list-object-versions --bucket $bucket --max-items 1000 --output json 2>&1 | ConvertFrom-Json
            $items = @()
            if ($page.Versions)      { $items += $page.Versions      | ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } } }
            if ($page.DeleteMarkers) { $items += $page.DeleteMarkers | ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } } }
            if ($items.Count -gt 0) {
                $payload = @{ Objects = $items; Quiet = $true } | ConvertTo-Json -Depth 5 -Compress
                $tmp = New-TemporaryFile
                Set-Content -Path $tmp.FullName -Value $payload -Encoding ASCII
                & aws s3api delete-objects --bucket $bucket --delete file://$($tmp.FullName) 2>&1 | Out-Null
                Remove-Item $tmp.FullName -Force
                Write-Host "    deleted $($items.Count) object versions"
            }
        } while ($items.Count -gt 0)
        & aws s3api delete-bucket --bucket $bucket 2>&1 | Out-Null
        Done "Removed s3://$bucket"
    } else {
        Write-Host "  [DRY-RUN] would empty all versions and delete s3://$bucket" -ForegroundColor DarkGray
    }
}

$allBuckets = (& aws s3api list-buckets --query "Buckets[].Name" --output text 2>&1) -split '\s+' | Where-Object { $_ -like "$BUCKET_PREFIX*" }
Info "Buckets matching '$BUCKET_PREFIX*':"
$allBuckets | ForEach-Object { Write-Host "    $_" }
foreach ($b in $allBuckets) {
    if ($b -eq $STATE_BUCKET) { continue }   # state bucket handled in phase 9
    Clear-And-Remove-Bucket $b
}

# ==========================================================================
# 5/10  KMS -- schedule key deletion (min 7-day window) + drop alias.
# ==========================================================================
Step "5/10  KMS keys"
$aliases = & aws kms list-aliases --query "Aliases[?starts_with(AliasName, 'alias/agripulse')].[AliasName,TargetKeyId]" --output text 2>&1
foreach ($line in ($aliases -split "`n" | Where-Object { $_ -match '\S' })) {
    $aliasName, $keyId = $line.Trim() -split '\s+', 2
    if ($keyId) {
        Act "schedule-key-deletion $keyId (7-day window)" {
            & aws kms schedule-key-deletion --key-id $keyId --pending-window-in-days 7 2>&1 | Out-Null
        }
    }
    Act "delete-alias $aliasName" { & aws kms delete-alias --alias-name $aliasName 2>&1 | Out-Null }
}

# ==========================================================================
# 6/10  Secrets Manager -- force-delete (no recovery window = stops billing now).
# ==========================================================================
Step "6/10  Secrets Manager"
$secrets = & aws secretsmanager list-secrets --query "SecretList[?starts_with(Name, 'agripulse')].ARN" --output text 2>&1
foreach ($arn in (($secrets -split '\s+') | Where-Object { $_ -match 'secret' })) {
    Act "force-delete secret $arn" {
        & aws secretsmanager delete-secret --secret-id $arn --force-delete-without-recovery 2>&1 | Out-Null
    }
}

# ==========================================================================
# 7/10  Route53 -- delete records (except NS/SOA) then the hosted zone.
#        external-dns records are NOT in TF state and block zone deletion.
#        NOTE: this breaks DNS for agripulse.cloud. Only do this once the domain
#        is re-delegated to Cloudflare (NS changed at GoDaddy).
# ==========================================================================
Step "7/10  Route53 hosted zone ($ROOT_DOMAIN)"
$zoneId = & aws route53 list-hosted-zones-by-name --dns-name $ROOT_DOMAIN `
    --query "HostedZones[?Name=='$ROOT_DOMAIN.'].Id | [0]" --output text 2>&1
if (-not $zoneId -or "$zoneId" -eq 'None') {
    Warn "No hosted zone for $ROOT_DOMAIN found (already deleted?)."
} else {
    $zoneId = ($zoneId -replace '/hostedzone/', '').Trim()
    Info "Zone id: $zoneId"
    Warn "DNS for $ROOT_DOMAIN will STOP resolving via Route53 after this."
    Warn "Confirm the domain is already re-delegated to Cloudflare before executing."
    if ($Execute) {
        $rrJson = & aws route53 list-resource-record-sets --hosted-zone-id $zoneId --output json 2>&1 | ConvertFrom-Json
        $changes = @()
        foreach ($rr in $rrJson.ResourceRecordSets) {
            if ($rr.Type -in @('NS','SOA')) { continue }   # apex NS/SOA can't be deleted; removed with the zone
            $changes += @{ Action = 'DELETE'; ResourceRecordSet = $rr }
        }
        if ($changes.Count -gt 0) {
            $batch = @{ Changes = $changes } | ConvertTo-Json -Depth 10 -Compress
            $tmp = New-TemporaryFile
            Set-Content -Path $tmp.FullName -Value $batch -Encoding ASCII
            Act "delete $($changes.Count) record sets" {
                & aws route53 change-resource-record-sets --hosted-zone-id $zoneId --change-batch file://$($tmp.FullName) 2>&1 | Out-Null
            }
            Remove-Item $tmp.FullName -Force
        }
        Act "delete hosted zone $zoneId" { & aws route53 delete-hosted-zone --id $zoneId 2>&1 | Out-Null }
    } else {
        Write-Host "  [DRY-RUN] would delete all non-NS/SOA records then the zone $zoneId" -ForegroundColor DarkGray
    }
}

# ==========================================================================
# 8/10  CloudWatch log groups (should be near-empty -- logging disabled on dev --
#        but sweep any /aws/eks or project groups so nothing trickles charges).
# ==========================================================================
Step "8/10  CloudWatch log groups"
foreach ($prefix in @("/aws/eks/$CLUSTER_NAME", "/aws/lambda/agripulse", "agripulse")) {
    $lgs = & aws logs describe-log-groups --log-group-name-prefix $prefix --query "logGroups[].logGroupName" --output text 2>&1
    foreach ($lg in (($lgs -split '\s+') | Where-Object { $_ -match '\S' })) {
        Act "delete log group $lg" { & aws logs delete-log-group --log-group-name $lg 2>&1 | Out-Null }
    }
}

# ==========================================================================
# 9/10  Terraform state backend (created outside TF -- must be removed by hand).
#        Done LAST so `terraform destroy` above could still read state.
# ==========================================================================
Step "9/10  Terraform state backend"
& aws s3api head-bucket --bucket $STATE_BUCKET 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Warn "About to delete the TF state bucket. terraform destroy must be DONE first."
    Clear-And-Remove-Bucket $STATE_BUCKET
} else {
    Warn "State bucket $STATE_BUCKET not found (already gone?)."
}
$tableExists = & aws dynamodb describe-table --table-name $LOCK_TABLE --query "Table.TableName" --output text 2>&1
if ("$tableExists" -eq $LOCK_TABLE) {
    Act "delete DynamoDB lock table $LOCK_TABLE" { & aws dynamodb delete-table --table-name $LOCK_TABLE 2>&1 | Out-Null }
} else {
    Warn "Lock table $LOCK_TABLE not found (already gone?)."
}

# ==========================================================================
# 10/10  Verify + residual billing checklist
# ==========================================================================
Step "10/10  Verification"
Info "Remaining resources tagged Project=$PROJECT_TAG (Resource Groups Tagging API):"
& aws resourcegroupstaggingapi get-resources --tag-filters "Key=Project,Values=$PROJECT_TAG" `
    --query "ResourceTagMappingList[].ResourceARN" --output text 2>&1

Write-Host ""
Write-Host "=========================================================================" -ForegroundColor Green
$verb = if ($Execute) { 'COMPLETE' } else { 'DRY-RUN COMPLETE' }
Write-Host " AWS TEARDOWN $verb" -ForegroundColor Green
Write-Host "=========================================================================" -ForegroundColor Green
Write-Host @"

Residual-billing checklist (verify in the console 24-48h later):
  [ ] EC2  : no instances / volumes / snapshots / EIPs left (esp. EBS snapshots).
  [ ] VPC  : NAT gateways gone (hourly + data charge), VPC + subnets deleted.
  [ ] ELB  : no load balancers / target groups.
  [ ] S3   : all agripulse-* buckets gone, including tfstate.
  [ ] KMS  : key shows 'Pending deletion' (bills ~`$1/mo until the window elapses).
  [ ] Route53 : zone deleted (`$0.50/mo each) AND domain re-delegated to Cloudflare.
  [ ] Secrets Manager : 0 secrets.
  [ ] Cost Explorer : run for the *next* full day; should trend to `$0.
       aws ce get-cost-and-usage --time-period Start=<tomorrow>,End=<+2d> ``
         --granularity DAILY --metrics UnblendedCost

ACCOUNT CLOSURE (manual -- not scripted; see docs/runbooks/hetzner-migration.md):
  1. Confirm Cost Explorer shows `$0/day for 2-3 consecutive days first.
  2. Console -> Account -> 'Close Account' (or, if this is an Organizations
     member: aws organizations close-account --account-id $EXPECTED_ACCOUNT).
  3. A closed account is recoverable for 90 days, then permanently deleted.
     Any trailing usage in the closure month is still invoiced.
  4. If this is the Organization MANAGEMENT account, all member accounts must be
     closed/removed first, then close the org, then the account.
"@ -ForegroundColor Gray
