#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Build the AgriPulse marketing site and deploy it to S3 + CloudFront.

.DESCRIPTION
  Reads the bucket name + distribution id from the Terraform state in
  infra/terraform/marketing, syncs the freshly built dist/ to S3 with
  long-lived caching for fingerprinted assets and short-lived caching
  for everything else, then issues a CloudFront invalidation so the
  new content shows up immediately.

.NOTES
  Requires:
    - pnpm (for the build step)
    - terraform (to read outputs)
    - aws CLI
    - $env:AWS_PROFILE set to a profile with permissions on the bucket
      and the distribution. Defaults to 'agripulse' if unset.
#>

$ErrorActionPreference = "Stop"

if (-not $env:AWS_PROFILE) {
  $env:AWS_PROFILE = "agripulse"
  Write-Host "AWS_PROFILE not set; defaulting to 'agripulse'."
}

# Resolve repo-relative paths from the script location.
$here       = $PSScriptRoot
$marketing  = (Resolve-Path (Join-Path $here "..")).Path
$tfdir      = (Resolve-Path (Join-Path $marketing "..\infra\terraform\marketing")).Path
$distDir    = Join-Path $marketing "dist"

# ---------------------------------------------------------------------------
# Step 1 — build
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Building site in $marketing"
Push-Location $marketing
try {
  pnpm install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw "pnpm install failed" }
  pnpm build
  if ($LASTEXITCODE -ne 0) { throw "pnpm build failed" }
} finally {
  Pop-Location
}

if (-not (Test-Path $distDir)) {
  throw "Build did not produce $distDir"
}

# ---------------------------------------------------------------------------
# Step 2 — read Terraform outputs
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Reading Terraform outputs from $tfdir"
Push-Location $tfdir
try {
  $bucket = (terraform output -raw bucket_name 2>$null)
  if (-not $bucket) { throw "Could not read bucket_name from terraform output. Did you run terraform apply?" }
  $dist = (terraform output -raw distribution_id 2>$null)
  if (-not $dist) { throw "Could not read distribution_id from terraform output." }
} finally {
  Pop-Location
}
Write-Host "    bucket           = $bucket"
Write-Host "    distribution_id  = $dist"

# ---------------------------------------------------------------------------
# Step 3 — sync to S3
#   First pass: everything with short-lived caching.
#   Second pass: re-upload Astro's fingerprinted /_astro assets with a
#                long immutable TTL.
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Syncing $distDir -> s3://$bucket/"
aws s3 sync $distDir "s3://$bucket/" `
  --delete `
  --cache-control "public,max-age=300,s-maxage=300"
if ($LASTEXITCODE -ne 0) { throw "s3 sync (root) failed" }

$astroDir = Join-Path $distDir "_astro"
if (Test-Path $astroDir) {
  Write-Host "==> Re-uploading _astro/ with immutable cache headers"
  aws s3 cp $astroDir "s3://$bucket/_astro" `
    --recursive `
    --cache-control "public,max-age=31536000,immutable" `
    --metadata-directive REPLACE
  if ($LASTEXITCODE -ne 0) { throw "s3 cp (_astro) failed" }
}

# ---------------------------------------------------------------------------
# Step 4 — invalidate CloudFront
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==> Invalidating CloudFront distribution $dist"
$invalidation = aws cloudfront create-invalidation `
  --distribution-id $dist `
  --paths "/*" `
  --output json | ConvertFrom-Json

Write-Host "    invalidation id = $($invalidation.Invalidation.Id)"
Write-Host ""
Write-Host "Done."
Write-Host "https://agripulse.cloud  (allow ~1-3 minutes for the invalidation to propagate)"
