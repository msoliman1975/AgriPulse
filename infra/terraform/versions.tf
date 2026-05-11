terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.44"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in S3 + DynamoDB lock table. Bucket and table are created
  # outside Terraform (chicken-and-egg) — the bootstrap script in
  # infra/terraform/scripts/bootstrap-state.sh creates them once per AWS
  # account. Backend init is `terraform init -backend-config=...`.
  backend "s3" {
    # Configured per env via -backend-config in CI:
    #   bucket  = "missionagre-tfstate-<account-id>"
    #   key     = "<env>/terraform.tfstate"
    #   region  = "me-south-1"
    #   encrypt = true
    #   dynamodb_table = "missionagre-tfstate-lock"
  }
}
