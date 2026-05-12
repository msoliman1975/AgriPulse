# IRSA role for the backend API pod. Read/write access to imagery + exports
# S3 buckets and read access to AWS Secrets Manager.

module "iam_role_api" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "missionagre-${var.environment}-api"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["missionagre:missionagre-api"]
    }
  }

  role_policy_arns = {
    s3_imagery_rw = aws_iam_policy.s3_imagery_rw.arn
    s3_exports_rw = aws_iam_policy.s3_exports_rw.arn
    secrets_read  = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}
