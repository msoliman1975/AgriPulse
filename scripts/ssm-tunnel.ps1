#requires -Version 5.1
# Opens an SSM port-forward from localhost:8443 to the EKS API endpoint.
# Leave running in its own terminal; kubectl/helm/kcadm pick it up via
# the `agripulse-dev-tunneled` kubeconfig context.

$ErrorActionPreference = 'Stop'

$env:AWS_PROFILE = 'agripulse'

$id = aws ec2 describe-instances `
    --filters 'Name=tag:eks:cluster-name,Values=agripulse-dev' 'Name=instance-state-name,Values=running' `
    --query 'Reservations[0].Instances[0].InstanceId' `
    --output text `
    --region eu-south-1

$eks = aws eks describe-cluster `
    --name agripulse-dev `
    --region eu-south-1 `
    --query 'cluster.endpoint' `
    --output text

$ekshost = $eks -replace '^https?://', ''

if (-not $id   -or $id   -eq 'None') { throw "Could not resolve baseline node InstanceId" }
if (-not $eks  -or $eks  -eq 'None') { throw "Could not resolve EKS endpoint" }

Write-Host "instance: $id" -ForegroundColor Cyan
Write-Host "EKS host: $ekshost" -ForegroundColor Cyan
Write-Host "Tunneling localhost:8443 -> $ekshost:443 ..." -ForegroundColor Cyan

aws ssm start-session `
    --target $id `
    --document-name AWS-StartPortForwardingSessionToRemoteHost `
    --parameters "host=$ekshost,portNumber=443,localPortNumber=8443" `
    --region eu-south-1
