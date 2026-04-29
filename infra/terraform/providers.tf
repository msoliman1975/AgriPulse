provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "missionagre"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "msoliman1975/MissionAgre"
    }
  }
}
