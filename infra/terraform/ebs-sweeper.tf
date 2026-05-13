# CD-15 — EBS sweeper.
#
# CNPG and Karpenter both leave detached EBS volumes around when they
# fail in particular ways (pod evicted mid-WAL-archive; node scaled in
# before the StatefulSet PVC release reconciled). Over a few weeks
# these add up. The sweeper runs daily, snapshots anything `available`
# (i.e. unattached) and older than 7 days, then deletes it.
#
# Dry-run mode (env var SWEEPER_DRY_RUN=true) is the default for the
# first week of operation — read the CloudWatch logs to verify it's only
# targeting volumes you actually want it to delete, then flip the var.

variable "ebs_sweeper_dry_run" {
  description = "If true (default), the sweeper logs what it would do and skips the snapshot+delete. Flip to false after a week of observation."
  type        = bool
  default     = true
}

variable "ebs_sweeper_age_days" {
  description = "Minimum age of an `available` volume before the sweeper touches it. Karpenter normally reclaims within hours; 7d is far past that."
  type        = number
  default     = 7
}

data "aws_iam_policy_document" "ebs_sweeper_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_sweeper" {
  name               = "missionagre-${var.environment}-ebs-sweeper"
  assume_role_policy = data.aws_iam_policy_document.ebs_sweeper_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ebs_sweeper_basic" {
  role       = aws_iam_role.ebs_sweeper.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "ebs_sweeper" {
  name        = "missionagre-${var.environment}-ebs-sweeper"
  description = "CD-15: read EBS volumes, snapshot + delete unattached + old."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots",
          "ec2:DescribeTags",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateSnapshot",
          "ec2:CreateTags",
          "ec2:DeleteVolume",
        ]
        Resource = "*"
        # Scoping by tag would prevent cleaning up untagged orphans —
        # exactly the case the sweeper exists to handle.
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_sweeper" {
  role       = aws_iam_role.ebs_sweeper.name
  policy_arn = aws_iam_policy.ebs_sweeper.arn
}

data "archive_file" "ebs_sweeper" {
  type        = "zip"
  source_dir  = "${path.module}/ebs-sweeper-lambda"
  output_path = "${path.module}/.terraform-build/ebs-sweeper.zip"
}

resource "aws_lambda_function" "ebs_sweeper" {
  function_name    = "missionagre-${var.environment}-ebs-sweeper"
  description      = "CD-15: snapshot+delete unattached EBS volumes older than threshold."
  role             = aws_iam_role.ebs_sweeper.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.ebs_sweeper.output_path
  source_code_hash = data.archive_file.ebs_sweeper.output_base64sha256
  timeout          = 300
  memory_size      = 256

  environment {
    variables = {
      DRY_RUN  = var.ebs_sweeper_dry_run ? "true" : "false"
      AGE_DAYS = tostring(var.ebs_sweeper_age_days)
      REGION   = var.region
    }
  }

  tags = local.common_tags
}

# Daily at 03:00 UTC — quiet hour for me-south-1 + Karpenter consolidation.
resource "aws_cloudwatch_event_rule" "ebs_sweeper_daily" {
  name                = "missionagre-${var.environment}-ebs-sweeper-daily"
  description         = "CD-15: trigger the EBS sweeper Lambda daily."
  schedule_expression = "cron(0 3 * * ? *)"
  tags                = local.common_tags
}

resource "aws_cloudwatch_event_target" "ebs_sweeper_daily" {
  rule      = aws_cloudwatch_event_rule.ebs_sweeper_daily.name
  target_id = "ebs-sweeper"
  arn       = aws_lambda_function.ebs_sweeper.arn
}

resource "aws_lambda_permission" "ebs_sweeper_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ebs_sweeper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ebs_sweeper_daily.arn
}

output "ebs_sweeper_function_name" {
  description = "Lambda function name; tail with `aws logs tail /aws/lambda/<name> --follow`."
  value       = aws_lambda_function.ebs_sweeper.function_name
}
