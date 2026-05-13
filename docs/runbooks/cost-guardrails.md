# Cost guardrails

CD-15. Three controls keep cloud cost visible and reactive:

1. **AWS Budgets alarm** (`infra/terraform/budgets.tf`) — $300/mo
   default, 80% forecast + 100% actual thresholds, SNS → Lambda → Slack.
2. **EBS sweeper** (`infra/terraform/ebs-sweeper.tf`) — daily Lambda
   that snapshots-then-deletes orphan EBS volumes older than 7 days.
3. **Prometheus rules** (`infra/helm/shared/templates/prometheusrule-cost.yaml`) —
   `IdlePodCPU` + `IdlePodMemory` warn when a pod sits idle for 24h.

## Verifying the budget alarm

```bash
aws budgets describe-budgets --account-id "$(aws sts get-caller-identity --query Account --output text)"
aws sns list-subscriptions-by-topic --topic-arn "$(terraform -chdir=infra/terraform output -raw cost_alerts_topic_arn)"
```

To fire a test alert without waiting for spend:

1. Temporarily drop `var.budget_monthly_limit_usd` below this month's
   actual spend.
2. `terraform -chdir=infra/terraform apply`.
3. Wait for the next Budgets evaluation cycle (~3h).
4. After the Slack post lands, restore the original limit and re-apply.

## Flipping the EBS sweeper out of dry-run

The sweeper deploys with `DRY_RUN=true` so the first week is observation
only. Tail logs:

```bash
aws logs tail "/aws/lambda/$(terraform -chdir=infra/terraform output -raw ebs_sweeper_function_name)" \
  --follow --since 2d
```

Every entry has `level=info` plus `volume=`, `age_days=`, `size_gb=` for
each candidate. If the list is what you expect:

1. Set `ebs_sweeper_dry_run = false` in your tfvars (or flip the
   default in `infra/terraform/ebs-sweeper.tf`).
2. `terraform -chdir=infra/terraform apply`.
3. Re-tail logs the next morning; entries will now include
   `msg=snapshotted` and `msg=deleted`.

If anything is in the dry-run list that should not be touched, tag the
volume `keep=true` and the sweeper skips it forever:

```bash
aws ec2 create-tags --resources vol-0123 --tags Key=keep,Value=true
```

## Responding to `IdlePodCPU` / `IdlePodMemory`

These alerts are **cost** signals, not health signals. Triggering means
the alerted pod averaged <2% CPU (or <10% memory limit) for 24h
continuously. Two valid responses:

- **Workload is needed, sized too generously.** Drop the
  `resources.limits` (or `requests`, or `replicaCount`) and let HPA do
  its job. Re-evaluate after a week.
- **Workload is not needed.** Disable in the per-env overlay. If it's a
  CronJob with a long interval, the alert won't fire (the rules ignore
  pods that scale to zero between runs).

The alerts filter out `kube-*`, `argocd`, `external-secrets`, and
`cnpg-system` because those have their own opinionated sizing. If a new
control-plane namespace ships, extend the `namespace!~` regex in
`infra/helm/shared/templates/prometheusrule-cost.yaml`.

## Tuning the thresholds

The defaults are deliberately conservative — pages should be rare. If
you find yourself wanting an alert for moderate-but-not-idle waste,
copy the rule into `prometheusrule-cost.yaml` with a higher threshold
and a separate `alert:` name; don't relax the existing rule because the
2%/10% values are documented across runbooks.
