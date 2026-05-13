# Runbook: promotion procedure (dev â†’ staging â†’ prod)

Promotions are gated by human PRs that bump image tags in the per-env
overlay. There is no automated promotion in V1 â€” that's the feature,
not a gap. Manual gates are what keep prod's blast radius bounded.

## The three overlays

| Overlay | Auto-bumped by | Approvals to merge | Soak target |
|---|---|---|---|
| `overlays/dev/values.yaml`        | `.github/workflows/argocd-sync.yml` on every push to `main` | auto-merge after CI green | n/a â€” dev is continuous |
| `overlays/staging/values.yaml`    | hand-authored PR                                          | 1 CODEOWNER             | 24â€“72h before promote   |
| `overlays/production/values.yaml` | hand-authored PR                                          | 2 CODEOWNERS            | n/a â€” prod is the floor |

`argocd-sync.yml` only touches the dev overlay â€” staging and prod live
on a strict pull model.

## Dev â†’ staging

1. Pick the dev image SHAs you want to promote â€” usually the latest
   set in `overlays/dev/values.yaml` after 24h of clean dev runs.
2. Open a PR titled `chore(staging): bump images to <short-sha>`
   updating the four `global.images.*.tag` keys in
   `overlays/staging/values.yaml`.
3. One CODEOWNER approval. CI must be green (helm-template, lint,
   security scan).
4. Merge. ArgoCD syncs staging within ~3 minutes.
5. Watch:
   - `argocd app wait -l agripulse.cloud/env=staging --health --timeout 600`
   - GlitchTip for new errors
   - Grafana FastAPI dashboard for elevated 5xx or latency
6. Soak. 24h for routine code-only changes; 72h when the change touches
   migrations, auth, or imagery pipeline.

If staging breaks, revert the PR. Staging auto-syncs the rollback.

## Staging â†’ prod

1. Open a PR titled `chore(prod): bump images to <short-sha>` updating
   `overlays/production/values.yaml`. Use the **same four SHAs** that
   soaked successfully in staging â€” never re-build for prod.
2. **Two CODEOWNER approvals.** The second reviewer's job is to confirm
   staging actually soaked (check GlitchTip + Grafana history for the
   last 24h, not just "looks fine right now").
3. Merge.
4. Prod is not auto-sync â€” follow `docs/runbooks/first-prod-deploy.md`
   from Â§ 4 (the first-time runbook collapses to "sync the apps and
   smoke-test"; you've already done the secrets seed and DNS setup).

## Hotfix path (sev-1 only)

When a sev-1 in prod cannot wait for the staging soak:

1. Cut a hotfix branch off the **last green prod SHA**, not `main`.
2. Land the fix on the hotfix branch with the minimum delta â€” no
   refactors, no unrelated bumps.
3. Get one CODEOWNER + the on-call engineer's sign-off.
4. Bump the prod overlay directly. Skipping staging is the explicit
   gate that justifies the second sign-off.
5. After the fix is in prod, forward-port the change to `main` so dev
   and the next staging promote do not regress.

Document every hotfix in the deploys channel with the sev rating and
the on-call sign-off. The audit trail is the only reason this path is
allowed to exist.
