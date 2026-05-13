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

# Kubernetes + Helm providers used by argocd.tf to install ArgoCD itself.
# Auth piggy-backs on the EKS module's outputs; `aws eks get-token` keeps the
# bearer token fresh (vs. a one-shot `data.aws_eks_cluster_auth` token that
# expires mid-apply on long runs).
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", module.eks.cluster_name,
      "--region", var.region,
    ]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args = [
        "eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--region", var.region,
      ]
    }
  }
}
