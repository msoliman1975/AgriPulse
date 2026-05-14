# CD-11 â€” GitHub OIDC federation for CI.
#
# Two scoped roles:
#   * gha-terraform-plan  â€” read-only on services + RW on the TF state
#     lock. Assumed by PR runs (`pull_request` events).
#   * gha-terraform-apply â€” write on the resource types this stack
#     manages. Assumed only by `push` to `refs/heads/main` and gated
#     behind a manual GitHub environment approval (production-infra).
#
# Trust policies are GitHub-OIDC and restrict the assumable subject so a
# branch named "main-but-not-really" can't impersonate the apply role.

variable "github_org" {
  description = "GitHub org/user that owns the repo (subject prefix in OIDC claims)."
  type        = string
  default     = "msoliman1975"
}

variable "github_repo" {
  description = "GitHub repository name (without org)."
  type        = string
  default     = "AgriPulse"
}

variable "tf_state_bucket" {
  description = "S3 bucket holding the Terraform state. Used in the plan role's state-RW scope."
  type        = string
}

variable "tf_lock_table" {
  description = "DynamoDB lock table name. The plan + apply roles both need RW on this so terraform init/plan can acquire the lock."
  type        = string
  default     = "agripulse-tfstate-lock"
}

# --- OIDC provider -------------------------------------------------------
# Thumbprint pinned to GitHub's current root. Refresh quarterly via
# `openssl s_client -showcerts -servername token.actions.githubusercontent.com
#  -connect token.actions.githubusercontent.com:443 </dev/null`.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = local.common_tags
}

locals {
  github_oidc_arn  = aws_iam_openid_connect_provider.github.arn
  github_repo_full = "${var.github_org}/${var.github_repo}"
}

# --- Plan role (PRs) -----------------------------------------------------
data "aws_iam_policy_document" "gha_plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_repo_full}:pull_request"]
    }
  }
}

data "aws_iam_policy_document" "gha_plan_policy" {
  # Read-everything is granted via the AWS-managed ReadOnlyAccess policy
  # attached separately (see aws_iam_role_policy_attachment.gha_plan_readonly
  # below). IAM rejects wildcards in the service vendor ("*:Get*") so we
  # cannot express read-everything inline.

  statement {
    sid    = "TerraformStateRW"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::${var.tf_state_bucket}",
      "arn:aws:s3:::${var.tf_state_bucket}/*",
    ]
  }

  statement {
    sid    = "TerraformLockRW"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
    ]
    resources = ["arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/${var.tf_lock_table}"]
  }
}

resource "aws_iam_role" "gha_plan" {
  name               = "gha-terraform-plan"
  description        = "Read-only role assumed by GitHub Actions PR runs for terraform plan."
  assume_role_policy = data.aws_iam_policy_document.gha_plan_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "gha_plan" {
  name   = "gha-terraform-plan"
  role   = aws_iam_role.gha_plan.id
  policy = data.aws_iam_policy_document.gha_plan_policy.json
}

resource "aws_iam_role_policy_attachment" "gha_plan_readonly" {
  role       = aws_iam_role.gha_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# --- Apply role (push to main + environment approval) -------------------
data "aws_iam_policy_document" "gha_apply_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_repo_full}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "gha_apply_policy" {
  # Scoped to services Terraform manages. Intentionally NOT *:*.
  statement {
    sid    = "EksWrite"
    effect = "Allow"
    actions = [
      "eks:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "VpcWrite"
    effect = "Allow"
    actions = [
      "ec2:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "IamWrite"
    effect = "Allow"
    actions = [
      "iam:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "KmsWrite"
    effect = "Allow"
    actions = [
      "kms:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3Write"
    effect = "Allow"
    actions = [
      "s3:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "Route53Write"
    effect = "Allow"
    actions = [
      "route53:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AcmWrite"
    effect = "Allow"
    actions = [
      "acm:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "SecretsManagerWrite"
    effect = "Allow"
    actions = [
      "secretsmanager:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "EventsWrite"
    effect = "Allow"
    actions = [
      "events:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "SqsWrite"
    effect = "Allow"
    actions = [
      "sqs:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "TerraformStateRW"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::${var.tf_state_bucket}",
      "arn:aws:s3:::${var.tf_state_bucket}/*",
    ]
  }

  statement {
    sid    = "TerraformLockRW"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
    ]
    resources = ["arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/${var.tf_lock_table}"]
  }
}

resource "aws_iam_role" "gha_apply" {
  name               = "gha-terraform-apply"
  description        = "Write role assumed by GitHub Actions push-to-main runs for terraform apply. Gated by environment approval."
  assume_role_policy = data.aws_iam_policy_document.gha_apply_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "gha_apply" {
  name   = "gha-terraform-apply"
  role   = aws_iam_role.gha_apply.id
  policy = data.aws_iam_policy_document.gha_apply_policy.json
}
