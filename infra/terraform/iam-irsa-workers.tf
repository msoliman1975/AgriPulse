# IRSA role for the Celery worker pods. Mirrors the API role since workers
# share the same image and the same S3 + Secrets Manager surface.

module "iam_role_workers" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "missionagre-${var.environment}-workers"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["missionagre:missionagre-workers"]
    }
  }

  role_policy_arns = {
    s3_imagery_rw = aws_iam_policy.s3_imagery_rw.arn
    s3_exports_rw = aws_iam_policy.s3_exports_rw.arn
    secrets_read  = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}
