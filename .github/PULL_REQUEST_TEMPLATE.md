<!-- Thanks for the PR. Keep it small, focused, and behind a feature branch. -->

## What changed
<!-- One paragraph. Refer to issues with #N or fixes #N. -->

## Why
<!-- The motivation. If this is driven by ARCHITECTURE.md or data_model.md,
     link to the section. -->

## How to verify
<!-- Steps a reviewer can run locally. Include commands and expected output. -->

- [ ]

## Architectural impact
<!-- Tick all that apply. Anything new in the first three needs an ADR
     under docs/decisions/ before merge. -->

- [ ] Adds a new module
- [ ] Adds a new external dependency (library, service, infra component)
- [ ] Changes a binding decision in `docs/ARCHITECTURE.md`
- [ ] Changes a table or column in `docs/data_model.md`
- [ ] None of the above

## Bootstrap impact
<!-- Tick everything that applies. Each item has a non-zero chance of
     breaking a fresh `terraform apply` + ArgoCD sync. The
     feature-readiness runbook explains what each one requires.
     See: docs/runbooks/feature-readiness.md -->

- [ ] Adds or renames an env var read by the api / workers / tile-server
- [ ] Adds or renames a secret (AWS Secrets Manager, ExternalSecret, k8s Secret)
- [ ] Adds or modifies a database migration (`public` or `tenant`)
- [ ] Adds a new ServiceAccount or changes IRSA wiring on an existing one
- [ ] Adds a new EKS managed add-on or changes `cluster_addons` in `eks.tf`
- [ ] Adds a new container image or changes a Dockerfile base / build steps
- [ ] Adds a new Helm chart or top-level change to `infra/argocd/overlays/*`
- [ ] Touches the cluster-bootstrap path (Keycloak realm import, seed secrets, first-tenant flow)
- [ ] None of the above

## Checklist

- [ ] Tests pass locally (`pre-commit run --all-files`, `pytest`, `pnpm test` as relevant)
- [ ] `python scripts/lint_irsa.py` clean (if any IRSA / addon item above is ticked)
- [ ] Migration is backward-compatible with the previous api image (if a migration is added — see `docs/runbooks/migrations.md`)
- [ ] Linked any related issue
- [ ] No secrets, credentials, or PII committed
- [ ] CODEOWNERS reviewer requested
