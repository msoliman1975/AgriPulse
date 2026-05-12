module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.27"

  cluster_name    = local.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Encrypt secrets at rest with our KMS key.
  cluster_encryption_config = {
    provider_key_arn = aws_kms_key.missionagre.arn
    resources        = ["secrets"]
  }

  # Bare cluster add-ons; the rest are installed via ArgoCD ApplicationSets.
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
    aws-ebs-csi-driver = {
      most_recent = true
    }
  }

  eks_managed_node_groups = {
    # Baseline node group for cluster-critical pods only: Karpenter
    # controller, ingress-nginx, kube-prometheus-stack operator. Karpenter
    # provisions everything else dynamically; this group exists so the
    # cluster never hits zero nodes and Karpenter itself always has a home.
    default = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = ["t4g.medium"]
      desired_size   = 1
      min_size       = 1
      max_size       = 2

      labels = {
        "missionagre.io/role" = "system"
      }

      taints = {
        critical = {
          key    = "CriticalAddonsOnly"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      }

      tags = local.common_tags
    }
  }

  enable_cluster_creator_admin_permissions = true

  tags = local.common_tags
}
