variable "region" {
  description = "AWS region. ARCHITECTURE.md § 3.2 commits me-south-1 (Bahrain)."
  type        = string
  default     = "me-south-1"
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
  description = "EKS cluster name; defaults to missionagre-<env>."
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
