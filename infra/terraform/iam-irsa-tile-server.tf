# IRSA role for the tile-server pod. Read-only access to the imagery COG bucket.

module "iam_role_tile_server" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "missionagre-${var.environment}-tile-server"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["missionagre:missionagre-tile-server"]
    }
  }

  role_policy_arns = {
    s3_imagery_ro = aws_iam_policy.s3_imagery_ro.arn
  }

  tags = local.common_tags
}
