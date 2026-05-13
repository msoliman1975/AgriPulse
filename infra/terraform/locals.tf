locals {
  cluster_name = coalesce(var.cluster_name, "missionagre-${var.environment}")

  # Three AZs; me-south-1 has 1a, 1b, 1c.
  azs = ["${var.region}a", "${var.region}b", "${var.region}c"]

  # Public subnets host the NLB; private subnets host EKS nodes and
  # private endpoints. /20 each gives us ~4k IPs per subnet.
  public_subnets  = [cidrsubnet(var.vpc_cidr, 4, 0), cidrsubnet(var.vpc_cidr, 4, 1), cidrsubnet(var.vpc_cidr, 4, 2)]
  private_subnets = [cidrsubnet(var.vpc_cidr, 4, 3), cidrsubnet(var.vpc_cidr, 4, 4), cidrsubnet(var.vpc_cidr, 4, 5)]

  common_tags = merge(
    {
      "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    },
    var.tags
  )

  # CD-10 — ArgoCD UI hostname. Single name across all envs because we run one
  # ArgoCD per cluster, and the cluster is per-env. ExternalDNS + cert-manager
  # produce the A record + cert against the agripulse.cloud hosted zone.
  argocd_hostname = "argocd.agripulse.cloud"
}
