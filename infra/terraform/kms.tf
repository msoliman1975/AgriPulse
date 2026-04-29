resource "aws_kms_key" "missionagre" {
  description             = "MissionAgre ${var.environment} — at-rest encryption for S3, EKS secrets, RDS-style snapshots."
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(local.common_tags, {
    Name = "missionagre-${var.environment}"
  })
}

resource "aws_kms_alias" "missionagre" {
  name          = "alias/missionagre-${var.environment}"
  target_key_id = aws_kms_key.missionagre.key_id
}
