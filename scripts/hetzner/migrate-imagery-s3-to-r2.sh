#!/usr/bin/env bash
# Hetzner cutover — copy imagery COGs from AWS S3 to Cloudflare R2 (runbook §7).
# Uses rclone (handles S3↔R2 server-friendly, resumable, checks sizes/hashes).
# Reads R2 creds from the gitignored .r2-creds.env; AWS source creds from your
# AWS SSO profile. NO secret is written to a committed file.
#
# Prereqs: rclone installed; `aws sso login --profile agripulse` done so the
# source side can read S3.
#
# Usage:
#   source scripts/hetzner/.r2-creds.env
#   export S3_IMAGERY_BUCKET=agripulse-imagery-dev   # the AWS source bucket
#   [export AWS_PROFILE=agripulse]
#   bash scripts/hetzner/migrate-imagery-s3-to-r2.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -f "${HERE}/.r2-creds.env" ]] && source "${HERE}/.r2-creds.env"

: "${R2_ENDPOINT:?set R2_ENDPOINT (source scripts/hetzner/.r2-creds.env)}"
: "${R2_ACCESS_KEY_ID:?}"; : "${R2_SECRET_ACCESS_KEY:?}"
: "${S3_IMAGERY_BUCKET:?set S3_IMAGERY_BUCKET to the AWS source bucket}"
R2_IMAGERY_BUCKET="${R2_IMAGERY_BUCKET:-agripulse-imagery}"
export AWS_PROFILE="${AWS_PROFILE:-agripulse}"

command -v rclone >/dev/null || { echo "install rclone first: https://rclone.org/install/"; exit 1; }

# Build an ephemeral rclone config in a temp dir (deleted on exit) so no
# creds touch the repo or your real rclone.conf.
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT
export RCLONE_CONFIG="${TMP}/rclone.conf"
# Source: AWS S3 via the SSO profile (env_auth picks up AWS_PROFILE creds).
cat > "${RCLONE_CONFIG}" <<CFG
[awss3]
type = s3
provider = AWS
env_auth = true
region = ${AWS_REGION:-eu-south-1}

[r2]
type = s3
provider = Cloudflare
access_key_id = ${R2_ACCESS_KEY_ID}
secret_access_key = ${R2_SECRET_ACCESS_KEY}
endpoint = ${R2_ENDPOINT}
region = auto
CFG

echo "==> Dry-run first (no writes). Review the plan, then re-run with COPY=1."
FLAGS=(--checksum --transfers 16 --checkers 32 --fast-list --progress)
if [[ "${COPY:-0}" == "1" ]]; then
  echo "    COPYING s3://${S3_IMAGERY_BUCKET} -> r2:${R2_IMAGERY_BUCKET}"
  rclone copy "awss3:${S3_IMAGERY_BUCKET}" "r2:${R2_IMAGERY_BUCKET}" "${FLAGS[@]}"
  echo "==> Verify parity:"
  rclone check "awss3:${S3_IMAGERY_BUCKET}" "r2:${R2_IMAGERY_BUCKET}" --one-way --fast-list || true
else
  rclone copy "awss3:${S3_IMAGERY_BUCKET}" "r2:${R2_IMAGERY_BUCKET}" "${FLAGS[@]}" --dry-run
  echo "    (dry-run only — re-run with COPY=1 to actually copy)"
fi
