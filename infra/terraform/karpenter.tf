# CD-8 â€” Karpenter controller IAM + interruption queue + EventBridge.
#
# The terraform-aws-modules/eks/aws//modules/karpenter submodule produces
# the controller IRSA role, the EC2 node-instance profile Karpenter will
# attach to launched instances, the SQS interruption queue, and the
# EventBridge rules wiring spot-rebalance + spot-interruption + state-
# change events into the queue. Karpenter helm chart values reference the
# outputs of this module.

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.27"

  cluster_name = module.eks.cluster_name

  # Use IRSA for the controller (vs Pod Identity). Keeps us on the same
  # auth model as every other in-cluster controller.
  enable_irsa                     = true
  irsa_oidc_provider_arn          = module.eks.oidc_provider_arn
  irsa_namespace_service_accounts = ["karpenter:karpenter"]

  # Node IAM role â€” Karpenter attaches this to instances it launches.
  # `enable_pod_identity_association` etc. left at defaults.
  create_node_iam_role          = true
  node_iam_role_name            = "agripulse-${var.environment}-karpenter-node"
  node_iam_role_use_name_prefix = false
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  tags = local.common_tags
}

# Tag the private subnets and the node-group security group so Karpenter's
# subnet/SG selectors find them at provisioning time.

resource "aws_ec2_tag" "private_subnet_karpenter" {
  for_each = toset(module.vpc.private_subnets)

  resource_id = each.value
  key         = "karpenter.sh/discovery"
  value       = module.eks.cluster_name
}

resource "aws_ec2_tag" "node_sg_karpenter" {
  resource_id = module.eks.node_security_group_id
  key         = "karpenter.sh/discovery"
  value       = module.eks.cluster_name
}

# Service-linked role required before any EC2 Spot launch can succeed.
# Brand-new AWS accounts do not have this role; Karpenter's first Spot
# fleet then fails with AuthFailure.ServiceLinkedRoleCreationNotPermitted.
# AWS auto-creates the role on first console-launched Spot instance, so
# accounts that have used Spot before will already have it.
#
# Conditional create: if the role already exists on the account (auto-
# created by AWS, manually created via `aws iam create-service-linked-role`,
# or carried over from a prior cluster), the data lookup succeeds and the
# resource is not created. Otherwise terraform creates it.
data "aws_iam_roles" "spot_slr" {
  name_regex  = "^AWSServiceRoleForEC2Spot$"
  path_prefix = "/aws-service-role/spot.amazonaws.com/"
}

resource "aws_iam_service_linked_role" "spot" {
  count            = length(data.aws_iam_roles.spot_slr.names) == 0 ? 1 : 0
  aws_service_name = "spot.amazonaws.com"
  description      = "Required for Karpenter Spot launches (managed by AgriPulse terraform)"
}
