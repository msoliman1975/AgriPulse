output "vpc_id" {
  description = "ID of the VPC."
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ)."
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnet IDs (one per AZ)."
  value       = module.vpc.public_subnets
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_oidc_issuer_url" {
  description = "OIDC provider URL for the cluster (used by IRSA)."
  value       = module.eks.cluster_oidc_issuer_url
}

output "kms_key_arn" {
  description = "Customer-managed KMS key for at-rest encryption."
  value       = aws_kms_key.missionagre.arn
}

output "s3_buckets" {
  description = "Bucket names by logical role."
  value = {
    imagery_raw  = aws_s3_bucket.this["imagery_raw"].bucket
    imagery_cogs = aws_s3_bucket.this["imagery_cogs"].bucket
    exports      = aws_s3_bucket.this["exports"].bucket
  }
}

output "iam_role_arns" {
  description = "IRSA role ARNs by service."
  value = {
    api              = module.iam_role_api.iam_role_arn
    workers          = module.iam_role_workers.iam_role_arn
    tile_server      = module.iam_role_tile_server.iam_role_arn
    external_secrets = module.iam_role_external_secrets.iam_role_arn
    cnpg             = module.iam_role_cnpg.iam_role_arn
  }
}
