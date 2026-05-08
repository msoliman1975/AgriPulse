# Postgres failover

The platform runs Postgres via CloudNativePG (CNPG) — primary +
synchronous standby + async standby in three AZs. Failover is automatic
in most scenarios; this runbook covers the cases where it isn't, plus
the steps to verify a clean recovery.

> **Don't read this for the first time during an incident.** Walk
> through the dry-run section in staging on every quarter end so the
> commands are in muscle memory.

---

## Topology

```
┌──────────────────────────┐    sync replica    ┌──────────────────────────┐
│  primary (us-east-1a)    │──────────────────▶│  standby-1 (us-east-1b)  │
└──────────────────────────┘                    └──────────────────────────┘
              │                                              │
              │                                async replica │
              ▼                                              ▼
┌──────────────────────────┐                    ┌──────────────────────────┐
│  WAL archive (S3)        │                    │  standby-2 (us-east-1c)  │
└──────────────────────────┘                    └──────────────────────────┘
```

CNPG uses streaming replication + a `Cluster` CRD that owns failover
decisions. PITR (point-in-time recovery) goes through the WAL archive
(barman cloud, written to `s3://missionagre-pg-wal/`).

---

## 1 — Symptom check

```bash
kubectl get cluster -n missionagre
# Look for: STATUS=Cluster in healthy state, PRIMARY = current primary pod.
```

Cluster shows `Failover in progress`:
- Wait 60s. CNPG default failover delay is ~30s + promotion latency.
- If still failing-over after 5 min, jump to § 4 (manual intervention).

API returning 5xx with "could not connect to database":
- Apps can't reach Postgres. Could be cluster down, could be
  network. § 2.

API returning OK but writes fail with "cannot execute INSERT in a
read-only transaction":
- Connections are landing on a standby instead of primary. The
  pgBouncer / API config is pointing at the read-only service. § 3.

---

## 2 — Cluster down

Primary + both standbys unreachable usually means a cluster-wide AZ
event or accidental namespace delete.

```bash
kubectl describe cluster missionagre-pg -n missionagre | tail -50
kubectl get pods -n missionagre -l cnpg.io/cluster=missionagre-pg -o wide
```

If pods are `Pending` due to PVC issues, check the storage class +
node capacity. Re-create the cluster only as a last resort — recovery
goes through PITR (§ 5).

If pods are `Running` but not in `Cluster in healthy state`, see CNPG
operator logs:

```bash
kubectl logs -n cnpg-system deploy/cnpg-controller-manager --tail 200
```

---

## 3 — App talking to the wrong endpoint

CNPG exposes three services per cluster:
- `missionagre-pg-rw` — primary (read-write).
- `missionagre-pg-r` — any healthy member (read-only).
- `missionagre-pg-ro` — async standbys only (read-only).

Apps must point at `-rw`. Check the connection string in the API
deployment:

```bash
kubectl get deploy api -n missionagre -o yaml | grep -A2 DATABASE_URL
```

Expected: `…@missionagre-pg-rw.missionagre.svc.cluster.local:5432/…`.
If it's `-r` or `-ro`, fix the deployment manifest (or the
ExternalSecret feeding it) and roll the API.

---

## 4 — Manual failover

Use only when CNPG won't promote on its own (e.g. the primary is
unreachable but its pod is still `Running` and CNPG's quorum logic is
deadlocked).

```bash
# Identify the standby that's most caught-up
kubectl get pods -n missionagre -l cnpg.io/cluster=missionagre-pg \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready

# Inspect lag
kubectl exec -n missionagre missionagre-pg-1 -- psql -c '
  SELECT application_name,
         pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
    FROM pg_stat_replication;'

# Promote a specific replica
kubectl cnpg promote missionagre-pg missionagre-pg-2 -n missionagre
```

After promotion, the old primary will rejoin as a standby once it's
reachable. Verify all three pods reach `Cluster in healthy state`.

---

## 5 — PITR (point-in-time recovery)

When the cluster is unrecoverable or you need to roll back to before a
destructive operation (e.g. an accidental `DROP TABLE`):

```bash
# 1. Create a new cluster spec referencing the WAL archive
cat <<EOF | kubectl apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: missionagre-pg-recovered
  namespace: missionagre
spec:
  instances: 3
  bootstrap:
    recovery:
      source: missionagre-pg
      recoveryTarget:
        targetTime: "2026-05-08 14:23:00+00"   # adjust to just-before-incident
  externalClusters:
    - name: missionagre-pg
      barmanObjectStore:
        destinationPath: s3://missionagre-pg-wal/
        s3Credentials:
          accessKeyId: { ... }
          secretAccessKey: { ... }
EOF

# 2. Watch recovery progress
kubectl logs -n missionagre missionagre-pg-recovered-1 -f | grep -i recovery

# 3. Once "Cluster in healthy state", point the app at it
kubectl set env -n missionagre deploy/api \
  DATABASE_URL='postgresql+asyncpg://...@missionagre-pg-recovered-rw.missionagre.svc.cluster.local:5432/missionagre'

# 4. Cut DNS / service ownership over (out of scope for this runbook —
#    coordinate with the platform-on-call to flip the public hostname).

# 5. After verification, archive the old cluster + delete it.
```

A clean PITR usually completes in 10–30 minutes for our current data
volume. Test this every quarter against a fresh `missionagre-pg-pitr-test`
cluster — the recoveryTarget there can be `targetTime: now() - INTERVAL
'15 minutes'` so the test is harmless.

---

## 6 — Verify after any failover

```bash
# Smoke test from the API pod
kubectl exec -n missionagre deploy/api -- psql "$DATABASE_URL" -c '
  SELECT count(*) FROM public.tenants WHERE status = $$active$$;
  SELECT max(time) FROM public.audit_events_archive;'

# All migrations are applied
kubectl exec -n missionagre deploy/api -- alembic -c alembic.ini -n public current
kubectl exec -n missionagre deploy/api -- alembic -c alembic.ini -n tenant -x schema=tenant_<sample> current
```

Output the migration head + match against `git rev-parse HEAD` to
confirm no rows drifted during recovery.

---

## 7 — Pre-DDL snapshot (preventive)

Before any non-trivial migration in production:

```bash
# Logical dump of one tenant (point-in-time, doesn't block writers)
kubectl exec -n missionagre missionagre-pg-1 -- \
  pg_dump --schema=tenant_<uuid> --format=custom \
  --file=/tmp/tenant-<slug>-pre-migration.dump "$DATABASE_URL"

kubectl cp missionagre-pg-1:/tmp/tenant-<slug>-pre-migration.dump \
  ./backups/tenant-<slug>-$(date -u +%Y%m%dT%H%M%SZ).dump

aws s3 cp ./backups/tenant-<slug>-*.dump \
  s3://missionagre-pre-migration-snapshots/ --storage-class GLACIER
```

This is cheap insurance — Glacier storage for these is < $0.01/tenant/month.
