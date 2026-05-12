# IAM policies consumed by the in-cluster IRSA roles. The role modules
# themselves live in iam-irsa-<concern>.tf — one file per concern so that
# CD-N PRs adding new IRSA roles don't collide with each other on this
# file. Policies stay here because they're plain IAM policies that any
# role can attach to.

data "aws_caller_identity" "current" {}

# --- Policies -------------------------------------------------------------
resource "aws_iam_policy" "s3_imagery_rw" {
  name        = "missionagre-${var.environment}-s3-imagery-rw"
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
  name        = "missionagre-${var.environment}-s3-imagery-ro"
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
  name        = "missionagre-${var.environment}-s3-exports-rw"
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
  name        = "missionagre-${var.environment}-s3-pg-backup-rw"
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
        "arn:aws:s3:::missionagre-pg-backups-${var.environment}",
        "arn:aws:s3:::missionagre-pg-backups-${var.environment}/*",
      ]
    }]
  })
}

resource "aws_iam_policy" "secrets_read" {
  name        = "missionagre-${var.environment}-secrets-read"
  description = "Read access to the missionagre/* prefix in AWS Secrets Manager."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
      ]
      Resource = [
        "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:missionagre/*",
      ]
    }]
  })
}
