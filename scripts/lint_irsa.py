#!/usr/bin/env python3
"""IRSA hygiene linter.

Catches two bootstrap-time foot-guns:

1. A Helm chart values.yaml that creates its own ServiceAccount
   (``serviceAccount.create: true``) without wiring an IRSA role-arn
   annotation. Such pods fall back to the node-role, which usually has
   neither the perms they need nor the perms they shouldn't have.

2. An EKS managed add-on in ``infra/terraform/eks.tf`` that is in the
   known-IRSA-required set (e.g. ``aws-ebs-csi-driver``,
   ``aws-efs-csi-driver``) but missing ``service_account_role_arn``.
   These hang in CREATING until the IRSA wiring is added — see
   ``project_eks_addon_irsa`` memory.

Opt-outs (rule 1 only): add an HTML-style comment in the source
values.yaml near the ``serviceAccount:`` block, on its own line:

    serviceAccount:
      # irsa: not-required                    # nginx static SPA, no AWS calls
      create: true
      annotations: {}

    serviceAccount:
      # irsa: required-from-overlay           # api / workers; ARN comes from
      create: true                             # infra/argocd/overlays/<env>/values.yaml
      annotations: {}

Usage:
    python scripts/lint_irsa.py [--repo-root .]

Exits non-zero on the first uncovered violation. Run from CI helm job
or pre-commit.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    print("lint_irsa: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


# Known-required addons. Add to this set when a new managed add-on with
# its own controller pod ships — controllers that talk to AWS APIs need
# IRSA. coredns / kube-proxy / vpc-cni do not (vpc-cni IRSA is optional
# for prefix delegation; we keep it out of the required set so the
# default install doesn't trip).
ADDONS_REQUIRING_IRSA = frozenset(
    {
        "aws-ebs-csi-driver",
        "aws-efs-csi-driver",
        "aws-mountpoint-s3-csi-driver",
    }
)

IRSA_ANNOTATION = "eks.amazonaws.com/role-arn"
OPT_OUT_NOT_REQUIRED = "# irsa: not-required"
OPT_OUT_FROM_OVERLAY = "# irsa: required-from-overlay"


def lint_chart_values(path: Path) -> list[str]:
    """Return human-readable violation strings for one values.yaml.

    The file is parsed twice: once as YAML for structural checks, once
    as raw text so opt-out comments (which YAML drops) remain visible.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{path}: YAML parse error: {e}"]
    if not isinstance(data, dict):
        return []

    sa = data.get("serviceAccount")
    if not isinstance(sa, dict):
        return []
    if not sa.get("create"):
        return []

    annotations = sa.get("annotations") or {}
    has_arn = isinstance(annotations, dict) and IRSA_ANNOTATION in annotations
    if has_arn:
        return []

    if _has_optout_near_sa_block(text):
        return []

    errors.append(
        f"{path}: serviceAccount.create=true but no {IRSA_ANNOTATION} "
        f"annotation set and no opt-out comment found. Either set the "
        f"annotation (chart-level or overlay), or add "
        f"`{OPT_OUT_NOT_REQUIRED}` / `{OPT_OUT_FROM_OVERLAY}` next to "
        f"the serviceAccount: block."
    )
    return errors


def _has_optout_near_sa_block(text: str) -> bool:
    """True if an opt-out marker comment lives in the serviceAccount block."""
    in_block = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("serviceAccount:"):
            in_block = True
            continue
        if in_block:
            # End of block: a non-indented non-blank line that isn't a comment.
            if line and not line.startswith((" ", "\t", "#")):
                in_block = False
                continue
            if OPT_OUT_NOT_REQUIRED in line or OPT_OUT_FROM_OVERLAY in line:
                return True
    return False


def lint_eks_tf(path: Path) -> list[str]:
    """Flag cluster_addons entries that need IRSA but lack a role ARN.

    Uses regex rather than an HCL parser to keep this script
    dependency-light. The addon blocks we care about are flat
    name-value maps inside ``cluster_addons = {...}``.
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    block = _extract_block(text, "cluster_addons = {")
    if block is None:
        return []

    errors: list[str] = []
    for name in ADDONS_REQUIRING_IRSA:
        addon_body = _extract_block(block, f"{name} = {{")
        if addon_body is None:
            continue
        if "service_account_role_arn" not in addon_body:
            errors.append(
                f"{path}: cluster_addons.{name} is in the known-IRSA-required "
                f"set but has no `service_account_role_arn`. The add-on will "
                f"hang in CREATING. See `project_eks_addon_irsa` memory for "
                f"recovery + the iam-irsa.tf module to reference."
            )
    return errors


def _extract_block(text: str, opener: str) -> str | None:
    """Return body of a brace-balanced HCL block starting at ``opener``.

    None if the opener isn't found.
    """
    idx = text.find(opener)
    if idx == -1:
        return None
    start = idx + len(opener)
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    args = parser.parse_args(argv)
    root: Path = args.repo_root.resolve()

    errors: list[str] = []

    helm_root = root / "infra" / "helm"
    if helm_root.is_dir():
        for values in sorted(helm_root.glob("*/values.yaml")):
            errors.extend(lint_chart_values(values))

    eks_tf = root / "infra" / "terraform" / "eks.tf"
    errors.extend(lint_eks_tf(eks_tf))

    if errors:
        print("IRSA hygiene check FAILED:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            f"{len(errors)} violation(s). See docs/runbooks/irsa-hygiene.md.",
            file=sys.stderr,
        )
        return 1

    print("IRSA hygiene check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
