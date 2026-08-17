#!/usr/bin/env bash
# Apply a simulation snapshot from inside the cluster.
#
# The load needs a database connection. The API does not expose one and
# deliberately never will, and prod Postgres is not reachable from a laptop
# (6443 and 5432 are both shut). So the load runs in a throwaway pod on the
# same image the platform is running, and this script is what SIM_LOAD_CMD
# points at:
#
#   SIM_LOAD_CMD='bash scripts/sim/load_via_pod.sh {schema} {snapshot} {as_of}'
#
# Usage: load_via_pod.sh <target_schema> <local_snapshot.json> <as_of_iso_date>
set -euo pipefail

SCHEMA="${1:?target schema}"
SNAPSHOT="${2:?local snapshot path}"
AS_OF="${3:?as-of ISO date}"

NODE="${SIM_NODE:-root@167.233.98.216}"
NS="${SIM_NAMESPACE:-agripulse}"
POD="${SIM_LOADER_POD:-sim-loader}"

# The loader must run an image that contains the current clone manifest, or
# tables absent from ITS CLONE_TABLES are skipped no matter what the snapshot
# carries. Default to whatever the api deployment is running.
IMAGE="${SIM_LOADER_IMAGE:-}"
if [ -z "$IMAGE" ]; then
  IMAGE=$(ssh -o BatchMode=yes "$NODE" \
    "kubectl -n $NS get deploy agripulse-api-agripulse-api -o jsonpath='{.spec.template.spec.containers[0].image}'")
fi
echo "loader image: $IMAGE"

cleanup() {
  ssh -o BatchMode=yes "$NODE" "kubectl -n $NS delete pod $POD --ignore-not-found --wait=false" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ssh -o BatchMode=yes "$NODE" "kubectl -n $NS delete pod $POD --ignore-not-found --wait=true" >/dev/null 2>&1 || true

# readOnlyRootFilesystem + runAsUser 10001 mean the snapshot needs an emptyDir.
# DATABASE_PASSWORD comes from the CNPG-managed secret, NOT from envFrom — the
# copy in agripulse-app-secrets is stale and fails auth.
ssh -o BatchMode=yes "$NODE" "kubectl -n $NS apply -f -" <<EOF >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: $POD
spec:
  restartPolicy: Never
  serviceAccountName: agripulse-api-api
  securityContext:
    fsGroup: 10001
    runAsGroup: 10001
    runAsNonRoot: true
    runAsUser: 10001
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: loader
      image: $IMAGE
      imagePullPolicy: IfNotPresent
      command: ["sleep", "1800"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: {drop: ["ALL"]}
        readOnlyRootFilesystem: true
      env:
        - name: DATABASE_PASSWORD
          valueFrom:
            secretKeyRef: {name: agripulse-pg-app, key: password}
      envFrom:
        - configMapRef: {name: agripulse-app-config}
        - configMapRef: {name: agripulse-api-agripulse-api}
        - secretRef: {name: agripulse-app-secrets}
        - secretRef: {name: agripulse-r2-gdal}
      resources:
        requests: {cpu: 200m, memory: 512Mi}
        limits: {cpu: "2", memory: 2Gi}
      volumeMounts:
        - {name: work, mountPath: /work}
        - {name: tmp, mountPath: /tmp}
  volumes:
    - {name: work, emptyDir: {}}
    - {name: tmp, emptyDir: {}}
EOF

ssh -o BatchMode=yes "$NODE" "kubectl -n $NS wait --for=condition=Ready pod/$POD --timeout=180s" >/dev/null

# Gzip over the wire: the snapshot is ~75 MB raw, ~3.5 MB compressed.
echo "copying snapshot ($(du -h "$SNAPSHOT" | cut -f1)) into $POD"
gzip -c "$SNAPSHOT" | ssh -o BatchMode=yes "$NODE" \
  "kubectl -n $NS exec -i $POD -- sh -c 'gunzip -c > /work/snap.json'"

# Run THIS CHECKOUT's clone code, not the image's. The default SIM_LOAD_CMD
# runs the local `sim_snapshot.py`, so the pod version must too, or a fix you
# have not deployed yet is silently ignored and a table missing from the
# image's CLONE_TABLES is skipped whatever the snapshot carries.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_MODULE="$REPO_ROOT/backend/app/modules/simulation/snapshot.py"
echo "shipping local clone module: $LOCAL_MODULE"
ssh -o BatchMode=yes "$NODE" "kubectl -n $NS exec -i $POD -- sh -c 'cat > /work/snapshot_local.py'" < "$LOCAL_MODULE"

ssh -o BatchMode=yes "$NODE" "kubectl -n $NS exec -i $POD -- sh -c 'cat > /work/load_driver.py'" <<'DRIVER'
import asyncio, importlib.util, json, sys
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location("snapshot_local", "/work/snapshot_local.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["snapshot_local"] = mod
spec.loader.exec_module(mod)

from app.shared.db.session import AsyncSessionLocal

target, as_of_raw = sys.argv[1], sys.argv[2]
as_of = datetime.fromisoformat(as_of_raw).replace(tzinfo=UTC)
snapshot = json.loads(Path("/work/snap.json").read_text(encoding="utf-8"))

async def main() -> int:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        report = await mod.load(session, target_schema=target, snapshot=snapshot, as_of=as_of)
    print(f"loaded into {report['target_schema']}  (shift {report['offset_days']} days)")
    for name, count in sorted(report["tables"].items()):
        print(f"  {name:32} {count:>8}")
    if report["dropped_columns"]:
        print("\n  COLUMNS DROPPED (source/target schema drift):")
        for name, cols in sorted(report["dropped_columns"].items()):
            print(f"    {name}: {', '.join(cols)}")
    if report["missing_in_source"]:
        print(f"\n  absent from snapshot: {', '.join(report['missing_in_source'])}")
    return 0

raise SystemExit(asyncio.run(main()))
DRIVER

echo "loading into $SCHEMA as-of $AS_OF"
ssh -o BatchMode=yes "$NODE" \
  "kubectl -n $NS exec $POD -- python /work/load_driver.py '$SCHEMA' '$AS_OF'"
