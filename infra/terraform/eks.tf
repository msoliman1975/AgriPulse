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
    provider_key_arn = aws_kms_key.agripulse.arn
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
      # IRSA role gives the controller pods the EC2 perms they need to
      # create/attach volumes; without it the addon hangs in CREATING.
      service_account_role_arn = module.iam_role_ebs_csi.iam_role_arn
      # Controller pods must tolerate the system-only taint on the default
      # node group; without this the addon hangs in CREATING because no
      # node accepts the controller deployment.
      configuration_values = jsonencode({
        controller = {
          tolerations = [
            {
              key      = "CriticalAddonsOnly"
              operator = "Exists"
            },
          ]
        }
      })
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
        "agripulse.cloud/role" = "system"
      }

      taints = {
        critical = {
          key    = "CriticalAddonsOnly"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      }

      # AmazonSSMManagedInstanceCore lets the EKS node register with SSM,
      # which is the supported escape hatch for `kubectl` from a laptop
      # behind Netskope (it MITMs *.eks.amazonaws.com; SSM port-forward
      # bypasses that). Without this the first session-manager-plugin
      # tunnel fails with TargetNotConnected.
      iam_role_additional_policies = {
        AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
      }

      tags = local.common_tags
    }
  }

  # The cluster creator (whoever runs `terraform apply`) gets a managed
  # access entry with cluster-admin via the module. Keep this disabled
  # and use the explicit `access_entries` map below — that way the SSO
  # admin role keeps cluster-admin even when a CI service-role (or any
  # other principal) runs `terraform apply` later.
  enable_cluster_creator_admin_permissions = false

  # Map the SSO Administrator role into the cluster so kubectl from a
  # laptop (via the SSO `agripulse` profile) is admin out of the gate.
  # Without this entry, every fresh bootstrap requires manually running
  # `aws eks create-access-entry` for the SSO role before kubectl works.
  # The path-prefixed ARN form is required — EKS rejects the simpler
  # `role/AWSReservedSSO_...` form.
  access_entries = {
    sso_admin = {
      principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_${var.sso_admin_permission_set_id}"
      policy_associations = {
        cluster_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  tags = local.common_tags
}
