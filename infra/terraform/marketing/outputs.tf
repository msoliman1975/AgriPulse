output "bucket_name" {
  description = "S3 bucket holding the static site."
  value       = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  description = "CloudFront distribution ID — pass to `aws cloudfront create-invalidation` after each deploy."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_domain" {
  description = "Default CloudFront *.cloudfront.net domain. Useful for direct testing before DNS propagates."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "site_hostnames" {
  description = "Public hostnames served by the distribution."
  value       = var.site_hostnames
}

output "certificate_arn" {
  description = "ACM certificate ARN (in us-east-1) attached to the distribution."
  value       = aws_acm_certificate_validation.site.certificate_arn
}
