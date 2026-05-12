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
    external_dns     = module.iam_role_external_dns.iam_role_arn
    cert_manager     = module.iam_role_cert_manager.iam_role_arn
  }
}

output "route53_zone_id" {
  description = "ID of the public Route 53 hosted zone for agripulse.cloud."
  value       = local.route53_zone_id
}

output "route53_zone_name" {
  description = "Name of the public Route 53 hosted zone."
  value       = local.route53_zone_name
}

output "route53_nameservers" {
  description = "Authoritative AWS nameservers for the hosted zone. Paste these into the domain registrar on first apply."
  value       = local.route53_nameservers
}

output "acm_wildcard_certificate_arn" {
  description = "ARN of the wildcard certificate covering agripulse.cloud (+ dev/staging subzones)."
  value       = aws_acm_certificate.wildcard.arn
}

output "github_oidc_role_arns" {
  description = "Role ARNs that GitHub Actions assumes via OIDC. Wire these into .github/workflows/* `aws-actions/configure-aws-credentials` calls."
  value = {
    plan  = aws_iam_role.gha_plan.arn
    apply = aws_iam_role.gha_apply.arn
  }
}

output "karpenter" {
  description = "Karpenter wiring: IRSA role ARN, node IAM role name, SQS interruption queue, instance profile."
  value = {
    iam_role_arn          = module.karpenter.iam_role_arn
    node_iam_role_name    = module.karpenter.node_iam_role_name
    node_iam_role_arn     = module.karpenter.node_iam_role_arn
    queue_name            = module.karpenter.queue_name
    instance_profile_name = module.karpenter.instance_profile_name
  }
}

output "agripulse_env_resources" {
  description = "Per-env imagery + pg-backup bucket names and IRSA role ARNs. Overlays read this to wire the api + CNPG ServiceAccount annotations."
  value = {
    for env in var.environments :
    env => {
      imagery_bucket = aws_s3_bucket.agripulse_imagery[env].bucket
      backup_bucket  = aws_s3_bucket.agripulse_pg_backup[env].bucket
      api_irsa_arn   = module.iam_role_agripulse_api[env].iam_role_arn
      cnpg_irsa_arn  = module.iam_role_agripulse_cnpg[env].iam_role_arn
    }
  }
}
