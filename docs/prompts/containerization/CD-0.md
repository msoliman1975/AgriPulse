# CD-0 — Pre-flight refactor to unlock parallel CD-1..CD-15 execution

[Shared preamble — see README.md]

## Goal
This is a **zero-behaviour-change refactor** that splits the collision-prone files in `infra/` so that CD-1..CD-15 can be authored in parallel without merge conflicts. Nothing rendered by Helm or planned by Terraform should change. Verified by `helm template` + `terraform plan` producing byte-identical output before and after (modulo file paths in headers).

This PR MUST land alone, before any other CD-N PR. It's a no-op functionally but rearranges the file layout that every later PR will write into.

## Files to change

**Terraform splits**
- `infra/terraform/iam.tf` — leave existing resources in place if they aren't IRSA-specific. Move IRSA roles (if any exist today) into a new `iam-irsa.tf`.
- `infra/terraform/iam-irsa.tf` — new. Empty stub with a one-line comment: `# IRSA roles live in iam-irsa-<concern>.tf — one file per concern to keep PRs collision-free`. No resources. Later PRs add: `iam-irsa-externaldns.tf` (CD-5), `iam-irsa-certmanager.tf` (CD-5), `iam-irsa-s3.tf` (CD-6), `iam-irsa-karpenter.tf` (CD-8), `iam-irsa-externalsecrets.tf` (CD-9), `iam-irsa-github.tf` (CD-11).
- `infra/terraform/outputs.tf` — split by concern:
  - Keep `outputs.tf` as a one-line pointer comment.
  - Create `outputs-network.tf` with the current VPC outputs.
  - Create `outputs-eks.tf` with the current EKS outputs.
  - Create `outputs-kms.tf`, `outputs-s3.tf` if those modules have outputs today.
  - Later PRs add: `outputs-route53.tf` (CD-5), `outputs-iam-irsa.tf` (CD-6 etc.), `outputs-karpenter.tf` (CD-8), `outputs-secretsmanager.tf` (CD-9), `outputs-github.tf` (CD-11).

**Helm shared chart split**
- `infra/helm/shared/templates/postgres-cluster.yaml` — leave the `Cluster` resource here. CD-7 will edit this file (backup wiring).
- `infra/helm/shared/templates/postgres-databases.yaml` — new, empty `{{- /* additional CNPG Database resources live here (Keycloak DB etc.) */ -}}`. CD-13 will populate it.

**ArgoCD overlay restructure** (the highest-leverage split)
- Today `infra/argocd/overlays/{dev,staging,production}/values.yaml` is a single file per env that overrides ALL charts. Almost every CD-N PR edits it → guaranteed conflicts.
- New layout: per-chart override file under a `charts/` subdirectory.
  ```
  infra/argocd/overlays/
    dev/
      global.yaml          (was values.yaml; keeps cross-chart globals like image tags, env name)
      charts/
        api.yaml
        workers.yaml
        frontend.yaml
        tile-server.yaml
        keycloak.yaml
        shared.yaml        (CNPG cluster sizing etc.)
    staging/      same shape
    production/   same shape
  ```
- Move current per-chart sections from `values.yaml` into the appropriate `charts/<chart>.yaml`. Keep cross-chart concerns (image tags, `global.env`) in `global.yaml`.
- Update `infra/argocd/appsets/services.yaml` so each Application's `source.helm.valueFiles` references both `overlays/<env>/global.yaml` AND `overlays/<env>/charts/<chart>.yaml`. The first one stays a shared edit point for CD-12's image-tag bump fix.

**ArgoCD AppSets**
- Leave `infra/argocd/appsets/platform.yaml` as-is. Don't pre-split — only CD-5 and CD-8 touch it, low conflict risk. If you want to over-engineer: split per-component into `appsets/platform/<component>.yaml` and update the bootstrap AppSet generator. **Skip unless trivial.**

**Workflow conflict** (single file, two PRs)
- `.github/workflows/ci.yml` is edited by both CD-11 and CD-12. Don't pre-split — CD-11 lands first in Wave 2, CD-12 in Wave 5; serial by schedule.

## Tasks
1. Apply the splits above. Use `git mv` where the file is renamed (not split) so blame is preserved.
2. Run `terraform fmt -recursive infra/terraform/` and `terraform validate` from `infra/terraform/`.
3. Run `helm lint infra/helm/shared` and `helm template shared infra/helm/shared` — compare to pre-refactor output. Should be identical.
4. Run `helm template` for the api/workers/frontend/tile-server charts with each env overlay (loading both `global.yaml` and the per-chart override) — compare to pre-refactor (which loaded `values.yaml`). Should be byte-identical modulo any whitespace differences.
5. If any rendered diff appears, the split is wrong — fix the values-file plumbing in the AppSet.
6. Update `infra/argocd/appsets/services.yaml` so Helm gets both override files in the right order (global first, chart-specific second so it can override globals).
7. Add a short note to `docs/proposals/app-containerization-strategy.md` § 4 noting that CD-0 (this PR) is the prerequisite — one line.

## Out of scope
- Don't add any new resources, IRSA roles, S3 buckets, NodePools, secrets, ingresses, or hostnames. **Zero new functionality.**
- Don't change image tags, replica counts, resource requests, or any value visible in rendered Helm output.
- Don't migrate the Keycloak chart's `realm-configmap.yaml` or any other file not listed above.
- Don't touch `.github/workflows/*` — workflow conflicts are handled by schedule, not by splits.
- Don't touch `infra/argocd/platform-values/*.yaml` — these are per-platform-component and already disjoint.

## Definition of done
- `git diff main --stat` shows only file moves / additions of empty stubs / re-homed values blocks. No semantic changes.
- `helm template` for every chart against every env overlay produces output equivalent to pre-refactor.
- `terraform plan` shows zero diff (no resources added, modified, or destroyed).
- CI (the existing `ci.yml`) passes.
- PR description explicitly states "no-op refactor — verified byte-identical Helm + Terraform output."
- Reviewer can read the diff in <10 minutes.
