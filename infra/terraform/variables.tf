variable "region" {
  description = "AWS region. ARCHITECTURE.md Â§ 3.2 commits eu-south-1 (Milan)."
  type        = string
  default     = "eu-south-1"
}

variable "environment" {
  description = "One of dev, staging, production."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be dev, staging, or production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.30.0.0/16"
}

variable "cluster_name" {
  description = "EKS cluster name; defaults to agripulse-<env>."
  type        = string
  default     = ""
}

variable "cluster_version" {
  description = "Kubernetes minor version for the EKS control plane."
  type        = string
  default     = "1.31"
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_desired_size" {
  description = "Desired number of nodes in the managed node group."
  type        = number
  default     = 3
}

variable "node_min_size" {
  description = "Minimum number of nodes."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum number of nodes."
  type        = number
  default     = 6
}

variable "tags" {
  description = "Additional tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "argocd_chart_version" {
  description = "Pinned argo/argo-cd Helm chart version (CD-10)."
  type        = string
  default     = "7.7.3"
}

variable "argocd_admin_allowlist_cidrs" {
  description = "CIDRs allowed to hit the ArgoCD UI ingress until Keycloak SSO lands (CD-13). Empty list disables the whitelist (open to the internet â€” only use for break-glass)."
  type        = list(string)
  default     = []
}

variable "sso_admin_permission_set_id" {
  description = "Trailing hash on the SSO permission-set role ARN — e.g. for `AWSReservedSSO_AdministratorAccess_519336c3efbae36e`, set this to `519336c3efbae36e`. Used by eks.tf's access_entries map to grant the SSO admin role cluster-admin so kubectl-from-laptop works without manual setup after a fresh bootstrap. Find via `aws iam list-roles --query \"Roles[?starts_with(RoleName, 'AWSReservedSSO_AdministratorAccess')].RoleName\"`."
  type        = string
  default     = "519336c3efbae36e"
}

variable "environments" {
  description = "Logical envs whose S3 buckets + IRSA roles this stack owns (regardless of var.environment). Imagery + pg-backup buckets are global resources; one TF stack owns all three so per-env apply doesn't drift."
  type        = list(string)
  default     = ["dev", "staging", "prod"]
}
