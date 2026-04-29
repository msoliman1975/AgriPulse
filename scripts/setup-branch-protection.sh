#!/usr/bin/env bash
# Apply MissionAgre's branch-protection ruleset to `main`.
#
# Run once per repo, then any time the required-checks list changes.
# Requires `gh auth status` to be active for an account with admin
# rights on msoliman1975/MissionAgre.
#
# Usage:
#     scripts/setup-branch-protection.sh                # apply
#     scripts/setup-branch-protection.sh --dry-run      # show payload only
#     OWNER=foo REPO=bar scripts/setup-branch-protection.sh
#
# Idempotent — re-running with the same payload yields no diff.

set -euo pipefail

OWNER="${OWNER:-msoliman1975}"
REPO="${REPO:-MissionAgre}"
BRANCH="${BRANCH:-main}"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Required-checks list. Names must exactly match the `name:` field on
# each job in .github/workflows/ci.yml. The `containers` job is included
# so a failed image build blocks merge once it goes green at least once.
REQUIRED_CHECKS=(
    "pre-commit"
    "backend"
    "frontend"
    "helm"
    "infra-tf"
    "containers"
)

# Build the JSON payload. Hand-rolled to keep the script jq-free; the
# REQUIRED_CHECKS array is the only dynamic input.
contexts_json="$(
    printf '"%s",' "${REQUIRED_CHECKS[@]}" | sed 's/,$//'
)"

PAYLOAD=$(cat <<EOF
{
    "required_status_checks": {
        "strict": false,
        "contexts": [${contexts_json}]
    },
    "enforce_admins": false,
    "required_pull_request_reviews": {
        "dismiss_stale_reviews": true,
        "require_code_owner_reviews": true,
        "required_approving_review_count": 1,
        "require_last_push_approval": false
    },
    "restrictions": null,
    "required_linear_history": true,
    "allow_force_pushes": false,
    "allow_deletions": false,
    "block_creations": false,
    "required_conversation_resolution": true,
    "lock_branch": false,
    "allow_fork_syncing": false
}
EOF
)

echo "Repo: ${OWNER}/${REPO}"
echo "Branch: ${BRANCH}"
echo "Required checks: ${REQUIRED_CHECKS[*]}"
echo

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- payload (dry-run) ---"
    if command -v jq >/dev/null 2>&1; then
        echo "$PAYLOAD" | jq .
    else
        echo "$PAYLOAD"
    fi
    exit 0
fi

echo "Applying branch protection..."
echo "$PAYLOAD" | gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
    --input -

echo
echo "Done. Verify at:"
echo "  https://github.com/${OWNER}/${REPO}/settings/branches"
