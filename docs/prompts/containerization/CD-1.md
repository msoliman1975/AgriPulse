# CD-1 — Replace ECS proposal with EKS strategy of record

[Shared preamble — see README.md]

## Goal
The strategy doc at `docs/proposals/app-containerization-strategy.md` has already been rewritten by the maintainer to reflect today's decisions (EKS + ArgoCD + CNPG, single AWS account, eu-south-1). This PR's job is **not** to write it — it's to audit that doc against the live repo state and surface any drift before it ships.

## Files to change
- `docs/proposals/app-containerization-strategy.md` — minor corrections only.
- `README.md` — add a one-line pointer to the new strategy doc under a "Deployment" heading. Skip if a similar pointer already exists.

## Tasks
1. Read `docs/proposals/app-containerization-strategy.md` end to end.
2. Verify every concrete claim against the live tree:
   - The Dockerfile descriptions match `backend/Dockerfile`, `frontend/Dockerfile`, `tile-server/Dockerfile`.
   - The Helm chart list matches `infra/helm/*/Chart.yaml`.
   - The ArgoCD AppSet list matches `infra/argocd/appsets/*.yaml`.
   - The platform-values list matches `infra/argocd/platform-values/*.yaml`.
   - The Terraform resource list matches `infra/terraform/*.tf`.
   - The CI job names in §2 match `.github/workflows/ci.yml`.
3. For each drift you find, patch the doc — do **not** rewrite from scratch. Preserve the maintainer's structure and tone.
4. Add a "Deployment" pointer to `README.md` if one doesn't already exist.
5. Do NOT add new sections, change locked decisions, or expand the scope.

## Definition of done
- Doc compiles (`grep -F "BROKEN_REFERENCE"` returns empty if you used that pattern).
- `git diff` is < 50 lines.
- PR description lists every drift found and how it was patched, or states "no drift — doc is accurate as-written."
