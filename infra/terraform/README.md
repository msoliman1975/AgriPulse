# MissionAgre — Terraform

Bootstraps the AWS substrate that hosts MissionAgre per ARCHITECTURE.md
§ 3.2: VPC + subnets, EKS cluster, KMS key, S3 buckets, and the IRSA roles
ArgoCD-installed workloads assume.

## What lives here vs. ArgoCD

This module owns the **immutable substrate** — anything that is expensive
to recreate or that ArgoCD cannot manage (the cluster itself, the network,
S3 buckets, IAM roles). Operators and applications go through ArgoCD
(`infra/argocd/appsets/`). The split is sharp on purpose: a `terraform
destroy` should not take cert-manager with it.

## Layout

```
versions.tf      Required Terraform + provider versions, S3 backend stub.
providers.tf     AWS provider with default tags.
variables.tf     User-facing inputs (region, env, sizing).
locals.tf        Computed values: subnet CIDRs, AZs, common tags.
vpc.tf           terraform-aws-modules/vpc/aws.
eks.tf           terraform-aws-modules/eks/aws.
kms.tf           Customer-managed KMS key for at-rest encryption.
s3.tf            imagery-raw, imagery-cogs, exports buckets.
iam.tf           Five IRSA roles for the workloads in infra/helm/.
outputs.tf       VPC ID, EKS endpoint, role ARNs.
```

## State backend

State lives in a per-account S3 bucket with a DynamoDB lock table. The
backend block in `versions.tf` is intentionally empty — `terraform init`
gets the values via `-backend-config`:

```bash
terraform init \
  -backend-config="bucket=missionagre-tfstate-<account-id>" \
  -backend-config="key=<env>/terraform.tfstate" \
  -backend-config="region=me-south-1" \
  -backend-config="encrypt=true" \
  -backend-config="dynamodb_table=missionagre-tfstate-lock"
```

The bucket and table are created once per account by the bootstrap
runbook in `docs/runbooks/bootstrap-aws-account.md` (Prompt 6).

## CI

The `infra-tf` job in `.github/workflows/ci.yml` runs `terraform fmt
-check -recursive` and `terraform init -backend=false && terraform
validate` on every push/PR. No `plan` or `apply` in CI — those happen
manually with the runbook.

## Local

```bash
cd infra/terraform
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```
