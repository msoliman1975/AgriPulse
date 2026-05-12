# IRSA role for the CloudNativePG operator-managed Postgres cluster. Allows
# barman-cloud (running inside the CNPG instance pods) to read/write the
# PITR backup bucket via instance profile credentials.

module "iam_role_cnpg" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "missionagre-${var.environment}-cnpg"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["missionagre:missionagre-pg"]
    }
  }

  role_policy_arns = {
    backup_rw = aws_iam_policy.s3_pg_backup_rw.arn
  }

  tags = local.common_tags
}
