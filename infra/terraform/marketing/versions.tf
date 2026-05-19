terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # State lives in the same S3 backend as the main infra-tf root, but under a
  # separate key so marketing-site applies don't lock the cluster state and
  # vice-versa. Initialize with:
  #
  #   terraform init \
  #     -backend-config="bucket=agripulse-tfstate-<account-id>" \
  #     -backend-config="key=marketing/terraform.tfstate" \
  #     -backend-config="region=eu-south-1" \
  #     -backend-config="encrypt=true" \
  #     -backend-config="dynamodb_table=agripulse-tfstate-lock"
  backend "s3" {}
}
