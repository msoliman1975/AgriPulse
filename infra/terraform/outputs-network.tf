output "vpc_id" {
  description = "ID of the VPC."
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (one per AZ)."
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnet IDs (one per AZ)."
  value       = module.vpc.public_subnets
}
