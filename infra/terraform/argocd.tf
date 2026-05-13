# CD-10 â€” ArgoCD bootstrap.
#
# Terraform owns the install of ArgoCD itself (chart + namespace + admin
# password seed). Everything downstream â€” platform operators, services,
# observability â€” is GitOps from `infra/argocd/appsets/bootstrap.yaml` once
# that one manifest is applied (see docs/runbooks/argocd-bootstrap.md).
#
# Chicken-and-egg on the admin password: external-secrets is installed by the
# platform AppSet, which doesn't exist until ArgoCD is up. So for the very
# first boot Terraform generates the password, bcrypts it into the chart
# values, and seeds the plaintext into AWS Secrets Manager. Once ArgoCD has
# reconciled external-secrets, an ExternalSecret can take over the rotation
# story â€” but the bootstrap value is owned here, not in `secrets-manager.tf`'s
# placeholder pattern.

resource "random_password" "argocd_admin" {
  length  = 32
  special = true
  # Avoid characters that need shell-escaping when ops paste the password
  # into a CLI on first login. ArgoCD accepts the full ASCII printable set.
  override_special = "!@#$%^&*()-_=+[]{}"
}

resource "aws_secretsmanager_secret" "argocd_admin" {
  name        = "agripulse/${var.environment}/argocd-admin-password"
  description = "ArgoCD UI admin password. Owned by Terraform until Keycloak SSO lands (CD-13)."
  kms_key_id  = aws_kms_key.agripulse.arn

  tags = merge(local.common_tags, {
    Env     = var.environment
    Purpose = "argocd-admin-password"
  })
}

resource "aws_secretsmanager_secret_version" "argocd_admin" {
  secret_id     = aws_secretsmanager_secret.argocd_admin.id
  secret_string = random_password.argocd_admin.result
}

resource "helm_release" "argocd" {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true

  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.argocd_chart_version

  # Long enough to cover the first-time CRD install on a fresh cluster.
  timeout = 900
  atomic  = false
  wait    = true

  values = [
    file("${path.module}/../argocd/values/argocd-server.yaml"),
  ]

  # `configs.secret.argocdServerAdminPassword` wants a bcrypt hash. Storing
  # plaintext in SM lets operators retrieve it; the chart only ever sees the
  # hash. `argocdServerAdminPasswordMtime` must be a valid RFC3339 timestamp
  # â€” keep it stable across applies so we don't bump the password every run.
  set_sensitive {
    name  = "configs.secret.argocdServerAdminPassword"
    value = bcrypt(random_password.argocd_admin.result)
  }

  set {
    name  = "configs.secret.argocdServerAdminPasswordMtime"
    value = "2026-05-12T00:00:00Z"
  }

  # Ingress hostname is templated into the chart values rather than hard-coded
  # in YAML so we keep one source of truth (locals.argocd_hostname).
  set {
    name  = "server.ingress.hostname"
    value = local.argocd_hostname
  }

  set {
    name  = "server.ingress.tls[0].secretName"
    value = "argocd-server-tls"
  }

  set {
    name  = "server.ingress.tls[0].hosts[0]"
    value = local.argocd_hostname
  }

  # IP allowlist for the ingress. Until Keycloak SSO is in place (CD-13) the
  # UI is locked to maintainer CIDRs. Empty list disables the annotation.
  dynamic "set" {
    for_each = length(var.argocd_admin_allowlist_cidrs) > 0 ? [1] : []
    content {
      name  = "server.ingress.annotations.nginx\\.ingress\\.kubernetes\\.io/whitelist-source-range"
      value = join("\\,", var.argocd_admin_allowlist_cidrs)
    }
  }

  depends_on = [
    module.eks,
    # External Secrets IRSA exists â€” even though the controller itself
    # installs via the platform AppSet, having the role pre-created means the
    # first ExternalSecret to sync after install doesn't race IAM.
    module.iam_role_external_secrets,
  ]

  lifecycle {
    # bcrypt() is non-deterministic; without this the admin password would
    # appear "changed" on every plan even though the underlying random_password
    # is stable.
    ignore_changes = [
      set_sensitive,
    ]
  }
}

output "argocd_hostname" {
  description = "ArgoCD UI hostname. ExternalDNS + cert-manager publish the record once the chart reconciles."
  value       = local.argocd_hostname
}

output "argocd_admin_secret_arn" {
  description = "AWS Secrets Manager ARN of the bootstrap admin password. Retrieve with `aws secretsmanager get-secret-value --secret-id <arn>`."
  value       = aws_secretsmanager_secret.argocd_admin.arn
}
