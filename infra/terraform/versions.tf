terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
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
    # CD-15: used to zip the EBS sweeper + Slack publisher Lambda
    # source directories at apply time, so the .py files in
    # infra/terraform/{ebs-sweeper,slack-publisher}-lambda/ ship
    # straight to Lambda without a separate build step.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
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
