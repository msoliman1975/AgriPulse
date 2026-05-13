# CD-7 — CNPG Cluster backup wiring + 30-day PITR + ScheduledBackup

[Shared preamble — see README.md]

## Goal
Turn the CNPG `Cluster` resource into a production-shaped Postgres with continuous WAL archive and 30-day point-in-time recovery, backed by the S3 bucket from CD-6. The existing template at `infra/helm/shared/templates/postgres-cluster.yaml` **already has a `backup:` block** with `s3Credentials.inheritFromIAMRole` — this PR enables it, wires the IRSA ServiceAccount annotation, adds a `ScheduledBackup`, and writes the restore runbook.

## Files to change
- `infra/helm/shared/templates/postgres-cluster.yaml` — add `serviceAccountTemplate.metadata.annotations` so CNPG creates its SA with the IRSA role ARN from CD-6.
- `infra/helm/shared/templates/scheduled-backup.yaml` — new. CNPG `ScheduledBackup` CR.
- `infra/helm/shared/values.yaml` — flip `postgresCluster.backup.enabled: true`, set `destinationPath` template `s3://agripulse-pg-backup-{{ .Values.global.env }}/pg`, set retention `30d`, add `serviceAccountAnnotations.eks\.amazonaws\.com/role-arn` (pulled from CD-6 output via the overlay).
- `infra/argocd/overlays/{dev,staging,production}/values.yaml` — set `global.env` and the CNPG IRSA role ARN.
- `docs/runbooks/postgres-restore.md` — new, ~80 lines.

## Tasks
1. `Cluster.spec.serviceAccountTemplate.metadata.annotations` — `eks.amazonaws.com/role-arn: <from-values>`. Without this the CNPG-created pods can't write to S3.
2. `ScheduledBackup`:
   - `schedule: "0 0 2 * * *"` (CNPG uses 6-field cron with seconds — daily at 02:00 UTC).
   - `backupOwnerReference: self`.
   - `cluster.name: <cluster-name>`.
3. `Cluster.spec.backup.retentionPolicy: "30d"` (this is Barman's retention syntax).
4. WAL: `wal.compression: gzip`, `wal.maxParallel: 4`. Already in template; confirm values.
5. Don't touch `Cluster.spec.bootstrap` — new envs continue to use `initdb`. Restore is via a **new** `Cluster` resource with `bootstrap.recovery.recoveryTarget.targetTime: <ISO timestamp>` (documented in runbook, not encoded in chart).
6. Runbook (`docs/runbooks/postgres-restore.md`) covers:
   - How to list available backups: `kubectl exec -n <ns> postgres-cluster-1 -- barman-cloud-backup-list s3://agripulse-pg-backup-prod/pg postgres-cluster`.
   - How to verify a backup is valid (Barman `check`).
   - How to restore to a new namespace at a specific recovery target time — full YAML example.
   - How to swap the new cluster in (update connection strings via External Secret or ConfigMap).
   - What to do if WAL archive falls behind (Prometheus alert + manual `barman-cloud-wal-archive`).
   - Tested-restore drill cadence (quarterly).

## Out of scope
- Don't enable cross-region backup replication.
- Don't add backup encryption beyond what S3 + KMS already provide.
- Don't enable `Cluster.spec.replica.enabled` (replica cluster) — that's a separate decision.

## Definition of done
- `helm template shared infra/helm/shared --set postgresCluster.backup.enabled=true --set global.env=dev` renders the `Cluster` with the SA annotation, the `backup:` block populated, and a `ScheduledBackup` resource.
- After ArgoCD sync in dev, `kubectl logs -n <ns> postgres-cluster-1 -c postgres | grep "barman-cloud-wal-archive"` shows successful WAL pushes.
- Manual test: trigger a `Backup` CR, see it succeed in <2 min for an empty DB.
- Runbook reviewed and committed.
