# CD-3 — Alembic migrations as an ArgoCD PreSync Job

[Shared preamble — see README.md]

## Goal
Today, `alembic upgrade head` is a manual step after deploying. This PR makes it an ArgoCD pre-sync Job so every ArgoCD sync runs migrations before rolling new Deployments. If the Job fails, the sync fails and the Deployments are not touched — the old version keeps serving.

## Files to change
- `infra/helm/api/templates/migrations-job.yaml` — new.
- `infra/helm/api/values.yaml` — new `migrations:` block (enabled, image, command, resources).
- `infra/argocd/overlays/dev/values.yaml` — enable migrations under the api chart values pass-through.
- `docs/runbooks/failed-migration-recovery.md` — new, ~30 lines.

## Tasks
1. Create the Job manifest with these annotations:
   - `argocd.argoproj.io/hook: PreSync`
   - `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation`
   - `argocd.argoproj.io/sync-wave: "-10"` (well before any Deployment)
2. The Job uses the **same image** as the api Deployment (image tag flows through via the chart's `image` block — DO NOT pin a different tag, that breaks atomicity).
3. Command: `["alembic", "-c", "migrations/alembic.ini", "upgrade", "head"]`. Use `workingDir: /app` (the image's `APP_HOME`).
4. Env: pull the same `ExternalSecret` data as the api Deployment for DB credentials. Reference the same `envFrom` block.
5. ServiceAccount: reuse the api ServiceAccount (same IRSA needs).
6. `backoffLimit: 1`, `activeDeadlineSeconds: 600`.
7. Wrap the manifest in `{{- if .Values.migrations.enabled }}` so users can disable it for charts where they don't want it (e.g., test renders).
8. Runbook covers:
   - How to check Job logs (`kubectl logs job/<name>-migrate-<sha> -n <ns>`).
   - How to skip a migration (set `migrations.enabled: false`, sync, run alembic manually, re-enable).
   - How to roll back a migration (alembic `downgrade -1` from a debug pod).
   - The "stuck PreSync" failure mode — what to delete to retry.

## Out of scope
- Don't add migration logic to the workers chart. Workers don't run migrations.
- Don't change Alembic config or migration files.
- Don't add a separate ServiceAccount.

## Definition of done
- `helm template api infra/helm/api` produces a Job with the four annotations above.
- A manual `kubectl apply` of the rendered Job against a dev cluster runs migrations successfully (or fails loudly).
- Runbook reviewed and committed.
