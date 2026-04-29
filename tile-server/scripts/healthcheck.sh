#!/bin/sh
# TiTiler ships a `/healthz` endpoint on its main port. The K8s liveness
# and readiness probes hit it directly; this shim is for `docker
# compose ps` and the Dockerfile HEALTHCHECK directive.
set -eu

PORT="${PORT:-8000}"

# wget is in the upstream slim image; curl is not.
if ! wget -q -O /dev/null "http://127.0.0.1:${PORT}/healthz"; then
    echo "tile-server unhealthy"
    exit 1
fi
exit 0
