#!/usr/bin/env bash
# Hetzner cutover — seed the Cloudflare R2 credentials as a Kubernetes Secret.
# Runs against the live k3s cluster (after 02-node-bootstrap.sh). Reads the
# real values from the gitignored scripts/hetzner/.r2-creds.env (or from the
# environment) — NO secret ever lives in a committed file.
#
# The Secret `agripulse-r2` is consumed by:
#   - CNPG Cluster (barmanObjectStore.s3Credentials) for backups → agripulse-pg-backup
#   - api / workers / tile-server for imagery object storage → agripulse-imagery
#
# Usage (KUBECONFIG must point at the Hetzner cluster):
#   source scripts/hetzner/.r2-creds.env   # or export the R2_* vars yourself
#   bash scripts/hetzner/03-seed-r2-secret.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -f "${HERE}/.r2-creds.env" ]] && source "${HERE}/.r2-creds.env"

: "${R2_ENDPOINT:?set R2_ENDPOINT (source scripts/hetzner/.r2-creds.env)}"
: "${R2_ACCESS_KEY_ID:?set R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?set R2_SECRET_ACCESS_KEY}"
NS="${NS:-agripulse}"

kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -

# Keys named to suit both consumers: CNPG references ACCESS_KEY_ID /
# SECRET_ACCESS_KEY; the app reads ENDPOINT + REGION + bucket names too.
kubectl -n "${NS}" create secret generic agripulse-r2 \
  --from-literal=ACCESS_KEY_ID="${R2_ACCESS_KEY_ID}" \
  --from-literal=SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY}" \
  --from-literal=ENDPOINT="${R2_ENDPOINT}" \
  --from-literal=REGION="${R2_REGION:-auto}" \
  --from-literal=IMAGERY_BUCKET="${R2_IMAGERY_BUCKET:-agripulse-imagery}" \
  --from-literal=BACKUP_BUCKET="${R2_BACKUP_BUCKET:-agripulse-pg-backup}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret agripulse-r2 seeded into namespace ${NS}."
echo "CNPG backup endpointURL (put in the Cluster spec at deploy): ${R2_ENDPOINT}"
