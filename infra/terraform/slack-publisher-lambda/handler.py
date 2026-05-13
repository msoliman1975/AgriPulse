"""CD-15: forward SNS cost alerts to Slack.

Invoked by an SNS subscription on `missionagre-<env>-cost-alerts`. Pulls
the webhook URL from Secrets Manager (the ARN lives in env var
SLACK_WEBHOOK_SECRET_ARN) and POSTs the SNS message as a Slack
incoming-webhook payload.
"""
from __future__ import annotations

import json
import os
import urllib.request

import boto3

_secrets = boto3.client("secretsmanager")


def _webhook_url() -> str | None:
    arn = os.environ.get("SLACK_WEBHOOK_SECRET_ARN", "")
    if not arn:
        return None
    return _secrets.get_secret_value(SecretId=arn)["SecretString"].strip()


def handler(event, _ctx):
    env = os.environ.get("ENVIRONMENT", "unknown")
    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        subject = sns.get("Subject", "(no subject)")
        message = sns.get("Message", "")
        webhook = _webhook_url()
        if not webhook:
            # No webhook seeded yet — log and exit success so SNS
            # doesn't retry forever. CloudWatch surfaces this clearly.
            print(json.dumps({"level": "warn", "msg": "no webhook URL", "subject": subject}))
            continue
        payload = {
            "text": f":money_with_wings: *AWS Budgets* ({env})\n*{subject}*\n```{message}```",
        }
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(json.dumps({"level": "info", "msg": "slack post", "status": resp.status}))
    return {"ok": True}
