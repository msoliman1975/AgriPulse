# Parallel execution plan for CD-0 â€¦ CD-15

Strategy doc: `docs/proposals/app-containerization-strategy.md`. Prompts: `CD-N.md` in this directory.

This file lays out how to **author the 15 PRs in 4â€“5 wall-clock days instead of ~15**, by running multiple Claude Code sessions concurrently across git worktrees.

---

## 1. Why parallelism is possible

Looking at the actual dependency graph (logical prerequisites only):

```
CD-1  CD-2  CD-3  CD-4         â† no deps on anything
CD-5  CD-6  CD-8  CD-11        â† no deps on each other
CD-7  â† CD-6                    (S3 buckets + IRSA)
CD-9  â† CD-6                    (IRSA pattern; soft dep)
CD-10 â† CD-5, CD-9              (hostname + admin secret)
CD-12 â† (none, CI-only)
CD-13 â† CD-7                    (CNPG operator must be backup-enabled)
CD-15 â† (none)
CD-14 â† CD-13                   (Keycloak hostnames in prod overlay)
```

Logical deps are sparse. The real blocker to parallelism is **file-collision** in a handful of shared files (`outputs.tf`, `iam.tf`, overlay `values.yaml`, `postgres-cluster.yaml`). That's what **CD-0** solves.

---

## 2. The waves

| Wave | PRs (run in parallel) | Hard deps | Calendar | Notes |
| --- | --- | --- | --- | --- |
| **0** | CD-0 | â€” | Day 1 AM (2h) | Pre-flight file-split refactor. Must land alone. |
| **1** | CD-1, CD-2, CD-3, CD-4 | CD-0 | Day 1 PM â†’ Day 2 | Local + observability. No AWS touched. |
| **2** | CD-5, CD-6, CD-8, CD-11 | CD-0 | Day 3 â†’ Day 4 | Foundational AWS. Author parallel, **serialise `terraform apply` in merge order CD-5 â†’ CD-6 â†’ CD-11 â†’ CD-8**. |
| **3** | CD-7, CD-9 | CD-6 | Day 5 | CNPG backup + External Secrets. |
| **4** | CD-10 (solo) | CD-5, CD-9 | Day 6 | ArgoCD bootstrap. High-impact, single PR, careful review. |
| **5** | CD-12, CD-13, CD-15 | CD-10 (soft); CD-13 needs CD-7 | Day 7â€“8 | Argocd-sync fix + Keycloak prod + cost guardrails. |
| **6** | CD-14 (solo) | CD-13 | Day 9 | Production overlay finalisation + runbooks. |

**Total: ~9 working days vs ~15 serial.** The biggest compression is in Waves 1, 2, and 5 (4Ã—, 4Ã—, 3Ã— respectively).

---

## 3. Execution mechanics â€” running 4 Claude sessions in parallel

### Setup (once)
```powershell
# From the repo root, create one worktree per parallel PR.
# Worktrees share the .git database but have independent working trees + branches.
git worktree add ../agripulse-cd-1 cd-1
git worktree add ../agripulse-cd-2 cd-2
git worktree add ../agripulse-cd-3 cd-3
git worktree add ../agripulse-cd-4 cd-4
```

### Per-wave
1. Open **N Claude Code sessions**, one per worktree (just `cd` into the worktree before launching `claude`).
2. In each session, paste the corresponding `docs/prompts/containerization/CD-N.md` body as the first message.
3. Let them run independently. Each is ~1â€“3 hours of focused work.
4. As each PR opens, review **in the wave's prescribed merge order** (see Â§2 notes).
5. After each merge to `main`, in every other live worktree: `git fetch && git rebase origin/main`. CD-0 makes this painless because no file is touched by two PRs in the same wave.
6. When the wave is done, prune worktrees: `git worktree remove ../agripulse-cd-N`.

### Tip â€” running Claude sessions truly in parallel
Each Claude Code session is independent. You can leave one running in a terminal, switch to another worktree's terminal, and launch a second session. They don't share context, which is exactly what you want â€” each one stays scoped to its single CD-N prompt.

---

## 4. Conflict-zone map (after CD-0 lands)

The table below is what's left after CD-0 splits the collision files. If a future PR violates this, reject the PR and ask for a per-concern file.

| File | Owned by | Edited by |
| --- | --- | --- |
| `infra/terraform/iam-irsa-externaldns.tf` | CD-5 | CD-5 |
| `infra/terraform/iam-irsa-certmanager.tf` | CD-5 | CD-5 |
| `infra/terraform/iam-irsa-s3.tf` | CD-6 | CD-6 |
| `infra/terraform/iam-irsa-karpenter.tf` | CD-8 | CD-8 |
| `infra/terraform/iam-irsa-externalsecrets.tf` | CD-9 | CD-9 |
| `infra/terraform/iam-irsa-github.tf` | CD-11 | CD-11 |
| `infra/terraform/outputs-route53.tf` | CD-5 | CD-5 |
| `infra/terraform/outputs-s3.tf` | CD-6 | CD-6, CD-7 (read-only ref) |
| `infra/terraform/outputs-karpenter.tf` | CD-8 | CD-8 |
| `infra/terraform/outputs-secretsmanager.tf` | CD-9 | CD-9 |
| `infra/terraform/outputs-github.tf` | CD-11 | CD-11 |
| `infra/helm/shared/templates/postgres-cluster.yaml` | CD-7 | CD-7 only |
| `infra/helm/shared/templates/postgres-databases.yaml` | CD-13 | CD-13 only |
| `infra/argocd/overlays/<env>/charts/<chart>.yaml` | per-chart PR | one PR per chart per env |
| `infra/argocd/overlays/<env>/global.yaml` | CD-12 (tag-bump only) | All â€” but only the `images.*.tag` lines, edited by CI bot |
| `.github/workflows/ci.yml` | CD-11 then CD-12 | Serial â€” CD-12 lands after CD-11 in Wave 5 |
| `infra/argocd/appsets/platform.yaml` | CD-5, CD-8 | Same wave â€” merge CD-5 first |

The two remaining unavoidable serial points: **Wave 2 `terraform apply`** (one state, one applier) and **CI workflow file** (single file edited by CD-11 then CD-12, but they're in different waves so it's free).

---

## 5. Critical-path callouts

- **Wave 2 Terraform apply order**: `CD-5 â†’ CD-6 â†’ CD-11 â†’ CD-8`. Why this order: DNS first (CD-5 lets ExternalDNS find its zone before anything else needs it), then S3 + IRSA (CD-6, unblocks CD-7), then OIDC role (CD-11, switches CI from local-creds to OIDC), then Karpenter (CD-8, last because it depends on subnet/SG tags being stable). Each apply is ~3â€“8 min.
- **Wave 4 must be solo**: CD-10 bootstraps ArgoCD itself. Don't merge anything else into `main` while CD-10 is in flight. After it lands, the cluster is GitOps-managed and every subsequent PR's effect is visible in the ArgoCD UI.
- **Wave 5 ordering**: Land CD-12 first (it's CI-only and tiny). Then CD-13 and CD-15 can land in either order â€” they touch disjoint files.

---

## 6. Reviewer bottleneck (the real constraint)

With a solo maintainer + Claude:
- **Author wall-clock**: ~3h per PR Ã— 15 PRs = 45h serial; parallelism drops it to ~25h wall-clock across 4â€“5 sessions.
- **Review wall-clock**: ~30 min per PR Ã— 15 PRs = 7.5h. Cannot be parallelised by one person.
- **Net critical path is review-bound, not author-bound.** Plan for review sessions at end-of-wave: 4 PRs Ã— 30 min = 2h focused review block.

Mitigations:
- Author tight diffs (<200 lines). Each prompt enforces this via explicit out-of-scope sections.
- Use CODEOWNERS to fan out reviews if a second reviewer exists.
- For low-risk PRs (CD-1, CD-12, CD-15) â€” accept on a skim. Reserve deep review for CD-7, CD-8, CD-10, CD-13.

---

## 7. Failure modes + recovery

| Scenario | Recovery |
| --- | --- |
| Two Wave-2 PRs add the same IRSA resource name | Reject the later PR; rename. CD-0's file-per-concern split makes this rare. |
| `terraform apply` partial failure mid-wave | State is consistent; re-run apply after fixing. Terraform is idempotent. |
| Wave-3 PR lands but ArgoCD isn't bootstrapped yet (Wave 4 hasn't happened) | Expected. The cluster runs in `kubectl apply` mode until CD-10 lands. ~1 day of drift, all in dev. |
| Two parallel Claude sessions accidentally over-reach into each other's scope | Kill the offender, re-run with explicit `Do not modify <path>` line appended to the CD-N prompt. |
| Reviewer fatigue â†’ PRs pile up | Drop to 2-wide parallelism in subsequent waves; calendar slips by 2â€“3 days. Still faster than serial. |
| A wave's apply breaks production-shaped dev | Roll back the offending PR via revert PR; ArgoCD syncs to previous SHA within minutes. |

---

## 8. Calendar at a glance

```
Day 1: CD-0  | Wave 1 author (CD-1, CD-2, CD-3, CD-4)
Day 2:       | Wave 1 review + merge
Day 3: Wave 2 author (CD-5, CD-6, CD-8, CD-11)
Day 4: Wave 2 review + serial terraform apply
Day 5: Wave 3 (CD-7, CD-9) author + review + merge
Day 6: CD-10 (Wave 4) â€” solo PR, careful
Day 7: Wave 5 author (CD-12, CD-13, CD-15)
Day 8: Wave 5 review + merge
Day 9: CD-14 (Wave 6) â€” final
```

**Decision points along the way**:
- End of Wave 1: confirm the local prod-shaped compose runs cleanly. Don't go further until it does.
- End of Wave 2: confirm `terraform apply` succeeds for all four. Confirm `argocd.agripulse.cloud` would resolve (DNS up, cert pending).
- End of Wave 4: ArgoCD UI accessible. All AppSets Synced.
- End of Wave 6: `https://api.agripulse.cloud/health` returns 200 in prod.
