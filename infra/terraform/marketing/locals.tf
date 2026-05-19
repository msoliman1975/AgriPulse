locals {
  bucket_name = "agripulse-marketing-${var.environment}"

  common_tags = {
    Project     = "agripulse"
    Component   = "marketing-site"
    Environment = var.environment
    ManagedBy   = "terraform"
    Repo        = "msoliman1975/AgriPulse"
  }
}
