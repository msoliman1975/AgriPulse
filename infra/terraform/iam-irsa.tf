# IRSA roles that exist outside the app-namespace IRSA bindings in iam.tf.
#
# Today this file holds:
#   * external-dns (Route 53 RW on the agripulse.cloud zone)
#   * cert-manager (Route 53 TXT RW on the same zone â€” DNS-01 solver)
#   * api / cnpg IRSA bindings keyed by deploy env, used by the
#     EKS-dev/staging/prod target namespaces.
#
# Keep app-specific (`api`, `workers`, `tile-server`) bindings in iam.tf so
# the diff stays readable when we eventually fold those into this file.

# --- EBS CSI driver ------------------------------------------------------
# IRSA role for the aws-ebs-csi-driver addon's controller ServiceAccount.
# EKS module v20+ no longer auto-creates this; without it the controller
# pods can't call EC2 to create/attach volumes and the addon hangs in
# CREATING until the 20-min Terraform timeout fires.
module "iam_role_ebs_csi" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name             = "agripulse-${var.environment}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.common_tags
}

# --- ExternalDNS ---------------------------------------------------------
data "aws_iam_policy_document" "external_dns" {
  statement {
    sid    = "Route53ChangeRecords"
    effect = "Allow"
    actions = [
      "route53:ChangeResourceRecordSets",
    ]
    resources = [local.route53_zone_arn]
  }

  statement {
    sid    = "Route53ReadZones"
    effect = "Allow"
    actions = [
      "route53:ListHostedZones",
      "route53:ListResourceRecordSets",
      "route53:ListTagsForResource",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "external_dns" {
  name        = "agripulse-${var.environment}-external-dns"
  description = "Allow ExternalDNS to manage records inside the agripulse.cloud hosted zone."
  policy      = data.aws_iam_policy_document.external_dns.json
}

module "iam_role_external_dns" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-external-dns"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["external-dns:external-dns"]
    }
  }

  role_policy_arns = {
    route53 = aws_iam_policy.external_dns.arn
  }

  tags = local.common_tags
}

# --- cert-manager DNS-01 solver -----------------------------------------
data "aws_iam_policy_document" "cert_manager_dns01" {
  statement {
    sid    = "Route53GetChange"
    effect = "Allow"
    actions = [
      "route53:GetChange",
    ]
    resources = ["arn:aws:route53:::change/*"]
  }

  statement {
    sid    = "Route53ChangeTxtRecords"
    effect = "Allow"
    actions = [
      "route53:ChangeResourceRecordSets",
      "route53:ListResourceRecordSets",
    ]
    resources = [local.route53_zone_arn]
  }

  statement {
    sid       = "Route53ListZones"
    effect    = "Allow"
    actions   = ["route53:ListHostedZonesByName"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "cert_manager_dns01" {
  name        = "agripulse-${var.environment}-cert-manager-dns01"
  description = "Allow cert-manager DNS-01 solver to manage TXT records under the agripulse.cloud zone."
  policy      = data.aws_iam_policy_document.cert_manager_dns01.json
}

module "iam_role_cert_manager" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-${var.environment}-cert-manager"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["cert-manager:cert-manager"]
    }
  }

  role_policy_arns = {
    dns01 = aws_iam_policy.cert_manager_dns01.arn
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# CD-6 â€” per-env agripulse IRSA roles.
#
# Bound to ServiceAccounts in the per-env Kubernetes namespaces (`dev`,
# `staging`, `prod`). The trust policy lets only those SAs assume the role
# via the cluster's OIDC provider.
# ---------------------------------------------------------------------------

resource "aws_iam_policy" "agripulse_api" {
  for_each = toset(var.environments)

  name        = "agripulse-api-irsa-${each.value}"
  description = "Read/write the agripulse-imagery-${each.value} bucket from the api ServiceAccount."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = ["${aws_s3_bucket.agripulse_imagery[each.value].arn}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:GetBucketLocation",
        ]
        Resource = [aws_s3_bucket.agripulse_imagery[each.value].arn]
      },
    ]
  })
}

module "iam_role_agripulse_api" {
  for_each = toset(var.environments)

  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-api-irsa-${each.value}"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["${each.value}:agripulse-api"]
    }
  }

  role_policy_arns = {
    imagery = aws_iam_policy.agripulse_api[each.value].arn
  }

  tags = merge(local.common_tags, {
    Env = each.value
  })
}

resource "aws_iam_policy" "agripulse_cnpg" {
  for_each = toset(var.environments)

  name        = "agripulse-cnpg-irsa-${each.value}"
  description = "Read/write the agripulse-pg-backup-${each.value} bucket from the CNPG-managed ServiceAccount."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = ["${aws_s3_bucket.agripulse_pg_backup[each.value].arn}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:GetBucketLocation",
        ]
        Resource = [aws_s3_bucket.agripulse_pg_backup[each.value].arn]
      },
    ]
  })
}

module "iam_role_agripulse_cnpg" {
  for_each = toset(var.environments)

  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.50"

  role_name = "agripulse-cnpg-irsa-${each.value}"

  oidc_providers = {
    main = {
      provider_arn = module.eks.oidc_provider_arn
      # CNPG names its SA after the Cluster CR; the shared chart pins this
      # to `agripulse-pg`. CD-7 will switch the Cluster CR to use this
      # SA template; that PR will line the names up if they ever diverge.
      namespace_service_accounts = ["${each.value}:agripulse-pg"]
    }
  }

  role_policy_arns = {
    backup = aws_iam_policy.agripulse_cnpg[each.value].arn
  }

  tags = merge(local.common_tags, {
    Env = each.value
  })
}
