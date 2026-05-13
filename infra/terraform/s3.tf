# Three buckets per env. Imagery raw + COGs are bucket-versioned with a
# lifecycle that moves objects past 90 days to S3 Glacier Instant Retrieval
# (ARCHITECTURE.md Â§ 9). Exports is shorter-lived (30 days then expire).

locals {
  buckets = {
    imagery_raw  = "agripulse-imagery-raw-${var.environment}"
    imagery_cogs = "agripulse-imagery-cogs-${var.environment}"
    exports      = "agripulse-exports-${var.environment}"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket = each.value

  tags = merge(local.common_tags, {
    Name = each.value
  })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agripulse.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "imagery" {
  for_each = {
    for k, v in aws_s3_bucket.this :
    k => v
    if startswith(k, "imagery_")
  }

  bucket = each.value.id

  rule {
    id     = "tier-to-glacier-after-90-days"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.this["exports"].id

  rule {
    id     = "expire-exports-after-30-days"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ---------------------------------------------------------------------------
# CD-6 â€” agripulse-{imagery,pg-backup}-{env} buckets.
#
# Replaces MinIO outside dev. Imagery buckets retain noncurrent versions
# (STANDARD_IA at 30d, DEEP_ARCHIVE at 90d). Backup buckets hard-expire at
# 30 days matching the PITR window from CD-7.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "agripulse_imagery" {
  for_each = toset(var.environments)

  bucket = "agripulse-imagery-${each.value}"

  tags = merge(local.common_tags, {
    Name = "agripulse-imagery-${each.value}"
    Env  = each.value
  })
}

resource "aws_s3_bucket_public_access_block" "agripulse_imagery" {
  for_each = aws_s3_bucket.agripulse_imagery

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "agripulse_imagery" {
  for_each = aws_s3_bucket.agripulse_imagery

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agripulse_imagery" {
  for_each = aws_s3_bucket.agripulse_imagery

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agripulse.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agripulse_imagery" {
  for_each = aws_s3_bucket.agripulse_imagery

  bucket = each.value.id

  rule {
    id     = "tier-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_transition {
      noncurrent_days = 90
      storage_class   = "DEEP_ARCHIVE"
    }
  }
}

resource "aws_s3_bucket" "agripulse_pg_backup" {
  for_each = toset(var.environments)

  bucket = "agripulse-pg-backup-${each.value}"

  tags = merge(local.common_tags, {
    Name = "agripulse-pg-backup-${each.value}"
    Env  = each.value
  })
}

resource "aws_s3_bucket_public_access_block" "agripulse_pg_backup" {
  for_each = aws_s3_bucket.agripulse_pg_backup

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "agripulse_pg_backup" {
  for_each = aws_s3_bucket.agripulse_pg_backup

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agripulse_pg_backup" {
  for_each = aws_s3_bucket.agripulse_pg_backup

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agripulse.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agripulse_pg_backup" {
  for_each = aws_s3_bucket.agripulse_pg_backup

  bucket = each.value.id

  rule {
    id     = "expire-backups-30d"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}
