# IRSA roles for the in-cluster service accounts that need AWS access.
#
#   * api / workers â€” read/write S3 imagery + exports buckets, fetch
#     AWS Secrets Manager values via IRSA.
#   * tile-server â€” read-only access to the imagery COG bucket.
#   * external-secrets â€” read access to AWS Secrets Manager.
#   * cloudnativepg â€” read/write S3 backup bucket for PITR.
#
# These roles assume the cluster's OIDC provider; the EKS module emits
# `module.eks.oidc_provider_arn` we rely on below.

data "aws_caller_identity" "current" {}

# --- Backend API ----------------------------------------------------------
module "iam_role_api" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-api"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["agripulse:agripulse-api"]
    }
  }

  role_policy_arns = {
    s3_imagery_rw = aws_iam_policy.s3_imagery_rw.arn
    s3_exports_rw = aws_iam_policy.s3_exports_rw.arn
    secrets_read  = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}

# --- Workers --------------------------------------------------------------
module "iam_role_workers" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-workers"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["agripulse:agripulse-workers"]
    }
  }

  role_policy_arns = {
    s3_imagery_rw = aws_iam_policy.s3_imagery_rw.arn
    s3_exports_rw = aws_iam_policy.s3_exports_rw.arn
    secrets_read  = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}

# --- Tile server (read-only) ---------------------------------------------
module "iam_role_tile_server" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-tile-server"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["agripulse:agripulse-tile-server"]
    }
  }

  role_policy_arns = {
    s3_imagery_ro = aws_iam_policy.s3_imagery_ro.arn
  }

  tags = local.common_tags
}

# --- External Secrets Operator -------------------------------------------
module "iam_role_external_secrets" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-external-secrets"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-secrets:external-secrets"]
    }
  }

  role_policy_arns = {
    secrets_read = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}

# --- CloudNativePG backup ------------------------------------------------
module "iam_role_cnpg" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-cnpg"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["agripulse:agripulse-pg"]
    }
  }

  role_policy_arns = {
    backup_rw = aws_iam_policy.s3_pg_backup_rw.arn
  }

  tags = local.common_tags
}

# --- Policies -------------------------------------------------------------
resource "aws_iam_policy" "s3_imagery_rw" {
  name        = "agripulse-${var.environment}-s3-imagery-rw"
  description = "Read/write the imagery raw + COG buckets."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts",
      ]
      Resource = [
        "${aws_s3_bucket.this["imagery_raw"].arn}/*",
        "${aws_s3_bucket.this["imagery_cogs"].arn}/*",
      ]
      }, {
      Effect = "Allow"
      Action = [
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
      ]
      Resource = [
        aws_s3_bucket.this["imagery_raw"].arn,
        aws_s3_bucket.this["imagery_cogs"].arn,
      ]
    }]
  })
}

resource "aws_iam_policy" "s3_imagery_ro" {
  name        = "agripulse-${var.environment}-s3-imagery-ro"
  description = "Read-only access to the imagery COG bucket (tile-server)."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.this["imagery_cogs"].arn, "${aws_s3_bucket.this["imagery_cogs"].arn}/*"]
    }]
  })
}

resource "aws_iam_policy" "s3_exports_rw" {
  name        = "agripulse-${var.environment}-s3-exports-rw"
  description = "Read/write access to the exports bucket."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = ["${aws_s3_bucket.this["exports"].arn}/*"]
      }, {
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = [aws_s3_bucket.this["exports"].arn]
    }]
  })
}

resource "aws_iam_policy" "s3_pg_backup_rw" {
  name        = "agripulse-${var.environment}-s3-pg-backup-rw"
  description = "Read/write access to the Postgres PITR backup bucket. Bucket itself is provisioned outside this stack (CNPG defaults)."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
      ]
      Resource = [
        "arn:aws:s3:::agripulse-pg-backups-${var.environment}",
        "arn:aws:s3:::agripulse-pg-backups-${var.environment}/*",
      ]
    }]
  })
}

resource "aws_iam_policy" "secrets_read" {
  name        = "agripulse-${var.environment}-secrets-read"
  description = "Read access to the agripulse/* prefix in AWS Secrets Manager."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = [
        "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:agripulse/*",
      ]
    }]
  })
}
