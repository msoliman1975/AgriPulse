#!/usr/bin/env bash
# Hetzner provisioning — step 1 of the cutover (docs/runbooks/hetzner-migration.md §0–§1).
# Runs on YOUR machine. Creates the CPX41 node, a detachable volume for Postgres,
# and a firewall. Idempotent-ish: re-running skips resources that already exist.
#
# Prereqs (install once):
#   - hcloud CLI:  https://github.com/hetznercloud/cli  (brew install hcloud / scoop install hcloud)
#   - A Hetzner Cloud project + API token (Console → Security → API Tokens, Read&Write).
#   - An SSH key uploaded to the project (or pass SSH_KEY_NAME of an existing one).
#
# Usage:
#   export HCLOUD_TOKEN=...           # project API token
#   export SSH_KEY_NAME=my-key        # name of an SSH key already in the project
#   [export LOCATION=fsn1]            # fsn1/nbg1/hel1 (EU). Default fsn1 (Falkenstein).
#   [export SERVER_NAME=agripulse-1]  # default agripulse-1
#   [export SERVER_TYPE=cpx41]        # 8 vCPU / 16 GB. cpx51 for headroom.
#   [export VOLUME_SIZE=160]          # GiB for the PG volume (data 100 + WAL 30 + slack)
#   bash scripts/hetzner/01-provision.sh
set -euo pipefail

: "${HCLOUD_TOKEN:?set HCLOUD_TOKEN to your Hetzner project API token}"
: "${SSH_KEY_NAME:?set SSH_KEY_NAME to an SSH key already uploaded to the project}"
LOCATION="${LOCATION:-fsn1}"
SERVER_NAME="${SERVER_NAME:-agripulse-1}"
SERVER_TYPE="${SERVER_TYPE:-cpx41}"
VOLUME_NAME="${VOLUME_NAME:-agripulse-pg}"
VOLUME_SIZE="${VOLUME_SIZE:-160}"
FIREWALL_NAME="${FIREWALL_NAME:-agripulse-fw}"
IMAGE="${IMAGE:-ubuntu-24.04}"

export HCLOUD_TOKEN

have() { hcloud "$@" >/dev/null 2>&1; }

echo "==> Firewall: ${FIREWALL_NAME} (allow 22/80/443, k3s API 6443 from your IP only)"
MY_IP="$(curl -fsS https://ifconfig.me)/32"
if ! have firewall describe "${FIREWALL_NAME}"; then
  hcloud firewall create --name "${FIREWALL_NAME}"
  hcloud firewall add-rule "${FIREWALL_NAME}" --direction in --protocol tcp --port 22  --source-ips 0.0.0.0/0 --source-ips ::/0
  hcloud firewall add-rule "${FIREWALL_NAME}" --direction in --protocol tcp --port 80  --source-ips 0.0.0.0/0 --source-ips ::/0
  hcloud firewall add-rule "${FIREWALL_NAME}" --direction in --protocol tcp --port 443 --source-ips 0.0.0.0/0 --source-ips ::/0
  hcloud firewall add-rule "${FIREWALL_NAME}" --direction in --protocol tcp --port 6443 --source-ips "${MY_IP}"
else
  echo "    firewall exists, leaving as-is"
fi

echo "==> Server: ${SERVER_NAME} (${SERVER_TYPE}, ${IMAGE}, ${LOCATION})"
if ! have server describe "${SERVER_NAME}"; then
  hcloud server create \
    --name "${SERVER_NAME}" \
    --type "${SERVER_TYPE}" \
    --image "${IMAGE}" \
    --location "${LOCATION}" \
    --ssh-key "${SSH_KEY_NAME}" \
    --firewall "${FIREWALL_NAME}"
else
  echo "    server exists, leaving as-is"
fi

echo "==> Volume: ${VOLUME_NAME} (${VOLUME_SIZE} GiB, attached to ${SERVER_NAME})"
if ! have volume describe "${VOLUME_NAME}"; then
  # --automount false: we format + mount deterministically in 02-node-bootstrap.sh
  hcloud volume create \
    --name "${VOLUME_NAME}" \
    --size "${VOLUME_SIZE}" \
    --server "${SERVER_NAME}" \
    --automount=false \
    --format ext4
else
  echo "    volume exists, leaving as-is"
fi

IP="$(hcloud server ip "${SERVER_NAME}")"
echo
echo "================================================================"
echo " Provisioned."
echo "   Server : ${SERVER_NAME}  (${SERVER_TYPE})"
echo "   IP     : ${IP}"
echo "   Volume : ${VOLUME_NAME}  (${VOLUME_SIZE} GiB)  -> /dev/disk/by-id/scsi-0HC_Volume_<id>"
echo
echo " Next:"
echo "   1) Lower the TTL on agripulse.cloud DNS records NOW (so cutover is fast)."
echo "   2) Create the Cloudflare R2 buckets + an API token (see §0 of the runbook):"
echo "        - agripulse-imagery   (COGs)"
echo "        - agripulse-pg-backup (CNPG/Barman)"
echo "   3) Copy the node bootstrap script up and run it on the box:"
echo "        scp scripts/hetzner/02-node-bootstrap.sh root@${IP}:/root/"
echo "        ssh root@${IP} 'bash /root/02-node-bootstrap.sh'"
echo "================================================================"
