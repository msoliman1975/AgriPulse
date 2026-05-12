# Wildcard ACM certs covering the three per-env subdomains. cert-manager
# handles per-Ingress certs via DNS-01 below; this ACM cert is reserved for
# regional-NLB / ALB termination in case a service migrates off
# ingress-nginx later. DNS-01 validation against the Route 53 zone happens
# automatically through the aws_route53_record loop.

resource "aws_acm_certificate" "wildcard" {
  domain_name = var.root_domain
  subject_alternative_names = [
    "*.${var.root_domain}",
    "*.dev.${var.root_domain}",
    "*.staging.${var.root_domain}",
  ]
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.root_domain}-wildcard"
  })
}

resource "aws_route53_record" "wildcard_validation" {
  for_each = {
    for dvo in aws_acm_certificate.wildcard.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = local.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "wildcard" {
  certificate_arn         = aws_acm_certificate.wildcard.arn
  validation_record_fqdns = [for record in aws_route53_record.wildcard_validation : record.fqdn]
}
