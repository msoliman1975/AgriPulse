# Tempo trace storage — S3 bucket + IRSA for the observability:observability-tempo
# ServiceAccount.
#
# Tempo's helm chart at platform-values/tempo.yaml is configured with
# `storage.trace.backend = s3` pointing at the bucket below; without
# this bucket + role pair the tempo-0 StatefulSet CrashLoops on startup
# with `The specified bucket does not exist`.

resource "aws_s3_bucket" "tempo_traces" {
  bucket = "agripulse-tempo-traces"

  tags = merge(local.common_tags, {
    Name = "agripulse-tempo-traces"
  })
}

resource "aws_s3_bucket_public_access_block" "tempo_traces" {
  bucket = aws_s3_bucket.tempo_traces.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tempo_traces" {
  bucket = aws_s3_bucket.tempo_traces.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agripulse.arn
    }
    bucket_key_enabled = true
  }
}

# 30 days hot in the chart's `retention`, then S3 expires the underlying
# objects. Tempo's storage block index files are written once and read on
# query; nothing here needs versioning, so versioning stays disabled.
resource "aws_s3_bucket_lifecycle_configuration" "tempo_traces" {
  bucket = aws_s3_bucket.tempo_traces.id

  rule {
    id     = "expire-traces-30d"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "tempo_s3" {
  statement {
    sid    = "TempoReadWriteObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.tempo_traces.arn}/*"]
  }

  statement {
    sid    = "TempoListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.tempo_traces.arn]
  }

  statement {
    sid       = "TempoUseKMSKey"
    effect    = "Allow"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.agripulse.arn]
  }
}

resource "aws_iam_policy" "tempo_s3" {
  name        = "agripulse-${var.environment}-tempo-s3"
  description = "Read/write the agripulse-tempo-traces bucket from the observability-tempo ServiceAccount."
  policy      = data.aws_iam_policy_document.tempo_s3.json
}

module "iam_role_tempo" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-tempo"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["observability:observability-tempo"]
    }
  }

  role_policy_arns = {
    s3 = aws_iam_policy.tempo_s3.arn
  }

  tags = local.common_tags
}
