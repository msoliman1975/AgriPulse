# CD-8 — Karpenter: controller, NodePool, EC2NodeClass

[Shared preamble — see README.md]

## Goal
Replace the current `eks_managed_node_groups.default` block (which has fixed min/max/desired and no spot) with Karpenter for dynamic, cost-optimized node provisioning. Keep a minimal on-demand baseline for system pods (Karpenter itself, kube-prometheus operator) so the cluster never hits zero nodes.

## Files to change
- `infra/terraform/eks.tf` — shrink the default managed node group to a 1-node `t4g.medium` baseline tagged for system pods. Add a tag/label scheme `missionagre.io/role=system`.
- `infra/terraform/karpenter.tf` — new. Karpenter controller IRSA, SQS interruption queue, EventBridge rules for spot interruption + instance state change.
- `infra/argocd/platform-values/karpenter.yaml` — new (or add to platform AppSet).
- `infra/argocd/appsets/platform.yaml` — add `karpenter` if not already present.
- `infra/helm/shared/templates/karpenter-nodepools.yaml` — new. NodePool + EC2NodeClass resources.
- `infra/helm/shared/values.yaml` — `karpenter` block.

## Tasks
1. Terraform:
   - Karpenter controller IAM role + IRSA. Use the official `terraform-aws-modules/eks/aws//modules/karpenter` submodule if it's compatible with the EKS module version you're already on (~> 20.27).
   - SQS interruption queue + EventBridge rules.
   - Tag subnets (private) with `karpenter.sh/discovery: <cluster-name>`.
   - Tag node-group security group with `karpenter.sh/discovery: <cluster-name>`.
2. Shrink the existing `default` managed node group to: `min_size=1`, `max_size=2`, `desired_size=1`, `instance_types=["t4g.medium"]`, labels include `missionagre.io/role: system`, taints `CriticalAddonsOnly=true:NoSchedule`. This keeps Karpenter + kube-prometheus operator + ingress-nginx (mark them with appropriate tolerations) on the baseline node.
3. Karpenter helm chart values (`infra/argocd/platform-values/karpenter.yaml`):
   - `serviceAccount.annotations` with the IRSA ARN.
   - `settings.clusterName`, `settings.interruptionQueue`.
   - `replicas: 2` (HA controller).
4. NodePool (`infra/helm/shared/templates/karpenter-nodepools.yaml`):
   - One `NodePool` named `general` with weight 10:
     - Requirements: `kubernetes.io/arch: [arm64, amd64]`, `karpenter.sh/capacity-type: [spot, on-demand]` (spot first per Karpenter's price-based ordering).
     - `instance-family: [t, m, c]`, exclude metal sizes.
     - `limits: cpu: 100` (cluster-wide cap).
     - `disruption.consolidationPolicy: WhenUnderutilized`, `expireAfter: 720h` (force-rotate every 30 days).
   - One `EC2NodeClass` named `default`:
     - `amiFamily: AL2023`.
     - `role: <node IAM role from EKS module>`.
     - `subnetSelectorTerms` and `securityGroupSelectorTerms` matching the `karpenter.sh/discovery` tag.
     - `blockDeviceMappings`: 50Gi gp3 root.
5. Add `CriticalAddonsOnly` tolerations to: karpenter controller deployment, kube-prometheus-stack operator, ingress-nginx controller. They must be schedulable on the baseline.

## Out of scope
- Don't create separate NodePools for spot-only workloads in this PR. The single NodePool with mixed capacity types handles 90 % of cases.
- Don't migrate the workers to spot-only just yet. That's a follow-up tuning PR.
- Don't enable Karpenter's drift detection (`disruption.budgets`) — defaults are fine.

## Definition of done
- `terraform apply` succeeds without recreating the EKS cluster (only shrinking node group + adding Karpenter resources).
- After ArgoCD syncs Karpenter, `kubectl get nodepool,ec2nodeclass` shows the two resources.
- Pending pod with a 2-CPU request triggers Karpenter to provision a node within 90 s (`kubectl get nodes -w`).
- Removing the pod causes Karpenter to consolidate the node away within ~15 min.
- PR description includes the verify commands and the expected baseline cost change (~$25/mo baseline + Karpenter-managed elastic spend on top).
