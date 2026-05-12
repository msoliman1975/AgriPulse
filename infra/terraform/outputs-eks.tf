output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_oidc_issuer_url" {
  description = "OIDC provider URL for the cluster (used by IRSA)."
  value       = module.eks.cluster_oidc_issuer_url
}
