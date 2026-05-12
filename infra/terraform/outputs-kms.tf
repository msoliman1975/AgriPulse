output "kms_key_arn" {
  description = "Customer-managed KMS key for at-rest encryption."
  value       = aws_kms_key.missionagre.arn
}
