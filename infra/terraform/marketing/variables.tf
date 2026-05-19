variable "region" {
  description = "Primary AWS region (S3 bucket lives here)."
  type        = string
  default     = "eu-south-1"
}

variable "environment" {
  description = "Environment name. Marketing is a single shared instance; we use 'prod'."
  type        = string
  default     = "prod"
}

variable "root_domain" {
  description = "Public DNS zone hosting the site. Must already exist in Route53."
  type        = string
  default     = "agripulse.cloud"
}

variable "site_hostnames" {
  description = "Hostnames the CloudFront distribution serves."
  type        = list(string)
  default     = ["agripulse.cloud", "www.agripulse.cloud"]
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 = NA + EU + Israel edges (cheapest, sufficient for MENA latency)."
  type        = string
  default     = "PriceClass_100"
}
