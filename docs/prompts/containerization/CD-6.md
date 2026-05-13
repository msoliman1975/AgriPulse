# CD-6 â€” S3 buckets + IRSA for imagery and Postgres backups

[Shared preamble â€” see README.md]

## Goal
Provision the application-level S3 buckets in Terraform, with KMS encryption, lifecycle rules, and IRSA bindings so the api ServiceAccount can read/write imagery and the CNPG ServiceAccount can read/write Postgres backups. Replaces MinIO outside dev.

## Files to change
- `infra/terraform/s3.tf` â€” extend. Buckets per env:
  - `agripulse-imagery-{dev,staging,prod}`
  - `agripulse-pg-backup-{dev,staging,prod}`
- `infra/terraform/iam-irsa.tf` (or `iam.tf`) â€” new IRSA roles:
  - `agripulse-api-irsa-{env}` with imagery bucket RW.
  - `agripulse-cnpg-irsa-{env}` with backup bucket RW.
- `infra/terraform/outputs.tf` â€” output role ARNs.
- `infra/helm/api/values.yaml` â€” `serviceAccount.annotations` block referencing the api IRSA ARN (per-env override).
- `infra/helm/shared/values.yaml` â€” `postgresCluster.serviceAccountAnnotations` for the CNPG-managed SA.
- `infra/argocd/overlays/{dev,staging,production}/values.yaml` â€” set the role ARN per env.
- `backend/app/shared/storage/s3.py` (if it exists; otherwise the boto3 client wherever it's configured) â€” confirm it uses default credential chain (no static keys). Don't add new code â€” verify.

## Tasks
1. S3 buckets: versioning enabled, KMS-encrypted with the existing `aws_kms_key.agripulse`, public access blocked (all four flags), lifecycle rule transitioning `noncurrent_version` objects to STANDARD_IA after 30 days and DEEP_ARCHIVE after 90 (imagery), or expiring backups after 30 days (Postgres backup buckets â€” matches PITR window from CD-7).
2. IRSA roles: trust policy targets the EKS OIDC provider for the `<env>` namespace ServiceAccounts (`api` and `cnpg-cluster-<name>`). Policy scoped to one bucket each.
3. Bucket naming uses `for_each` over `var.environments = ["dev", "staging", "prod"]`. Don't duplicate resources.
4. Output map of `{ env => { imagery_bucket, backup_bucket, api_irsa_arn, cnpg_irsa_arn } }` so overlays can fetch the right values.
5. Helm: add `serviceAccount.annotations.eks\.amazonaws\.com/role-arn` template (escape the dots in Helm).
6. **Critical**: the CNPG IRSA role ARN must be referenced by the CNPG `Cluster.spec.serviceAccountTemplate.metadata.annotations` â€” but the `Cluster` CR is currently in `infra/helm/shared/templates/postgres-cluster.yaml` and doesn't have a SA template block yet. Don't add it in this PR â€” leave that to CD-7. Just output the ARN.

## Out of scope
- Don't wire CNPG backups in this PR (CD-7 does that).
- Don't migrate dev away from MinIO. Dev still uses MinIO in `infra/dev/compose.yaml`. EKS-dev should point at the real S3 bucket â€” that's the difference.
- Don't add CloudFront / CDN in front of the imagery bucket.

## Definition of done
- `terraform plan` shows 3 imagery buckets, 3 backup buckets, 6 IRSA roles, 6 outputs.
- Apply succeeds.
- A debug pod with the api ServiceAccount can `aws s3 ls s3://agripulse-imagery-dev/` (no creds, just IRSA).
- PR description includes the IRSA verification command.
