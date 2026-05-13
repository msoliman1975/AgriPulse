resource "aws_kms_key" "agripulse" {
  description             = "AgriPulse ${var.environment} â€” at-rest encryption for S3, EKS secrets, RDS-style snapshots."
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(local.common_tags, {
    Name = "agripulse-${var.environment}"
  })
}

resource "aws_kms_alias" "agripulse" {
  name          = "alias/agripulse-${var.environment}"
  target_key_id = aws_kms_key.agripulse.key_id
}
