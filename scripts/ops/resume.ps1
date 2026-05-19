#requires -Version 5.1
# Reverse of pause.ps1. Restores compute on the dev/demo cluster.
# Design: scripts/../../memory/project_aws_cost_pause_plan.md.
#
# Order matters: Karpenter -> CNPG (wait for Ready) -> apps -> Argo last.

$ErrorActionPreference = 'Continue'

$ARGOCD_NS    = 'argocd'
$APP_NS       = 'agripulse'
$OBS_NS       = 'observability'
$INGRESS_NS   = 'ingress-nginx'
$CNPG_CLUSTER = 'agripulse-pg'
$NODEPOOL     = 'general'
$NODEPOOL_CPU = '100'   # matches the helm chart default

# Platform addons paused by pause.ps1 step 7. Bring back before CNPG un-hib
# so the operator is alive to react, and before ExternalSecrets are needed.
$PLATFORM_NS  = @('cert-manager', 'cnpg-system', 'external-dns', 'external-secrets')

# Explicit app list — safer than scale --all on resume because Argo will
# correct any drift in step 6 anyway, and this avoids scaling random extras.
$APP_DEPLOYMENTS = @(
    'api', 'workers', 'frontend', 'tile-server', 'agripulse-redis'
)
$APP_STATEFULSETS = @('keycloak')  # bitnami keycloak chart uses STS

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }
function Done($msg) { Write-Host "OK  $msg" -ForegroundColor Green }

# --- 1/7 Context sanity ----------------------------------------------------
Info "1/7  Verifying kubectl context"
$ctx = (kubectl config current-context).Trim()
Write-Host "    context: $ctx"
if ($ctx -notmatch 'agripulse-dev') {
    Warn "Expected context to mention 'agripulse-dev'. Continue anyway? (Ctrl+C to abort)"
    [void](Read-Host -Prompt "Press Enter to continue")
}

# --- 2/7 Restore Karpenter NodePool ----------------------------------------
Info "2/7  Restoring Karpenter NodePool '$NODEPOOL' (limits.cpu=$NODEPOOL_CPU)"
$patchFile = New-TemporaryFile
Set-Content -Path $patchFile.FullName -Value "{`"spec`":{`"limits`":{`"cpu`":`"$NODEPOOL_CPU`"}}}" -Encoding ASCII
kubectl patch "nodepool/$NODEPOOL" --type=merge --patch-file $patchFile.FullName | Out-Null
Remove-Item $patchFile.FullName -Force
Done "Karpenter can launch nodes again"

# --- 3/7 Restore platform addons (CNPG operator must run before un-hib) ---
Info "3/7  Scaling platform addons back to 1"
foreach ($ns in $PLATFORM_NS) {
    kubectl -n $ns scale deployment --all --replicas=1 2>$null | Out-Null
}
kubectl -n $ARGOCD_NS scale deployment/argocd-server --replicas=1 2>$null | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-redis  --replicas=1 2>$null | Out-Null
# CNPG operator needs to be Ready before its annotation watcher fires.
kubectl -n cnpg-system rollout status deployment --timeout=180s | Out-Null
Done "Platform addons up"

# --- 4/7 Un-hibernate CNPG, then WAIT for primary Ready --------------------
# Apps booting before PG comes back will CrashLoopBackOff and burn time on
# exponential backoff. Always wait here.
Info "4/7  Un-hibernating CNPG cluster '$CNPG_CLUSTER'"
kubectl -n $APP_NS annotate "cluster/$CNPG_CLUSTER" cnpg.io/hibernation=off --overwrite | Out-Null

Info "Waiting up to 10min for CNPG primary Ready"
$timeout = 600; $elapsed = 0; $ready = $false
while ($elapsed -lt $timeout) {
    $phase = kubectl -n $APP_NS get "cluster/$CNPG_CLUSTER" -o jsonpath='{.status.phase}' 2>$null
    if ($phase -eq 'Cluster in healthy state') { $ready = $true; break }
    Write-Host "    phase: '$phase' ($elapsed s)"
    Start-Sleep -Seconds 15; $elapsed += 15
}
if (-not $ready) {
    Warn "CNPG not Ready after ${timeout}s. Apps will CrashLoop until PG is up."
    Warn "Investigate before continuing: kubectl -n $APP_NS describe cluster/$CNPG_CLUSTER"
    [void](Read-Host -Prompt "Press Enter to continue anyway, Ctrl+C to abort")
} else {
    Done "CNPG primary Ready"
}

# --- 5/7 Scale app workloads back up ---------------------------------------
Info "5/7  Scaling app workloads"
foreach ($d in $APP_DEPLOYMENTS) {
    kubectl -n $APP_NS scale "deployment/$d" --replicas=1 2>$null | Out-Null
}
foreach ($s in $APP_STATEFULSETS) {
    kubectl -n $APP_NS scale "statefulset/$s" --replicas=1 2>$null | Out-Null
}
Done "App workloads scaled to 1"

# --- 6/7 Scale observability + ingress -------------------------------------
Info "6/7  Scaling observability + ingress"
kubectl -n $OBS_NS     scale deployment  --all --replicas=1 2>$null | Out-Null
kubectl -n $OBS_NS     scale statefulset --all --replicas=1 2>$null | Out-Null
kubectl -n $INGRESS_NS scale deployment  --all --replicas=1 2>$null | Out-Null
Done "Observability + ingress scaled back up"

# --- 7/7 Restart Argo last; it heals any drift ----------------------------
Info "7/7  Restarting ArgoCD controllers (will reconcile remaining drift)"
kubectl -n $ARGOCD_NS scale statefulset/argocd-application-controller    --replicas=1 | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-applicationset-controller  --replicas=1 | Out-Null
kubectl -n $ARGOCD_NS scale deployment/argocd-repo-server                --replicas=1 | Out-Null
Done "ArgoCD back online"

Info "Final state:"
kubectl get nodes
Write-Host ""
kubectl -n $APP_NS get pods
Done "RESUME COMPLETE. Cluster is back to running baseline."
