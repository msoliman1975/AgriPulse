# IRSA role for the External Secrets Operator controller. Read access to the
# missionagre/* prefix in AWS Secrets Manager so it can sync ClusterSecretStore
# values into in-cluster Kubernetes Secrets.

module "iam_role_external_secrets" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "missionagre-${var.environment}-external-secrets"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-secrets:external-secrets"]
    }
  }

  role_policy_arns = {
    secrets_read = aws_iam_policy.secrets_read.arn
  }

  tags = local.common_tags
}
