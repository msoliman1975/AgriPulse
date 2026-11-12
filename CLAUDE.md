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
5. If the frontend tag changed, also check the Beta designer in prod:

   ```bash
   node scripts/ops/check-prod-beta-designer.cjs
   ```

   It signs in as a platform admin, opens a Beta tree and checks the four
   tabs (Canvas, Targeting, Combinations, Dry run) and the Targeting fields.
   It is read-only: never Save draft or Publish during a check.
   - Credentials: `AGRIPULSE_SMOKE_USER` / `AGRIPULSE_SMOKE_PASSWORD`, from
     the environment only. Never write them to a file, a commit, a PR or a
     scheduled task. If they are not set, use the token mode instead:
     `AGRIPULSE_SMOKE_TOKEN` set to a fresh `claude-automation`
     client-credentials token (it lasts ~15 min). It skips the Keycloak
     login page only; everything after sign-in is checked the same way.
   - Network: `app.`, `api.` and `keycloak.agripulse.cloud`.
   - Do not retry a failed sign-in in a loop: ten wrong passwords lock the
     account.
   On exit 1, report the failing step and the screenshot; do not call the
   deploy done.

## Autonomy

Claude may merge its own PRs, and the promotion PRs that bump the api /
workers / frontend tags in `infra/argocd/overlays/hetzner/values.yaml`, once
required CI is green, following `docs/runbooks/promotion-procedure.md`.

Claude may not, without the owner's explicit approval in the conversation:
force-push or rewrite `main`; disable or skip tests; switch the decision
engine; publish decision trees; hard-delete data.

Production changes go through the API only (identity: the `claude-automation`
Keycloak client, platform admin). Every production action is logged.
