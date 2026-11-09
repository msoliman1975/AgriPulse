#!/usr/bin/env bash
# Confirm the frontend prod is actually serving is the build you promoted.
#
#   scripts/ops/verify-prod-frontend.sh <sha> [timeout-seconds]
#
# The frontend image is built with APP_VERSION=<github.sha> and vite inlines
# its 7-character form into the entry bundle (`__APP_VERSION__`, see
# frontend/vite.config.ts). So the entry script prod serves names the commit
# it was built from. This fetches https://app.agripulse.cloud/, follows the
# entry `<script src="/assets/index-*.js">`, and looks for that string.
#
# It polls until the version appears or the timeout passes (default 600 s):
# ArgoCD auto-syncs the hetzner overlay a few minutes after the promotion PR
# merges, so the first fetches usually still see the old build.
#
# Exit 0: prod serves <sha>. Exit 1: it did not within the timeout (the
# script prints which version it saw instead). Exit 2: bad usage.
#
# Frontend only. The api and workers report no version without a token.
# No authentication, read-only.

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <sha> [timeout-seconds]" >&2
  exit 2
fi

want="${1:0:7}"
timeout="${2:-600}"
base="${PROD_APP_URL:-https://app.agripulse.cloud}"
interval=20
deadline=$(( $(date +%s) + timeout ))
seen=""

while :; do
  entry=$(curl -fsS --max-time 20 "$base/" 2>/dev/null \
    | grep -oE 'src="/assets/index-[A-Za-z0-9_-]+\.js"' | head -1 | cut -d'"' -f2 || true)
  if [ -n "$entry" ]; then
    bundle=$(curl -fsS --max-time 60 "$base$entry" 2>/dev/null || true)
    # A string match, not `printf | grep -q`: grep -q exits on the first hit,
    # printf takes SIGPIPE, and pipefail turns a match into a failure.
    if [[ "$bundle" == *"\"$want\""* ]]; then
      echo "OK: $base serves frontend $want ($entry)"
      exit 0
    fi
    # Best-effort: the version constant sits beside the telemetry flag,
    # e.g. `...!=="false",Yde="64bd597";`. Only used to say what was seen.
    seen=$(printf '%s' "$bundle" | grep -oE '!=="false",[A-Za-z_$][A-Za-z0-9_$]*="[0-9a-f]{7}"' \
      | head -1 | grep -oE '[0-9a-f]{7}"$' | tr -d '"' || true)
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "FAIL: $base did not serve frontend $want within ${timeout}s (entry: ${entry:-none}, saw: ${seen:-unknown})" >&2
    exit 1
  fi
  sleep "$interval"
done
