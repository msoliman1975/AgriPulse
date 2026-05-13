# AgriPulse â€” ArgoCD

GitOps surface for the platform. Three environments â€” `dev`, `staging`,
`production` â€” each rendered from this folder.

## Layout

```
appsets/
  bootstrap.yaml             AppOfApps that creates the ApplicationSets below.
  services.yaml              Generates Applications for our service charts
                             (api, workers, tile-server, frontend, keycloak,
                             shared) per environment.
  platform.yaml              Generates Applications for cluster operators
                             (cert-manager, external-secrets, cloudnativepg,
                             ingress-nginx). Points at upstream HelmRepo URLs.
  observability.yaml         kube-prometheus-stack, Loki, Tempo, GlitchTip.

overlays/
  dev/values.yaml            Auto-sync, looser policies, dev host names.
  staging/values.yaml        Auto-sync with smoke-test gate.
  production/values.yaml     Manual sync, prune disabled, restricted hosts.
```

## Bootstrap

After EKS is provisioned (Terraform in `infra/terraform/`), install ArgoCD
via the upstream chart, then apply `appsets/bootstrap.yaml`:

```bash
kubectl apply -n argocd -f infra/argocd/appsets/bootstrap.yaml
```

This creates the four ApplicationSets which fan out into Applications, one
per `(chart Ã— environment)` cell. Each Application has:

- `syncPolicy.automated` for `dev`; `automated.prune: false` for `production`.
- `syncOptions: ["ServerSideApply=true", "CreateNamespace=true"]`.
- `revision: HEAD` of the same repo so deployment tracks `main`.

## Per-env overrides

Each per-env `values.yaml` is consumed by ArgoCD via the
`spec.source.helm.valueFiles` list. Service charts get:
- shared platform values (`overlays/<env>/values.yaml`)
- chart-local defaults (`infra/helm/<chart>/values.yaml`)

## Sync policy

| Env         | Auto-sync | Auto-prune | Self-heal |
|-------------|-----------|------------|-----------|
| dev         | yes       | yes        | yes       |
| staging     | yes       | no         | yes       |
| production  | no        | no         | yes       |
