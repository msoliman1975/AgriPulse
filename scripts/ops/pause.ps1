#requires -Version 5.1
# Tier-1 pause for the dev/demo cluster (account 328972548541, agripulse-dev).
# Design: scripts/../../memory/project_aws_cost_pause_plan.md.
#
# Scales compute to zero; keeps EKS control plane, NAT, LBs, EBS alive. Idempotent.
# Run resume.ps1 to reverse.

$ErrorActionPreference = 'Continue'

$ARGOCD_NS    = 'argocd'
$APP_NS       = 'agripulse'
$OBS_NS       = 'observability'
$INGRESS_NS   = 'ingress-nginx'
$CNPG_CLUSTER = 'agripulse-pg'
$NODEPOOL     = 'general'

# Platform addons pin workload nodes when nothing's running; scale them down too.
# Order matters on resume — see resume.ps1.
$PLATFORM_NS  = @('cert-manager', 'cnpg-system', 'external-dns', 'external-secrets')

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }
function Done($msg) { Write-Host "OK  $msg" -ForegroundColor Green }

# --- 1/8 Context sanity ----------------------------------------------------
Info "1/8  Verifying kubectl context"
$ctx = (kubectl config current-context).Trim()
Write-Host "    context: $ctx"
if ($ctx -notmatch 'agripulse-dev') {
    Warn "Expected context to mention 'agripulse-dev'. Continue anyway? (Ctrl+C to abort)"
    [void](Read-Host -Prompt "Press Enter to continue")
}

# --- 2/8 Stop Argo so it cannot reconcile pods back ------------------------
# Scaling controllers to 0 is more reliable than per-App syncPolicy edits,
# which the ApplicationSet controller reverts within ~3 minutes.
Info "2/8  Stopping ArgoCD reconciliation"
kubectl -n $ARGOCD_NS scale statefulset/argocd-application-controller    --replicas=0 | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-applicationset-controller  --replicas=0 | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-repo-server                --replicas=0 | Out-Null
Done "ArgoCD controllers scaled to 0"

# --- 3/8 Hibernate CNPG (checkpoint + flush WAL, scale instances to 0) -----
Info "3/8  Hibernating CNPG cluster '$CNPG_CLUSTER'"
kubectl -n $APP_NS annotate "cluster/$CNPG_CLUSTER" cnpg.io/hibernation=on --overwrite | Out-Null

$timeout = 300; $elapsed = 0
while ($elapsed -lt $timeout) {
    $pods = (kubectl -n $APP_NS get pods -l "cnpg.io/cluster=$CNPG_CLUSTER" --no-headers 2>&1 |
        Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] -and $_ -notmatch 'No resources found' }) -join "`n"
    if ([string]::IsNullOrWhiteSpace($pods)) { break }
    Start-Sleep -Seconds 5; $elapsed += 5
    Write-Host "    waiting for CNPG pods to terminate ($elapsed s)..."
}
if ($elapsed -ge $timeout) { Warn "CNPG pods still present after ${timeout}s; proceeding anyway" }
else                       { Done "CNPG hibernated cleanly (PGDATA + WAL preserved)" }

# --- 4/8 Scale app workloads -----------------------------------------------
Info "4/8  Scaling app workloads to 0 in '$APP_NS'"
kubectl -n $APP_NS scale deployment  --all --replicas=0 2>$null | Out-Null
kubectl -n $APP_NS scale statefulset --all --replicas=0 2>$null | Out-Null
Done "App workloads scaled down"

# --- 5/8 Scale observability -----------------------------------------------
Info "5/8  Scaling observability to 0 in '$OBS_NS'"
kubectl -n $OBS_NS scale deployment  --all --replicas=0 2>$null | Out-Null
kubectl -n $OBS_NS scale statefulset --all --replicas=0 2>$null | Out-Null
Done "Observability scaled down"

# --- 6/8 Scale ingress (NLB stays; failing health checks are harmless) ----
Info "6/8  Scaling ingress-nginx to 0 in '$INGRESS_NS'"
kubectl -n $INGRESS_NS scale deployment --all --replicas=0 2>$null | Out-Null
Done "Ingress scaled down"

# --- 7/8 Scale platform addons + ArgoCD UI/state ---------------------------
# Each of these has a Deployment pinning a workload node. They serve no
# purpose while everything else is paused. Resume.ps1 brings them back first.
Info "7/8  Scaling platform addons to 0"
foreach ($ns in $PLATFORM_NS) {
    kubectl -n $ns scale deployment --all --replicas=0 2>$null | Out-Null
}
kubectl -n $ARGOCD_NS scale deployment/argocd-server --replicas=0 2>$null | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-redis  --replicas=0 2>$null | Out-Null
Done "Platform addons scaled down"

# --- 8/8 Choke Karpenter; consolidation drains workload nodes -------------
Info "8/8  Choking Karpenter NodePool '$NODEPOOL' (limits.cpu=0)"
$patchFile = New-TemporaryFile
Set-Content -Path $patchFile.FullName -Value '{"spec":{"limits":{"cpu":"0"}}}' -Encoding ASCII
kubectl patch "nodepool/$NODEPOOL" --type=merge --patch-file $patchFile.FullName | Out-Null
Remove-Item $patchFile.FullName -Force
Done "Karpenter will not launch new nodes"

# Wait for Karpenter to consolidate empty workload nodes.
Info "Waiting up to 5min for workload nodes to drain"
$timeout = 300; $elapsed = 0
while ($elapsed -lt $timeout) {
    $workloadNodes = (kubectl get nodes -l 'agripulse.cloud/role=workload' --no-headers 2>&1 |
        Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] -and $_ -notmatch 'No resources found' }) -join "`n"
    if ([string]::IsNullOrWhiteSpace($workloadNodes)) { break }
    Start-Sleep -Seconds 15; $elapsed += 15
    $count = ($workloadNodes -split "`n").Count
    Write-Host "    $count workload node(s) still up ($elapsed s)..."
}

Info "Final node state:"
kubectl get nodes
Done "PAUSE COMPLETE. Paused floor ~`$130-170/mo (EKS + NAT + LBs + EBS)."
Write-Host "Run scripts\ops\resume.ps1 to bring the cluster back up." -ForegroundColor Gray
