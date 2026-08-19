#!/usr/bin/env bash
# Attach the custom domains to the two website Workers. Run once per domain.
# Safe to run again: the API call is a PUT and returns the same record.
#
#   CLOUDFLARE_API_TOKEN=... ./infra/websites/attach-domains.sh
#
# Why this is not in wrangler.toml: wrangler reconciles routes through
# /zones/{zone}/workers/routes, which needs the zone-level "Workers Routes:
# Edit" permission. The deploy token has "Workers Scripts: Edit" only, so a
# route in the config would fail every deploy. The account-level
# /accounts/{account}/workers/domains endpoint works with the deploy token.
# Once the token carries Workers Routes: Edit, move the routes into the
# wrangler.toml files and delete this script.

set -euo pipefail

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-83c91caacdfd03a1e6cb07e4fdf882a4}"
ZONE_ID="${CLOUDFLARE_ZONE_ID:-22d77054a96695cd8253e1176d3102b7}"   # agripulse.cloud

: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN}"

attach() {
  local hostname="$1" service="$2"
  echo "attaching ${hostname} -> ${service}"
  curl -fsS -X PUT \
    "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/workers/domains" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"environment\":\"production\",\"hostname\":\"${hostname}\",\"service\":\"${service}\",\"zone_id\":\"${ZONE_ID}\"}" \
    | python -c "import json,sys; r=json.load(sys.stdin); print('  ok' if r['success'] else '  FAILED: %s' % r['errors'])"
}

attach "agripulse.cloud"      "agripulse-marketing"
attach "www.agripulse.cloud"  "agripulse-marketing"
attach "docs.agripulse.cloud" "agripulse-docs"
