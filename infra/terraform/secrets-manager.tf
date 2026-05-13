# CD-9 — AWS Secrets Manager placeholders.
#
# Terraform owns the resource (name, KMS, tags, IAM) but does NOT own the
# value. Each secret is created with a one-off placeholder; a human seeds
# the real value via `aws secretsmanager put-secret-value` (see
# docs/runbooks/seeding-secrets.md). `lifecycle.ignore_changes` keeps
# Terraform from clobbering the value on subsequent applies.
#
# Naming: `agripulse/<env>/<purpose>`. The `agripulse/` prefix is what
# the External Secrets IRSA role is scoped to (see `agripulse_external_secrets`
# below). The ClusterSecretStore in `infra/helm/shared/templates/cluster-secret-store.yaml`
# is shared across all envs; per-env access happens via the path itself.

locals {
  agripulse_secret_purposes = [
    "brevo-smtp-password",
    "keycloak-admin-password",
    # CD-13: per-env password for the `keycloak` CNPG role. CNPG reads
    # this via a k8s Secret synced by the keycloak chart's ExternalSecret;
    # Keycloak's externalDatabase block reads the same k8s Secret.
    "keycloak-db-password",
    "sentinel-hub-client-secret",
    "jwt-signing-key",
    "postgres-superuser-password",
  ]

  # Cartesian of env × purpose, flattened to a map with stable keys
  # (`<env>/<purpose>`) so `for_each` produces deterministic IDs.
  agripulse_secrets = {
    for pair in setproduct(var.environments, local.agripulse_secret_purposes) :
    "${pair[0]}/${pair[1]}" => {
      env     = pair[0]
      purpose = pair[1]
    }
  }
}

resource "aws_secretsmanager_secret" "agripulse" {
  for_each = local.agripulse_secrets

  name        = "agripulse/${each.value.env}/${each.value.purpose}"
  description = "Placeholder owned by Terraform. Value seeded out-of-band per docs/runbooks/seeding-secrets.md."
  kms_key_id  = aws_kms_key.missionagre.arn

  tags = merge(local.common_tags, {
    Env     = each.value.env
    Purpose = each.value.purpose
  })
}

# Sentinel placeholder so the secret exists in a "created" state and the
# ExternalSecret controller does not log NotFound until a human seeds it.
# The actual value is set by `aws secretsmanager put-secret-value` and
# Terraform never touches it again because of `ignore_changes`.
resource "aws_secretsmanager_secret_version" "agripulse_placeholder" {
  for_each = aws_secretsmanager_secret.agripulse

  secret_id     = each.value.id
  secret_string = "PLACEHOLDER_SEED_ME"

  lifecycle {
    ignore_changes = [secret_string, version_stages]
  }
}

# Read-only access scoped to the agripulse/ prefix only. Distinct from the
# legacy `missionagre/*` policy in iam.tf — both attach to the same
# external-secrets IRSA role so the migration can land incrementally.
resource "aws_iam_policy" "agripulse_secrets_read" {
  name        = "agripulse-${var.environment}-secrets-read"
  description = "Read access to the agripulse/* prefix in AWS Secrets Manager."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:agripulse/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "external_secrets_agripulse" {
  role       = module.iam_role_external_secrets.iam_role_name
  policy_arn = aws_iam_policy.agripulse_secrets_read.arn
}
