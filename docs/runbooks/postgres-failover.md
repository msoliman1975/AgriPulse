# Postgres failover

The platform runs Postgres via CloudNativePG (CNPG) â€” primary +
synchronous standby + async standby in three AZs. Failover is automatic
in most scenarios; this runbook covers the cases where it isn't, plus
the steps to verify a clean recovery.

> **Don't read this for the first time during an incident.** Walk
> through the dry-run section in staging on every quarter end so the
> commands are in muscle memory.

---

## Topology

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    sync replica    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  primary (us-east-1a)    â”‚â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¶â”‚  standby-1 (us-east-1b)  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
              â”‚                                              â”‚
              â”‚                                async replica â”‚
              â–¼                                              â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  WAL archive (S3)        â”‚                    â”‚  standby-2 (us-east-1c)  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

CNPG uses streaming replication + a `Cluster` CRD that owns failover
decisions. PITR (point-in-time recovery) goes through the WAL archive
(barman cloud, written to `s3://agripulse-pg-wal/`).

---

## 1 â€” Symptom check

```bash
kubectl get cluster -n agripulse
# Look for: STATUS=Cluster in healthy state, PRIMARY = current primary pod.
```

Cluster shows `Failover in progress`:
- Wait 60s. CNPG default failover delay is ~30s + promotion latency.
- If still failing-over after 5 min, jump to Â§ 4 (manual intervention).

API returning 5xx with "could not connect to database":
- Apps can't reach Postgres. Could be cluster down, could be
  network. Â§ 2.

API returning OK but writes fail with "cannot execute INSERT in a
read-only transaction":
- Connections are landing on a standby instead of primary. The
  pgBouncer / API config is pointing at the read-only service. Â§ 3.

---

## 2 â€” Cluster down

Primary + both standbys unreachable usually means a cluster-wide AZ
event or accidental namespace delete.

```bash
kubectl describe cluster agripulse-pg -n agripulse | tail -50
kubectl get pods -n agripulse -l cnpg.io/cluster=agripulse-pg -o wide
```

If pods are `Pending` due to PVC issues, check the storage class +
node capacity. Re-create the cluster only as a last resort â€” recovery
goes through PITR (Â§ 5).

If pods are `Running` but not in `Cluster in healthy state`, see CNPG
operator logs:

```bash
kubectl logs -n cnpg-system deploy/cnpg-controller-manager --tail 200
```

---

## 3 â€” App talking to the wrong endpoint

CNPG exposes three services per cluster:
- `agripulse-pg-rw` â€” primary (read-write).
- `agripulse-pg-r` â€” any healthy member (read-only).
- `agripulse-pg-ro` â€” async standbys only (read-only).

Apps must point at `-rw`. Check the connection string in the API
deployment:

```bash
kubectl get deploy api -n agripulse -o yaml | grep -A2 DATABASE_URL
```

Expected: `â€¦@agripulse-pg-rw.agripulse.svc.cluster.local:5432/â€¦`.
If it's `-r` or `-ro`, fix the deployment manifest (or the
ExternalSecret feeding it) and roll the API.

---

## 4 â€” Manual failover

Use only when CNPG won't promote on its own (e.g. the primary is
unreachable but its pod is still `Running` and CNPG's quorum logic is
deadlocked).

```bash
# Identify the standby that's most caught-up
kubectl get pods -n agripulse -l cnpg.io/cluster=agripulse-pg \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready

# Inspect lag
kubectl exec -n agripulse agripulse-pg-1 -- psql -c '
  SELECT application_name,
         pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
    FROM pg_stat_replication;'

# Promote a specific replica
kubectl cnpg promote agripulse-pg agripulse-pg-2 -n agripulse
```

After promotion, the old primary will rejoin as a standby once it's
reachable. Verify all three pods reach `Cluster in healthy state`.

---

## 5 â€” PITR (point-in-time recovery)

When the cluster is unrecoverable or you need to roll back to before a
destructive operation (e.g. an accidental `DROP TABLE`):

```bash
# 1. Create a new cluster spec referencing the WAL archive
cat <<EOF | kubectl apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: agripulse-pg-recovered
  namespace: agripulse
spec:
  instances: 3
  bootstrap:
    recovery:
      source: agripulse-pg
      recoveryTarget:
        targetTime: "2026-05-08 14:23:00+00"   # adjust to just-before-incident
  externalClusters:
    - name: agripulse-pg
      barmanObjectStore:
        destinationPath: s3://agripulse-pg-wal/
        s3Credentials:
          accessKeyId: { ... }
          secretAccessKey: { ... }
EOF

# 2. Watch recovery progress
kubectl logs -n agripulse agripulse-pg-recovered-1 -f | grep -i recovery

# 3. Once "Cluster in healthy state", point the app at it
kubectl set env -n agripulse deploy/api \
  DATABASE_URL='postgresql+asyncpg://...@agripulse-pg-recovered-rw.agripulse.svc.cluster.local:5432/agripulse'

# 4. Cut DNS / service ownership over (out of scope for this runbook â€”
#    coordinate with the platform-on-call to flip the public hostname).

# 5. After verification, archive the old cluster + delete it.
```

A clean PITR usually completes in 10â€“30 minutes for our current data
volume. Test this every quarter against a fresh `agripulse-pg-pitr-test`
cluster â€” the recoveryTarget there can be `targetTime: now() - INTERVAL
'15 minutes'` so the test is harmless.

---

## 6 â€” Verify after any failover

```bash
# Smoke test from the API pod
kubectl exec -n agripulse deploy/api -- psql "$DATABASE_URL" -c '
  SELECT count(*) FROM public.tenants WHERE status = $$active$$;
  SELECT max(time) FROM public.audit_events_archive;'

# All migrations are applied
kubectl exec -n agripulse deploy/api -- alembic -c alembic.ini -n public current
kubectl exec -n agripulse deploy/api -- alembic -c alembic.ini -n tenant -x schema=tenant_<sample> current
```

Output the migration head + match against `git rev-parse HEAD` to
confirm no rows drifted during recovery.

---

## 7 â€” Pre-DDL snapshot (preventive)

Before any non-trivial migration in production:

```bash
# Logical dump of one tenant (point-in-time, doesn't block writers)
kubectl exec -n agripulse agripulse-pg-1 -- \
  pg_dump --schema=tenant_<uuid> --format=custom \
  --file=/tmp/tenant-<slug>-pre-migration.dump "$DATABASE_URL"

kubectl cp agripulse-pg-1:/tmp/tenant-<slug>-pre-migration.dump \
  ./backups/tenant-<slug>-$(date -u +%Y%m%dT%H%M%SZ).dump

aws s3 cp ./backups/tenant-<slug>-*.dump \
  s3://agripulse-pre-migration-snapshots/ --storage-class GLACIER
```

This is cheap insurance â€” Glacier storage for these is < $0.01/tenant/month.
