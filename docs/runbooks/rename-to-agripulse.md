# Rename — MissionAgre → AgriPulse

One-shot rename runbook. Run **before** CD-13/CD-14 ship so the Keycloak
realm, K8s namespace, IAM resource names, and image paths are correct on
their first deploy.

## Scope of the rename

| Current | New | Notes |
|---|---|---|
| `MissionAgre` / `missionagre` / `MISSIONAGRE` | `AgriPulse` / `agripulse` / `AGRIPULSE` | Brand name in all casings |
| `Agri.Pulse` | `AgriPulse` | Unify the dotted variant found in a few translation strings |
| `missionagre.io` | `agripulse.cloud` | Synthetic namespace strings: ProblemDetails URIs, K8s annotation prefix (`agripulse.cloud/role`) |
| `missionagre.local` | `agripulse.local` | Local-only dev hostnames — kept on `.local` per RFC 6762, not collapsed into the public domain |

The public/branded domain is **`agripulse.cloud`**. Per-env subdomains
(introduced by CD-13/CD-14) will look like `dev.agripulse.cloud`,
`staging.agripulse.cloud`, `keycloak.agripulse.cloud`, etc.

## Pre-flight

1. **Coordinate.** Any session working on CD-12/13/15 must pause, commit,
   and push their branch. Do not rebase yet — wait for the rename PR.
2. **Clean working tree.**
   ```powershell
   git status
   git stash push -u -m "pre-rename safety"   # only if needed
   ```
3. **Branch from main.**
   ```powershell
   git checkout main
   git pull
   git checkout -b chore/rename-agripulse
   ```
4. **Confirm no extra stashes you care about.** `git stash list` —
   anything labeled "WIP" for in-flight CD work should already be on a
   branch. Stale stashes can stay; they're inert until popped.

## Step 1 — content rename (scripted)

```powershell
# Dry-run first; eyeball the file list
pwsh -File scripts/rename-to-agripulse.ps1 -DryRun

# If happy, run for real
pwsh -File scripts/rename-to-agripulse.ps1
```

Expected: ~200 files, ~1000+ substitutions.

## Step 2 — file renames

The script edits content only. File renames are manual:

```powershell
git mv infra/dev/keycloak/missionagre-realm.json infra/dev/keycloak/agripulse-realm.json
git mv infra/helm/keycloak/files/missionagre-realm.json infra/helm/keycloak/files/agripulse-realm.json

# Sanity — should return nothing
Get-ChildItem -Recurse | Where-Object { $_.Name -match 'missionagre' } | Select-Object FullName
```

## Step 3 — regenerate lockfiles

The script skipped these on purpose; regenerate so package names line up:

```powershell
# Backend (uv)
Set-Location backend
uv lock
Set-Location ..

# Frontend (npm/pnpm — whichever you use)
Set-Location frontend
npm install      # or: pnpm install
Set-Location ..
```

## Step 4 — load-bearing manual review

The script handles strings mechanically, but these spots need a human
look. Open each and verify:

- [ ] **`backend/pyproject.toml`** — package name `agripulse-backend`.
- [ ] **`frontend/package.json`** — name `agripulse-frontend`.
- [ ] **`infra/dev/keycloak/agripulse-realm.json`** and
      **`infra/helm/keycloak/files/agripulse-realm.json`** — confirm
      `"realm": "agripulse"`, plus any embedded `redirectUris` /
      `webOrigins`.
- [ ] **`infra/helm/keycloak/templates/realm-configmap.yaml`** —
      ConfigMap name + the `files/` path point at the renamed file.
- [ ] **`infra/terraform/github-oidc.tf`** — `default = "AgriPulse"`
      for the OIDC repo subject. **Must match the new GitHub repo name
      exactly** (case-sensitive in OIDC).
- [ ] **`infra/terraform/iam.tf`, `kms.tf`, `iam-irsa.tf`** — HCL
      identifiers like `aws_kms_key.agripulse`. Run `terraform validate`
      below to catch any miss.
- [ ] **`backend/app/modules/imagery/tasks.py`** — STAC asset property
      keys (`agripulse:scene_id`, `agripulse:aoi_hash`). If dev pgstac
      has data, run the migration SQL in §6 below or wipe and re-ingest.
- [ ] **`backend/app/modules/**/errors.py`, `router.py`** — confirm the
      `https://agripulse.cloud/problems/...` URIs look sane.
- [ ] **`backend/.env.example`, `frontend/.env.example`,
      `infra/dev/.env.example`** — env var defaults. Update your local
      uncommitted `.env` files yourself.
- [ ] **`infra/dev/compose.yaml`** — service names, env vars, volumes,
      networks. `docker compose -f infra/dev/compose.yaml config` to
      spot-check.
- [ ] **`scripts/setup-branch-protection.sh`** — references the GitHub
      repo name.
- [ ] **`docs/architecture.html`** — pre-rendered HTML; eyeball it.

## Step 5 — verification

```powershell
# Should return zero hits
git grep -i 'missionagre'
git grep 'Agri\.Pulse'

# Backend
Set-Location backend
uv lock
uv run pytest -x tests/unit
Set-Location ..

# Frontend
Set-Location frontend
npm install
npm run typecheck
npm run lint
Set-Location ..

# Terraform
Set-Location infra/terraform
terraform fmt -check
terraform validate
Set-Location ../..

# Helm renders for each env overlay
helm template infra/helm/shared    -f infra/argocd/overlays/dev/values.yaml | Out-Null
helm template infra/helm/api       -f infra/argocd/overlays/dev/values.yaml | Out-Null
helm template infra/helm/frontend  -f infra/argocd/overlays/dev/values.yaml | Out-Null
helm template infra/helm/workers   -f infra/argocd/overlays/dev/values.yaml | Out-Null
helm template infra/helm/keycloak  -f infra/argocd/overlays/dev/values.yaml | Out-Null

# K8s annotation prefix should now be agripulse.cloud/role everywhere
git grep 'missionagre\.io/role'   # expect zero
git grep 'agripulse\.cloud/role'  # expect the moved references
```

## Step 6 — pgstac data migration (only if dev DB has ingested items)

If your dev pgstac already has imagery items written with the old
namespace prefix:

```sql
-- Spot-check first
SELECT id, properties ? 'missionagre:scene_id' AS has_old_key
FROM pgstac.items
WHERE properties ? 'missionagre:scene_id'
LIMIT 10;

-- Migrate scene_id
UPDATE pgstac.items
SET properties = (properties - 'missionagre:scene_id')
              || jsonb_build_object('agripulse:scene_id', properties->'missionagre:scene_id')
WHERE properties ? 'missionagre:scene_id';

-- Migrate aoi_hash
UPDATE pgstac.items
SET properties = (properties - 'missionagre:aoi_hash')
              || jsonb_build_object('agripulse:aoi_hash', properties->'missionagre:aoi_hash')
WHERE properties ? 'missionagre:aoi_hash';
```

If the dev DB is disposable, drop the pgstac volume and re-ingest from
scratch — simpler.

## Step 7 — open the PR

```powershell
git add -A
git commit -m "chore: rename MissionAgre -> AgriPulse"
git push -u origin chore/rename-agripulse
gh pr create --title "chore: rename MissionAgre -> AgriPulse" --body "Pure mechanical rename. See docs/runbooks/rename-to-agripulse.md for the load-bearing manual fixes that accompanied the scripted pass."
```

Keep the PR focused — no other changes mixed in — so reviewers can
verify it's pure rename.

## Step 8 — GitHub-side actions (after the PR merges)

1. **Rename the repo on GitHub:** Settings → General → Repository name →
   `AgriPulse`. GitHub auto-creates a 301 redirect from the old URL.
2. **Update local remotes** (everyone with a clone):
   ```powershell
   git remote set-url origin https://github.com/msoliman1975/AgriPulse.git
   ```
3. **OIDC trust policy:** the trust subject in
   `infra/terraform/github-oidc.tf` now references `AgriPulse`. Since
   Terraform has not been applied yet, this is automatic on first
   apply — just don't apply the old state.
4. **Container registry:** legacy `ghcr.io/msoliman1975/missionagre/*`
   packages can be left to age out or deleted from the GitHub Packages
   UI once the new images push.

## Step 9 — other sessions rebase

Branches with in-flight work (CD-12/13/15) rebase onto post-rename
`main`:

```powershell
git fetch origin
git checkout <branch>
git rebase origin/main
# Conflicts will be near-100% on touched files. For pure rename hunks
# accept "theirs" (origin/main); for your branch's logic changes,
# keep "ours" and replay the rename strings by hand.
```

## Why now and not later

- Terraform has not been applied → no KMS/IAM/S3 resources to recreate.
- ArgoCD has not bootstrapped a real cluster → no in-cluster state to
  migrate.
- Keycloak prod realm (CD-13) has not shipped → no user accounts to
  re-import, no JWT-issuer migration.
- No external API consumers → ProblemDetails URIs and STAC namespace
  prefixes are free to change.
- First prod deploy (CD-14) hasn't run → the production overlay can be
  born with the right name.

Doing this after CD-13 / CD-14 ship would cost days of state migration
instead of an afternoon of scripted edits.
