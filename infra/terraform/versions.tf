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
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.16"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.33"
    }
  }

  # State lives in S3 + DynamoDB lock table. Bucket and table are created
  # outside Terraform (chicken-and-egg) â€” the bootstrap script in
  # infra/terraform/scripts/bootstrap-state.sh creates them once per AWS
  # account. Backend init is `terraform init -backend-config=...`.
  backend "s3" {
    # Configured per env via -backend-config in CI:
    #   bucket  = "agripulse-tfstate-<account-id>"
    #   key     = "<env>/terraform.tfstate"
    #   region  = "eu-south-1"
    #   encrypt = true
    #   dynamodb_table = "agripulse-tfstate-lock"
  }
}
