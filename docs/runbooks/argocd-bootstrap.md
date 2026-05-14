# Runbook: ArgoCD bootstrap (CD-10)

Terraform installs ArgoCD itself. ArgoCD then installs everything else via
the AppSets in `infra/argocd/appsets/`. After this runbook, the workflow is:
push to `main` â†’ ArgoCD syncs.

## 1. First-time install

```bash
cd infra/terraform
terraform init -backend-config=...   # see infra/terraform/README.md
terraform apply
```

The apply produces an `argocd-server` Deployment plus its companion pods.
Verify:

```bash
aws eks update-kubeconfig --region eu-south-1 --name agripulse-dev
kubectl get pods -n argocd
# argocd-application-controller-*  Running
# argocd-applicationset-controller-* Running
# argocd-repo-server-*             Running (x2)
# argocd-server-*                  Running (x2)
# argocd-redis-*                   Running
```

## 2. Apply the bootstrap AppSet (one-time)

This is the only `kubectl apply` in the entire GitOps lifecycle.

```bash
kubectl apply -f infra/argocd/appsets/bootstrap.yaml
```

The AppOfApps creates the three child ApplicationSets (`platform`,
`services`, `observability`). Each spawns the underlying Applications. Watch
them go green:

```bash
kubectl get applications -n argocd -w
```

Expect 6 services Ã— 3 envs (18) + 6 platform Applications + 5 observability
Applications. Initial sync takes ~10â€“15 minutes.

## 3. Log into the UI

```bash
aws secretsmanager get-secret-value \
  --region eu-south-1 \
  --secret-id "agripulse/dev/argocd-admin-password" \
  --query SecretString --output text
```

Open `https://argocd.agripulse.cloud`. User `admin`, password from above.
TLS comes from the cert-manager â†’ Let's Encrypt â†’ Route 53 DNS-01 chain that
CD-5 set up; if the page returns the staging cert, the cluster issuer
annotation is wrong â€” re-check `infra/argocd/values/argocd-server.yaml`.

If the hostname does not resolve, ExternalDNS hasn't published the A record
yet. Tail `kubectl logs -n external-dns deploy/external-dns` and look for
the `argocd-server` ingress in the change set.

## 4. Adding a chart

1. Drop the chart in `infra/helm/<name>/`.
2. Add an element to `generators.list` in `infra/argocd/appsets/services.yaml`.
3. Push. ArgoCD picks it up in the next reconcile (default 3 min).

## 5. Adding an environment

1. Add an entry to the second list in `services.yaml`'s matrix generator
   (`{env, namespace, autoSync, prune}`).
2. Create `infra/argocd/overlays/<env>/values.yaml`.
3. Push. The AppSet spans (charts Ã— envs); new envs add a row of Apps.

## 6. Failure: Application stuck in OutOfSync after a PR

```bash
# 1. Force a hard refresh â€” argocd-repo-server caches manifests.
kubectl annotate application -n argocd <app> argocd.argoproj.io/refresh=hard --overwrite

# 2. If still OutOfSync, look at the diff.
argocd app diff <app>

# 3. Retry the sync explicitly.
argocd app sync <app>

# 4. Self-heal on, prune off, dev only: nuke the live state.
argocd app sync <app> --force --replace
```

If the diff itself is empty but the status disagrees, the controller is
stuck â€” restart it: `kubectl rollout restart -n argocd statefulset/argocd-application-controller`.

## 7. Failure: ArgoCD itself is broken

ArgoCD installs ArgoCD, but cannot fix a broken `argocd-server` Deployment
because the controller serving the UI is the one that's down. Two recovery
paths:

```bash
# Most common: bad config in argocd-server.yaml pushed via Terraform.
kubectl rollout undo -n argocd deploy/argocd-server

# Full reset: re-run Terraform after fixing the values file.
cd infra/terraform && terraform apply
```

If the helm release itself is wedged (CRD conflicts, stuck finalizers), the
nuclear option is:

```bash
helm uninstall argocd -n argocd
kubectl delete crd applications.argoproj.io applicationsets.argoproj.io \
  appprojects.argoproj.io
terraform apply   # reinstalls clean
```

This loses Application history. Application *state* re-derives from the
AppSets on the next sync, so you'll get the cluster back to declared-state
within a reconcile interval; what you lose is sync history + manual
overrides in the UI.
