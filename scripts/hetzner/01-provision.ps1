#Requires -Version 5.1
<#
  Hetzner provisioning (Windows / PowerShell) - step 1 of the cutover.
  Creates the CPX41 node + detachable Postgres volume + firewall, and
  generates+uploads an SSH key if you don't already have one. Idempotent:
  re-running skips anything that already exists.

  PREREQS (install once):
    1. hcloud CLI   (installed already if you ran the helper).
    2. Windows OpenSSH (built in on Win10/11) - gives ssh-keygen / ssh / scp.
    3. A Hetzner Cloud project + API token (Read and Write).

  RUN:
    $env:HCLOUD_TOKEN = "paste-your-token"
    .\scripts\hetzner\01-provision.ps1

  Optional overrides:
    .\scripts\hetzner\01-provision.ps1 -ServerType cpx51 -Location nbg1
#>
[CmdletBinding()]
param(
  [string]$Location     = "fsn1",          # fsn1/nbg1/hel1 (EU)
  [string]$ServerName   = "agripulse-1",
  [string]$ServerType   = "cx42",          # 8 vCPU / 16 GB Intel x86 (cpx41 retired). cx52 for headroom
  [string]$Image        = "ubuntu-24.04",
  [string]$VolumeName   = "agripulse-pg",
  [int]   $VolumeSize   = 160,             # GiB (PG data 100 + WAL 30 + slack)
  [string]$FirewallName = "agripulse-fw",
  [string]$SshKeyName   = "agripulse-key"
)

# Native-command friendly: don't let cmdlet EAP interact with hcloud's stderr.
$ErrorActionPreference = "Continue"

function Die([string]$m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function HExists([string[]]$a) { & hcloud @a 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
function HRun([string[]]$a) {
  & hcloud @a
  if ($LASTEXITCODE -ne 0) { Die ("hcloud " + ($a -join ' ') + " failed (exit $LASTEXITCODE)") }
}

if (-not $env:HCLOUD_TOKEN) { Die 'Set $env:HCLOUD_TOKEN to your Hetzner project API token first.' }
if (-not (Get-Command hcloud -ErrorAction SilentlyContinue)) {
  Die "hcloud CLI not found on PATH. Open a fresh PowerShell window and retry."
}
if (-not (Get-Command ssh-keygen -ErrorAction SilentlyContinue)) {
  Die "ssh-keygen not found. Enable the Windows OpenSSH Client (Settings -> Optional features)."
}

# --- 1. SSH key: generate locally if missing, then upload to the project ----
$sshDir  = Join-Path $HOME ".ssh"
$keyPath = Join-Path $sshDir "id_ed25519"
$pubPath = "$keyPath.pub"
if (-not (Test-Path $pubPath)) {
  Write-Host "==> No SSH key at $keyPath - generating one." -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
  # Interactive: press Enter twice for an empty passphrase (simplest), or set one.
  ssh-keygen -t ed25519 -f $keyPath -C "agripulse"
  if (-not (Test-Path $pubPath)) { Die "ssh-keygen did not produce $pubPath" }
}
if (HExists @("ssh-key", "describe", $SshKeyName)) {
  Write-Host "==> SSH key '$SshKeyName' already in project."
} else {
  Write-Host "==> Uploading SSH key '$SshKeyName' to the project."
  HRun @("ssh-key", "create", "--name", $SshKeyName, "--public-key-from-file", $pubPath)
}

# --- 2. Firewall (22/80/443 open; k3s API 6443 only from your current IP) ----
if (HExists @("firewall", "describe", $FirewallName)) {
  Write-Host "==> Firewall '$FirewallName' exists - leaving as-is."
} else {
  Write-Host "==> Creating firewall '$FirewallName'." -ForegroundColor Cyan
  HRun @("firewall", "create", "--name", $FirewallName)
  foreach ($p in 22, 80, 443) {
    HRun @("firewall", "add-rule", $FirewallName, "--direction", "in", "--protocol", "tcp",
           "--port", "$p", "--source-ips", "0.0.0.0/0", "--source-ips", "::/0")
  }
  $myip = $null
  try { $myip = (Invoke-RestMethod -Uri "https://ifconfig.me/ip" -TimeoutSec 10).ToString().Trim() } catch {}
  if ($myip) {
    HRun @("firewall", "add-rule", $FirewallName, "--direction", "in", "--protocol", "tcp",
           "--port", "6443", "--source-ips", "$myip/32")
    Write-Host "    k3s API (6443) opened to your IP $myip only."
  } else {
    Write-Host "    Could not detect your public IP - 6443 left closed; add it later for kubectl."
  }
}

# --- 3. Server -------------------------------------------------------------
if (HExists @("server", "describe", $ServerName)) {
  Write-Host "==> Server '$ServerName' exists - leaving as-is."
} else {
  Write-Host "==> Creating server '$ServerName' ($ServerType, $Image, $Location)." -ForegroundColor Cyan
  HRun @("server", "create", "--name", $ServerName, "--type", $ServerType, "--image", $Image,
         "--location", $Location, "--ssh-key", $SshKeyName, "--firewall", $FirewallName)
}

# --- 4. Volume (attached + formatted; mounted by 02-node-bootstrap.sh) ------
if (HExists @("volume", "describe", $VolumeName)) {
  Write-Host "==> Volume '$VolumeName' exists - leaving as-is."
} else {
  $sizeStr = "$VolumeSize"
  Write-Host ("==> Creating volume '{0}' ({1} GiB) on '{2}'." -f $VolumeName, $sizeStr, $ServerName) -ForegroundColor Cyan
  HRun @("volume", "create", "--name", $VolumeName, "--size", $sizeStr,
         "--server", $ServerName, "--automount=false", "--format", "ext4")
}

# --- Done ------------------------------------------------------------------
$ip = (& hcloud server ip $ServerName).Trim()
$bootstrap = "ssh root@$ip 'curl -sfL https://raw.githubusercontent.com/msoliman1975/AgriPulse/main/scripts/hetzner/02-node-bootstrap.sh | bash'"
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Provisioned."
Write-Host ("   Server : {0} ({1})" -f $ServerName, $ServerType)
Write-Host "   IP     : $ip"
Write-Host ("   Volume : {0} ({1} GiB)" -f $VolumeName, $VolumeSize)
Write-Host ""
Write-Host " NEXT - bootstrap the node (repo is public, so curl|bash works):"
Write-Host "   $bootstrap"
Write-Host ""
Write-Host " (First SSH will ask to trust the host key - type 'yes'.)"
Write-Host " Also: lower agripulse.cloud DNS TTL now so cutover is fast."
Write-Host "================================================================" -ForegroundColor Green
