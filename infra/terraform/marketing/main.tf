# --------------------------------------------------------------------------
# Marketing site for agripulse.cloud
#
# Static Astro build served from a private S3 bucket via CloudFront with an
# Origin Access Control. ACM cert lives in us-east-1 (CloudFront requirement).
# Apex + www both alias to the same distribution; no redirect, same content.
# --------------------------------------------------------------------------

data "aws_route53_zone" "root" {
  name         = var.root_domain
  private_zone = false
}

# --------------------------------------------------------------------------
# S3 bucket — private, encrypted, versioned. Only CloudFront can read.
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "site" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Bucket policy is wired after the distribution exists so we can scope on its ARN.
data "aws_iam_policy_document" "site_bucket" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json
}

# --------------------------------------------------------------------------
# ACM cert — issued in us-east-1 for CloudFront, validated via Route53.
# --------------------------------------------------------------------------

resource "aws_acm_certificate" "site" {
  provider                  = aws.us_east_1
  domain_name               = var.root_domain
  subject_alternative_names = [for h in var.site_hostnames : h if h != var.root_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "site_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = data.aws_route53_zone.root.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "site" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for r in aws_route53_record.site_cert_validation : r.fqdn]
}

# --------------------------------------------------------------------------
# CloudFront — distribution, OAC, viewer-request function for /foo → /foo/index.html
# --------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "agripulse-marketing"
  description                       = "OAC for the marketing site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Astro builds with format=directory: dist/capabilities/index.html etc.
# CloudFront doesn't automatically append index.html to subdirectory paths,
# so this viewer-request function does it.
resource "aws_cloudfront_function" "index_rewrite" {
  name    = "agripulse-marketing-index-rewrite"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      if (uri.endsWith('/')) {
        request.uri += 'index.html';
      } else if (!uri.includes('.')) {
        request.uri += '/index.html';
      }
      return request;
    }
  EOT
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  default_root_object = "index.html"
  aliases             = var.site_hostnames
  comment             = "AgriPulse marketing site"
  price_class         = var.price_class

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-${aws_s3_bucket.site.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-${aws_s3_bucket.site.id}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS-managed CachingOptimized policy — honors origin Cache-Control headers.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.index_rewrite.arn
    }
  }

  # OAC returns 403 when an S3 object doesn't exist. Map that (and any 404)
  # to /index.html with a real 404 status code so visitors get a clean
  # branded page rather than the default CloudFront error template.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/index.html"
    error_caching_min_ttl = 60
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/index.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

# --------------------------------------------------------------------------
# Route53 — apex + www, both A + AAAA, ALIAS to the CloudFront distribution.
# --------------------------------------------------------------------------

locals {
  alias_records = flatten([
    for host in var.site_hostnames : [
      { host = host, type = "A" },
      { host = host, type = "AAAA" },
    ]
  ])
}

resource "aws_route53_record" "site_alias" {
  for_each = { for r in local.alias_records : "${r.host}-${r.type}" => r }

  zone_id = data.aws_route53_zone.root.zone_id
  name    = each.value.host
  type    = each.value.type

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
