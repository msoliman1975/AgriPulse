# Marketing site infra — agripulse.cloud

Static Astro site at the apex domain. Single tier, no separate envs.

## What this module provisions

| Resource | Purpose |
|---|---|
| `aws_s3_bucket.site` | Private, versioned, server-side-encrypted bucket holding the static build. |
| `aws_cloudfront_origin_access_control.site` | Locks bucket reads to this distribution only. |
| `aws_cloudfront_function.index_rewrite` | Appends `/index.html` to subdirectory requests so `/capabilities` resolves. |
| `aws_cloudfront_distribution.site` | Edge CDN, HTTP/2 + HTTP/3, TLS 1.2_2021, IPv6 on. Aliased to apex + www. |
| `aws_acm_certificate.site` *(us-east-1)* | DNS-validated cert for `agripulse.cloud` + `www.agripulse.cloud`. CloudFront only accepts certs from us-east-1. |
| `aws_route53_record.site_alias` | A + AAAA aliases on apex and www, both pointing at the distribution. |

Both hostnames serve the same content (no redirect). The Route53 zone for
`agripulse.cloud` is **read** here via data source — it's managed by the
main infra-tf root, not this module.

## First-time apply

The user running this needs:

1. **An active AWS SSO session** to the `agripulse` profile:
   ```powershell
   aws sso login --profile agripulse
   $env:AWS_PROFILE = "agripulse"
   ```
2. **Terraform 1.9+** in PATH.
3. The **`agripulse-tfstate-<account-id>` bucket + `agripulse-tfstate-lock`
   DynamoDB table** already created (they are — the main infra-tf root uses
   the same backend).

Get the account id once:

```powershell
$acct = (aws sts get-caller-identity --query Account --output text)
Write-Host "Account: $acct"
```

Then from `infra/terraform/marketing/`:

```powershell
terraform init `
  -backend-config="bucket=agripulse-tfstate-$acct" `
  -backend-config="key=marketing/terraform.tfstate" `
  -backend-config="region=eu-south-1" `
  -backend-config="encrypt=true" `
  -backend-config="dynamodb_table=agripulse-tfstate-lock"

terraform plan -out=marketing.tfplan
terraform apply marketing.tfplan
```

**Expected duration:** ~10 minutes. CloudFront distribution creation is the
slow step (5–8 min). ACM cert validation via Route53 is usually under a
minute.

## After the first apply

Push the current build to S3 + invalidate the cache:

```powershell
..\..\..\marketing\scripts\deploy.ps1
```

Or from anywhere:

```powershell
& "$repo\marketing\scripts\deploy.ps1"
```

The script:

1. Runs `pnpm build` in `marketing/`.
2. Reads `bucket_name` and `distribution_id` from this module's TF outputs.
3. `aws s3 sync` everything with a 5-minute cache TTL.
4. Re-uploads `_astro/` (Astro's fingerprinted assets) with a 1-year
   immutable TTL.
5. Issues a CloudFront invalidation on `/*`.

## Tearing it down

```powershell
terraform destroy
```

This **does not** delete the Route53 zone — that's owned by the main root.
It does delete the bucket (versioning is on, so objects survive briefly in
non-current versions if anything goes wrong — set a lifecycle rule if you
want hard-delete after N days).

## Known gotchas

- **Netskope TLS-MITM** can break the AWS provider during the ACM cert
  flow. If `terraform apply` hangs on `aws_acm_certificate_validation`,
  check Netskope status — same pattern as the cluster bootstrap.
- **The distribution lives at edge cache** — invalidations cost $0.005 per
  path beyond the first 1000/month free. `/*` counts as one path; we're
  unlikely to hit the limit.
- **Apex aliases need ALIAS records, not CNAMEs.** Route53 supports A/AAAA
  ALIAS at apex; do not switch these to CNAME if you ever rework them.
