# AgriPulse: notes for Claude sessions

## Deploying a change to prod

Hetzner is the only live environment; AWS/dev is decommissioned, so there is
no dev deploy to check. Full procedure: `docs/runbooks/promotion-procedure.md`.

1. Merge the feature PR once CI is green. `backend-integration` is
   non-blocking and often stops at its 35-minute cap after the tests finish;
   read its log for the pytest summary rather than its conclusion.
2. Wait for `ci` on the `main` merge commit: the `containers (...)` jobs must
   succeed, since they push the images tagged with the short SHA.
3. Open a PR bumping the api / workers / frontend tags in
   `infra/argocd/overlays/hetzner/values.yaml`. Add a note on each block with
   what changed, what to watch and the rollback tag, following the existing
   notes. Merge it; ArgoCD auto-syncs.
4. If the frontend tag changed, verify prod serves it before reporting done:

   ```bash
   scripts/ops/verify-prod-frontend.sh <frontend-tag>
   ```

   It needs `app.agripulse.cloud` allowed in the session's network. On exit 1,
   report the version prod serves instead; do not call the deploy done.
