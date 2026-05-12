# Single public hosted zone for agripulse.cloud. Per-env hostnames use
# prefixed records (api.dev.agripulse.cloud, api.staging.agripulse.cloud,
# api.agripulse.cloud) rather than per-env subzones; ExternalDNS in each
# EKS namespace owns its own prefix via TXT-record ownership.

variable "create_hosted_zone" {
  description = "Whether Terraform should create the Route 53 hosted zone. Set false if the zone was created manually and should only be referenced via data."
  type        = bool
  default     = true
}

variable "root_domain" {
  description = "Root DNS zone owned by the project."
  type        = string
  default     = "agripulse.cloud"
}

resource "aws_route53_zone" "root" {
  count = var.create_hosted_zone ? 1 : 0

  name    = var.root_domain
  comment = "Public DNS zone for ${var.root_domain}. Managed by Terraform."

  tags = local.common_tags
}

data "aws_route53_zone" "root" {
  count = var.create_hosted_zone ? 0 : 1

  name         = var.root_domain
  private_zone = false
}

locals {
  route53_zone_id     = var.create_hosted_zone ? aws_route53_zone.root[0].zone_id : data.aws_route53_zone.root[0].zone_id
  route53_zone_arn    = var.create_hosted_zone ? aws_route53_zone.root[0].arn : data.aws_route53_zone.root[0].arn
  route53_zone_name   = var.root_domain
  route53_nameservers = var.create_hosted_zone ? aws_route53_zone.root[0].name_servers : data.aws_route53_zone.root[0].name_servers
}
