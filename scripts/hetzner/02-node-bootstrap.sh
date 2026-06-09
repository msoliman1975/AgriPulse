#!/usr/bin/env bash
# Hetzner cutover — step 2 (docs/runbooks/hetzner-migration.md §1–§2).
# Runs ON the Hetzner box as root. Mounts the PG volume, installs k3s
# (Traefik disabled so we keep the existing ingress-nginx config unchanged;
# klipper servicelb kept so the ingress LB binds the node IP), points the
# built-in local-path provisioner at the volume so Postgres data lands on
# the detachable disk, then installs ArgoCD.
#
# Idempotent: safe to re-run.
set -euo pipefail

PG_MOUNT="${PG_MOUNT:-/mnt/pgdata}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"

echo "==> 1/4 Mount the Hetzner PG volume at ${PG_MOUNT}"
# Hetzner volumes surface as /dev/disk/by-id/scsi-0HC_Volume_<id>. There is
# exactly one attached volume in this single-node design.
DEV="$(readlink -f /dev/disk/by-id/scsi-0HC_Volume_* | head -n1 || true)"
if [[ -z "${DEV}" || ! -b "${DEV}" ]]; then
  echo "ERROR: no Hetzner volume found under /dev/disk/by-id/scsi-0HC_Volume_*" >&2
  echo "       Attach the volume to this server first (01-provision.sh does this)." >&2
  exit 1
fi
echo "    device: ${DEV}"
if ! blkid "${DEV}" >/dev/null 2>&1; then
  echo "    no filesystem found; creating ext4"
  mkfs.ext4 -F "${DEV}"
fi
mkdir -p "${PG_MOUNT}"
UUID="$(blkid -s UUID -o value "${DEV}")"
if ! grep -q "${UUID}" /etc/fstab; then
  echo "UUID=${UUID} ${PG_MOUNT} ext4 discard,nofail,defaults 0 0" >> /etc/fstab
fi
mount -a
chmod 0700 "${PG_MOUNT}"
echo "    mounted: $(findmnt -no SOURCE,TARGET "${PG_MOUNT}")"

echo "==> 2/4 Install k3s (Traefik off, servicelb on)"
if ! command -v k3s >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --write-kubeconfig-mode 644" sh -
else
  echo "    k3s already installed"
fi
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes

echo "==> 3/4 Point local-path provisioner at the volume (${PG_MOUNT})"
# k3s ships local-path-provisioner defaulting to the OS disk; repoint it so
# CNPG's PVCs land on the detachable volume. Affects all local-path PVCs —
# fine on a single node where Postgres is the stateful workload that matters.
# k3s creates the ConfigMap a few seconds after first start, so wait for it.
echo "    waiting for k3s to create local-path-config..."
for _ in $(seq 1 30); do
  kubectl -n kube-system get configmap local-path-config >/dev/null 2>&1 && break
  sleep 2
done
kubectl -n kube-system patch configmap local-path-config --type merge -p "$(cat <<JSON
{"data":{"config.json":"{\"nodePathMap\":[{\"node\":\"DEFAULT_PATH_FOR_NON_LISTED_NODES\",\"paths\":[\"${PG_MOUNT}\"]}]}"}}
JSON
)" || echo "    (could not patch local-path-config; patch manually later)"
kubectl -n kube-system rollout restart deploy/local-path-provisioner 2>/dev/null || true

echo "==> 4/4 Install ArgoCD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
# Server-side apply: the ApplicationSet CRD is larger than the 262144-byte
# last-applied-configuration annotation that CLIENT-side apply tries to set,
# which fails with "metadata.annotations: Too long". --server-side avoids it.
kubectl apply --server-side --force-conflicts -n argocd \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
echo "    waiting for argocd-server..."
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s || true

echo
echo "================================================================"
echo " Node ready: k3s up, PG volume mounted at ${PG_MOUNT}, ArgoCD installed."
echo
echo " ArgoCD initial admin password:"
echo "   kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
echo
echo " NEXT (repo side — needs the Hetzner overlay + R2/Cloudflare secrets):"
echo "   1) Seed secrets: kubectl apply the app/keycloak/R2/Cloudflare secrets"
echo "      (or run the seed script once the Hetzner overlay lands)."
echo "   2) Apply the bootstrap AppOfApps pointed at the hetzner env:"
echo "        kubectl apply -n argocd -f infra/argocd/appsets/bootstrap.yaml"
echo "   3) Migrate data: pg_dump the AWS DB -> restore into CNPG;"
echo "      copy imagery COGs S3 -> R2 (see runbook §3 steps 6-7)."
echo "================================================================"
