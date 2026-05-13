# CD-15 — AWS Budgets alarm with Slack delivery.
#
# Pays for itself the first time it fires. Two thresholds: 80% on
# *forecast* (early warning while we can still react) and 100% on
# *actual* (the cap was breached). Both notify the same SNS topic; an
# operator-owned Slack webhook subscription fans them out to #ops-alerts.
#
# Slack delivery: a Lambda subscription pulls the webhook URL from
# Secrets Manager at invocation time and POSTs the SNS message. AWS
# Chatbot would be one click less work but adds a service we'd otherwise
# not depend on (and locks us into the Chatbot config UI for routing
# changes). Stick with the Lambda — same pattern as the EBS sweeper.

variable "budget_monthly_limit_usd" {
  description = "CD-15 monthly cost alarm threshold (USD). 80% forecasted + 100% actual both notify."
  type        = number
  default     = 300
}

variable "budget_slack_webhook_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Slack incoming-webhook URL the budget Lambda POSTs to. Seed via `aws secretsmanager put-secret-value` once per account."
  type        = string
  default     = ""
}

resource "aws_sns_topic" "cost_alerts" {
  name              = "missionagre-${var.environment}-cost-alerts"
  kms_master_key_id = aws_kms_key.missionagre.id

  tags = local.common_tags
}

resource "aws_sns_topic_policy" "cost_alerts_budgets" {
  arn = aws_sns_topic.cost_alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowBudgetsPublish"
        Effect = "Allow"
        Principal = {
          Service = "budgets.amazonaws.com"
        }
        Action   = "SNS:Publish"
        Resource = aws_sns_topic.cost_alerts.arn
      },
    ]
  })
}

resource "aws_budgets_budget" "monthly_cost" {
  name         = "missionagre-${var.environment}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_monthly_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Forecasted threshold: gives us ~2 weeks of headroom in a typical
  # month. Tune down to 70 if cost trends start running hot.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = [aws_sns_topic.cost_alerts.arn]
    subscriber_email_addresses = []
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.cost_alerts.arn]
    subscriber_email_addresses = []
  }
}

# Lambda that POSTs SNS messages to Slack. Same code path as the EBS
# sweeper's CloudWatch logger but pointed at a webhook secret. Keeping
# them as separate functions (rather than one fan-out) so a broken Slack
# webhook can't suppress the next-day sweeper invocation.

data "aws_iam_policy_document" "slack_publisher_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "slack_publisher" {
  name               = "missionagre-${var.environment}-slack-publisher"
  assume_role_policy = data.aws_iam_policy_document.slack_publisher_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "slack_publisher_basic" {
  role       = aws_iam_role.slack_publisher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "slack_publisher_read_secret" {
  count = var.budget_slack_webhook_secret_arn == "" ? 0 : 1

  name = "missionagre-${var.environment}-slack-publisher-read"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = var.budget_slack_webhook_secret_arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "slack_publisher_read_secret" {
  count      = var.budget_slack_webhook_secret_arn == "" ? 0 : 1
  role       = aws_iam_role.slack_publisher.name
  policy_arn = aws_iam_policy.slack_publisher_read_secret[0].arn
}

data "archive_file" "slack_publisher" {
  type        = "zip"
  source_dir  = "${path.module}/slack-publisher-lambda"
  output_path = "${path.module}/.terraform-build/slack-publisher.zip"
}

resource "aws_lambda_function" "slack_publisher" {
  function_name    = "missionagre-${var.environment}-slack-publisher"
  description      = "CD-15: forwards SNS cost alerts to Slack via incoming webhook."
  role             = aws_iam_role.slack_publisher.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.slack_publisher.output_path
  source_code_hash = data.archive_file.slack_publisher.output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      SLACK_WEBHOOK_SECRET_ARN = var.budget_slack_webhook_secret_arn
      ENVIRONMENT              = var.environment
    }
  }

  tags = local.common_tags
}

resource "aws_lambda_permission" "slack_publisher_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_publisher.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.cost_alerts.arn
}

resource "aws_sns_topic_subscription" "slack_publisher" {
  topic_arn = aws_sns_topic.cost_alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.slack_publisher.arn
}

output "cost_alerts_topic_arn" {
  description = "SNS topic that receives Budget threshold notifications and fans them to Slack."
  value       = aws_sns_topic.cost_alerts.arn
}
