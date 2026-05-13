# Runbook: Postgres point-in-time restore (CNPG + S3 / Barman)

Audience: on-call. Use this when the live `agripulse-pg` CNPG `Cluster`
in dev/staging/prod has lost data or is unrecoverable and you need to
roll forward from S3-backed WAL archives.

Continuous backup is configured by `infra/helm/shared/templates/postgres-cluster.yaml`
(`spec.backup.barmanObjectStore`) and the `ScheduledBackup` resource in
`infra/helm/shared/templates/scheduled-backup.yaml`. Daily base backups
run at 02:00 UTC; WAL is archived continuously to
`s3://agripulse-pg-backup-<env>/pg/`. Retention: 30 days dev, 14 days
staging, 90 days prod.

The S3 buckets, KMS key, and CNPG IRSA role are provisioned by Terraform
(`infra/terraform/s3.tf`, `infra/terraform/iam-irsa.tf`).

---

## 1. List available backups

```bash
ENV=prod
NS=agripulse

kubectl exec -n $NS postgres-cluster-1 -c postgres -- \
  barman-cloud-backup-list \
    s3://agripulse-pg-backup-$ENV/pg \
    agripulse-pg
```

The output lists base backups with `Backup ID`, `Status`, `Begin/End time`,
`Size`, and `WAL` ranges. The latest `DONE` backup is the floor of the
recovery window; you can recover to any `recoveryTarget.targetTime`
between the start of that backup and the end of the most recently
archived WAL segment.

## 2. Verify the backup is consistent

```bash
kubectl exec -n $NS postgres-cluster-1 -c postgres -- \
  barman-cloud-check-wal-archive \
    s3://agripulse-pg-backup-$ENV/pg \
    agripulse-pg
```

A clean exit means the WAL archive is intact and the backup chain is
restorable. A non-zero exit usually means a WAL segment is missing
(operator paged on `CNPGWALArchiveStalled` â€” see section 6).

## 3. Restore to a new namespace

Restore never overwrites the live cluster. Spin up a new `Cluster` in a
fresh namespace, replay WAL up to the recovery target, then cut traffic
over once verified.

```yaml
# postgres-restore.yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: pg-restore-2026-05-12
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: agripulse-pg
  namespace: pg-restore-2026-05-12
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:16.4-bookworm

  serviceAccountTemplate:
    metadata:
      annotations:
        # Same IRSA role as the source env â€” restore reads the same S3
        # bucket. From `terraform output agripulse_env_resources`.
        eks.amazonaws.com/role-arn: <cnpg_irsa_arn for source env>

  storage:
    size: 200Gi
    storageClass: gp3
  walStorage:
    size: 60Gi
    storageClass: gp3

  bootstrap:
    recovery:
      source: source-cluster
      recoveryTarget:
        # ISO-8601 UTC. Pick the moment just before the data loss.
        targetTime: "2026-05-12T13:42:00.000+00:00"

  externalClusters:
    - name: source-cluster
      barmanObjectStore:
        destinationPath: s3://agripulse-pg-backup-prod/pg
        s3Credentials:
          inheritFromIAMRole: true
        wal:
          compression: gzip
          maxParallel: 4
        serverName: agripulse-pg
```

Apply, then watch:

```bash
kubectl -n pg-restore-2026-05-12 get cluster agripulse-pg -w
kubectl -n pg-restore-2026-05-12 logs agripulse-pg-1 -c postgres -f
```

Expect the bootstrap pod to download the base backup, then replay WAL
until `targetTime`. A 200 GiB DB typically restores in 15-30 minutes
depending on WAL volume.

## 4. Verify the restored cluster

```bash
kubectl -n pg-restore-2026-05-12 exec agripulse-pg-1 -c postgres -- \
  psql -U postgres -d agripulse -c \
  "SELECT pg_is_in_recovery(), now() AT TIME ZONE 'UTC' AS now_utc, pg_last_xact_replay_timestamp();"
```

`pg_is_in_recovery` must be `f`. Spot-check a few tables that should
contain the lost rows; compare row counts and the latest timestamps.

## 5. Swap the new cluster in

Once the restored cluster passes verification:

1. Scale all writers down to zero. `kubectl -n agripulse scale deploy --all --replicas=0`
2. Update the connection strings:
   - Read-write: `postgresql+asyncpg://agripulse@agripulse-pg-rw.pg-restore-2026-05-12.svc:5432/agripulse`
   - The `ExternalSecret` projecting the DB password is per-namespace;
     the new namespace will create its own from the same SM key. If you
     run permanently from the new namespace, update
     `infra/argocd/overlays/<env>/values.yaml` `env.DATABASE_URL` and
     reapply. Otherwise, prefer renaming via DNS (CNAME the old
     service name to the new cluster) so callers do not need a redeploy.
3. Scale writers back up. Verify `/health` on the API and watch error
   rates in Grafana for ten minutes before declaring the incident closed.

## 6. WAL archive falling behind

Symptom: Prometheus alert `CNPGWALArchiveStalled` fires (rule lives in
`infra/helm/shared/templates/prometheus-rules.yaml`); or the operator
pages because `pg_stat_archiver.archived_count` stops advancing.

1. Inspect operator status:
   `kubectl -n agripulse describe cluster agripulse-pg | grep -A2 WAL`
2. Force a WAL archive push:
   ```bash
   kubectl exec -n agripulse agripulse-pg-1 -c postgres -- \
     barman-cloud-wal-archive s3://agripulse-pg-backup-prod/pg agripulse-pg
   ```
3. Common causes:
   - IRSA role lost `s3:PutObject` on the backup bucket â€” re-check
     `terraform output agripulse_env_resources`.
   - S3 bucket lifecycle rule rolled an in-flight WAL segment to a tier
     that does not support overwrite. Should not happen with the
     `expire-backups-30d` rule, but worth confirming.
   - Disk-pressure on the primary blocking WAL flush. Check
     `kubectl top pod -n agripulse`.

## 7. Drill cadence

Run section 3-4 against the **staging** bucket once per quarter and
record the restore time, RPO (time of latest WAL replayed vs the wall
clock at start), and any deviations from this runbook. File the result
in `docs/decisions/` as an ADR if anything changed; otherwise update
this runbook in place.
