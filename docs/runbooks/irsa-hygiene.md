# IRSA hygiene

## What this runbook covers

Two ways a pod can talk to AWS in our cluster, and how to make sure
neither one breaks silently:

1. **Service-Account-scoped IRSA** — the SA has an
   `eks.amazonaws.com/role-arn` annotation, the pod ends up with a
   web-identity token, and the role grants exactly the perms that pod
   needs.
2. **Node-role inheritance** — no IRSA, the pod inherits the node's
   instance-profile role. Usually wrong for app workloads (too much
   blast radius, no per-app audit).

`scripts/lint_irsa.py` runs in CI and fails the build when:

- A Helm chart values.yaml has `serviceAccount.create: true` but no
  `eks.amazonaws.com/role-arn` annotation **and** no opt-out marker.
- An EKS managed add-on in `infra/terraform/eks.tf` is in the
  known-IRSA-required set (e.g. `aws-ebs-csi-driver`) and is missing
  `service_account_role_arn`. (Backstory: the EBS CSI add-on hangs in
  `CREATING` indefinitely without this — see the
  `project_eks_addon_irsa` memory.)

## The two opt-out markers (chart values.yaml only)

Add an HTML-style comment line inside the `serviceAccount:` block:

| Marker                            | Means                                                                              |
| --------------------------------- | ---------------------------------------------------------------------------------- |
| `# irsa: not-required`            | This pod genuinely has no AWS calls. Node-role inheritance is fine.                |
| `# irsa: required-from-overlay`   | This pod needs IRSA, and the ARN is set per-env in `infra/argocd/overlays/<env>/values.yaml`. |

Example:

```yaml
serviceAccount:
  # irsa: required-from-overlay
  create: true
  name: ""
  annotations: {}
```

The lint only requires the marker text to appear inside the
`serviceAccount:` block. Inline placement on the same line as a key is
fine — readability wins.

### What is *not* an opt-out

- `serviceAccount.create: false` (the chart uses an externally-managed
  SA — out of scope for this lint).
- Comments outside the `serviceAccount:` block.
- Comments using `// irsa: …` or other syntax. Must be `#`.

## Adding a new chart

Three-question decision tree when scaffolding a new chart:

1. **Does it call AWS APIs at runtime?** (S3, SM, KMS, SQS, etc.)
   - No → `# irsa: not-required` and move on.
   - Yes → continue.
2. **Will the IRSA ARN be the same across dev/staging/prod?**
   - Yes (rare; usually only for global services like cert-manager talking to Route53) → set the annotation in the chart values.yaml directly.
   - No (typical — per-env AWS accounts or per-env role naming) → `# irsa: required-from-overlay` and add the annotation in `infra/argocd/overlays/<env>/values.yaml`.
3. **Is there a matching IRSA role in `infra/terraform/iam-irsa.tf`?**
   - If not, add it there first; `terraform apply` to mint the role; copy the ARN into the overlay.

## Adding a new EKS managed add-on

If the add-on ships a controller pod that talks to AWS (CSI drivers,
load-balancer-controller, etc.), add it to `ADDONS_REQUIRING_IRSA` in
`scripts/lint_irsa.py` before opening the PR. The lint then enforces
that the corresponding `cluster_addons.<name>.service_account_role_arn`
is set in `eks.tf`.

For controller-free add-ons (`coredns`, `kube-proxy`, plain `vpc-cni`),
skip — IRSA is not relevant.

## Recovery

### Lint failed in CI

The error message includes the offending file and the missing piece.
Fix forward and push.

If the lint is fundamentally wrong (e.g. flagging something that
legitimately doesn't need IRSA), add the opt-out marker. **Don't
silence the lint** by editing the script unless you're also adjusting
the `ADDONS_REQUIRING_IRSA` set as part of a real add-on change.

### Add-on stuck in CREATING

Confirm with:

```powershell
aws eks describe-addon --cluster-name agripulse-dev --addon-name aws-ebs-csi-driver --region eu-south-1
```

Look at `status` and `health.issues`. If `health.issues[*].code` is
`InsufficientPermissions` or the controller pod is OOM-restarting on
`AccessDenied`, the IRSA wiring is missing. Add
`service_account_role_arn` in `eks.tf`, `terraform apply`, then:

```powershell
aws eks delete-addon --cluster-name agripulse-dev --addon-name aws-ebs-csi-driver --region eu-south-1
# wait until it's gone, then re-apply terraform — the addon block recreates it.
```

(Full recipe in `project_eks_addon_irsa` memory.)

### Pod is using the wrong role at runtime

`kubectl exec` into the pod and:

```sh
aws sts get-caller-identity
```

If the ARN ends with `:assumed-role/<node-role>/…`, the SA isn't
IRSA-bound. Check the SA annotation, then check the pod spec actually
mounts the projected token volume — both should be present
automatically when the annotation is set, but a chart that bypasses
the standard ServiceAccount template can miss them.
